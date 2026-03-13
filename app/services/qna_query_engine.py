from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import discord

from app.services.barcello import BarcelloService
from app.services.database import DatabaseService

logger = logging.getLogger(__name__)
ROME_TZ = ZoneInfo("Europe/Rome")
NO_DATA_REPLY = "Non risultano messaggi o attività rilevanti per questa richiesta nel periodo indicato."
SUPPORTED_INTENTS = {
    "user_activity_summary",
    "topic_discussion_summary",
    "server_activity_summary",
    "user_opinion_on_topic",
    "voice_activity",
    "aura_query",
    "barcello_status",
    "user_stats",
    "conversation_between_users",
}


@dataclass
class QnaIntent:
    intent: str
    target_user: str | None
    topic: str | None
    time_range: str | None
    channel: str | None
    metric: str | None
    limit: int


class QnaQueryEngine:
    def __init__(self, *, database: DatabaseService, ai_service: Any, barcello: BarcelloService) -> None:
        self._db = database
        self._ai = ai_service
        self._barcello = barcello

    async def answer(self, *, guild_id: str, channel_id: str, question: str, source: discord.Interaction | discord.Message | None = None) -> str:
        parsed = await self._parse_intent(question)
        start_ts, end_ts, range_label = self._resolve_time_range(parsed.time_range or "", question)
        target_user_id, target_user_name = await self._resolve_target_user(parsed.target_user, question, guild_id, source)
        payload = await self._fetch_intent_data(
            intent=parsed.intent,
            guild_id=guild_id,
            channel_id=channel_id,
            target_user_id=target_user_id,
            topic=parsed.topic,
            metric=parsed.metric,
            limit=parsed.limit,
            start_ts=start_ts,
            end_ts=end_ts,
            question=question,
            source=source,
        )
        if not payload.get("has_data"):
            return NO_DATA_REPLY
        return await self._compose_answer(
            question=question,
            intent=parsed.intent,
            target_user_name=target_user_name,
            range_label=range_label,
            payload=payload,
        )

    async def _parse_intent(self, question: str) -> QnaIntent:
        fallback = self._heuristic_intent(question)
        if self._ai is None or not self._ai.is_enabled() or self._ai.client() is None:
            return fallback
        model = self._ai.get_model("summary") or "gpt-4o-mini"
        prompt = {
            "instruction": "Classifica la domanda Discord in JSON puro.",
            "schema": {
                "intent": "one_of:user_activity_summary,topic_discussion_summary,server_activity_summary,user_opinion_on_topic,voice_activity,aura_query,barcello_status,user_stats,conversation_between_users",
                "target_user": "string|null",
                "topic": "string|null",
                "time_range": "string|null",
                "channel": "string|null",
                "metric": "string|null",
                "limit": "int"
            },
            "question": question,
            "rules": ["Rispondi SOLO JSON valido", "Non aggiungere testo fuori dal JSON"],
        }
        try:
            response = await self._ai.client().responses.create(model=model, input=json.dumps(prompt, ensure_ascii=False))
            data = json.loads(str(getattr(response, "output_text", "") or "{}"))
            intent = str(data.get("intent") or "").strip()
            if intent not in SUPPORTED_INTENTS:
                return fallback
            limit = int(data.get("limit") or fallback.limit)
            return QnaIntent(
                intent=intent,
                target_user=self._clean_opt(data.get("target_user")),
                topic=self._clean_opt(data.get("topic")),
                time_range=self._clean_opt(data.get("time_range")),
                channel=self._clean_opt(data.get("channel")),
                metric=self._clean_opt(data.get("metric")),
                limit=max(3, min(20, limit)),
            )
        except Exception:
            logger.exception("qna_intent_parse_failed")
            return fallback

    def _heuristic_intent(self, question: str) -> QnaIntent:
        q = question.lower()
        intent = "server_activity_summary"
        if "aura" in q:
            intent = "aura_query"
        elif "barcello" in q:
            intent = "barcello_status"
        elif any(t in q for t in ["vocale", "chiamata", "auditorium", "voice"]):
            intent = "voice_activity"
        elif re.search(r"cosa\s+ha\s+detto|cosa\s+pensa", q):
            intent = "user_opinion_on_topic"
        elif re.search(r"tra\s+@|conversazione", q):
            intent = "conversation_between_users"
        elif re.search(r"di che ha parlato|ha parlato", q):
            intent = "user_activity_summary"
        elif re.search(r"di che si è parlato|topic|argomento", q):
            intent = "topic_discussion_summary"
        return QnaIntent(intent=intent, target_user=None, topic=None, time_range=None, channel=None, metric=None, limit=8)

    async def _resolve_target_user(self, target_user: str | None, question: str, guild_id: str, source: discord.Interaction | discord.Message | None) -> tuple[str | None, str | None]:
        mention = re.search(r"<@!?(\d+)>", question)
        if mention:
            return mention.group(1), None
        candidate = (target_user or "").strip()
        if not candidate:
            return None, None
        if source and getattr(source, "guild", None):
            guild = source.guild
            for member in getattr(guild, "members", []):
                name = f"{getattr(member, 'display_name', '')} {getattr(member, 'name', '')}".lower()
                if candidate.lower() in name:
                    return str(member.id), getattr(member, "display_name", None)
        rows = await self._db.fetchall(
            """
            SELECT gm.user_id, COALESCE(gm.nickname, u.display_name, u.global_name, u.username, gm.user_id) AS display
            FROM guild_memberships gm
            LEFT JOIN users u ON u.user_id = gm.user_id
            WHERE gm.guild_id = ?
            """,
            (guild_id,),
        )
        for row in rows:
            display = str(row["display"] or "")
            if candidate.lower() in display.lower():
                return str(row["user_id"]), display
        return None, candidate

    def _resolve_time_range(self, parsed: str, question: str) -> tuple[str, str, str]:
        q = f"{parsed} {question}".lower()
        now = datetime.now(timezone.utc)
        today = datetime.now(ROME_TZ).date()
        if "ultima ora" in q:
            return (now - timedelta(hours=1)).isoformat(), now.isoformat(), "ultima ora"
        if "ieri" in q:
            start = datetime.combine(today - timedelta(days=1), datetime.min.time(), tzinfo=ROME_TZ).astimezone(timezone.utc)
            end = datetime.combine(today, datetime.min.time(), tzinfo=ROME_TZ).astimezone(timezone.utc)
            return start.isoformat(), end.isoformat(), "ieri"
        if "oggi" in q or "adesso" in q:
            start = datetime.combine(today, datetime.min.time(), tzinfo=ROME_TZ).astimezone(timezone.utc)
            return start.isoformat(), now.isoformat(), "oggi"
        if "settimana" in q or "7 giorni" in q:
            return (now - timedelta(days=7)).isoformat(), now.isoformat(), "ultimi 7 giorni"
        return (now - timedelta(hours=24)).isoformat(), now.isoformat(), "ultime 24 ore"

    async def _fetch_intent_data(self, **kwargs: Any) -> dict[str, Any]:
        intent = kwargs["intent"]
        if intent == "barcello_status":
            status = await self._barcello.get_current_status(kwargs["guild_id"], channel_id=kwargs["channel_id"]) 
            return {"has_data": True, "barcello": status}
        if intent == "aura_query":
            user_id = kwargs.get("target_user_id")
            if not user_id:
                return {"has_data": False}
            total = await self._db.sum_aura_points(kwargs["guild_id"], user_id)
            events = await self._db.fetch_aura_ledger_events(kwargs["guild_id"], user_id, kwargs["start_ts"], kwargs["end_ts"])
            return {"has_data": bool(events) or total != 0, "aura_total": total, "events": events[:8]}
        if intent == "voice_activity":
            sessions = await self._db.fetch_voice_sessions_in_range(
                guild_id=kwargs["guild_id"],
                voice_channel_id=kwargs["channel_id"],
                start_ts=kwargs["start_ts"],
                end_ts=kwargs["end_ts"],
            )
            minutes = 0
            for row in sessions:
                started = datetime.fromisoformat(str(row["started_ts"]).replace("Z", "+00:00"))
                ended_raw = str(row["ended_ts"] or kwargs["end_ts"])
                ended = datetime.fromisoformat(ended_raw.replace("Z", "+00:00"))
                minutes += max(0, int((ended - started).total_seconds() // 60))
            return {"has_data": bool(sessions), "voice_minutes": minutes, "sessions": [dict(r) for r in sessions[:10]]}

        rows = await self._db.fetch_qna_messages(
            guild_id=kwargs["guild_id"],
            start_ts=kwargs["start_ts"],
            end_ts=kwargs["end_ts"],
            limit=kwargs["limit"],
            user_id=kwargs.get("target_user_id"),
            topic=kwargs.get("topic"),
        )
        if intent == "conversation_between_users":
            rows = await self._db.fetch_qna_conversation_between_users(
                guild_id=kwargs["guild_id"],
                user_a_id=kwargs.get("target_user_id"),
                question=kwargs["question"],
                start_ts=kwargs["start_ts"],
                end_ts=kwargs["end_ts"],
                limit=kwargs["limit"],
            )
        if intent == "user_stats" and kwargs.get("target_user_id"):
            stats = await self._db.fetch_qna_user_stats(
                guild_id=kwargs["guild_id"],
                user_id=kwargs["target_user_id"],
                start_ts=kwargs["start_ts"],
                end_ts=kwargs["end_ts"],
            )
            return {"has_data": bool(stats.get("messages")), "stats": stats}
        return {"has_data": bool(rows), "messages": rows}

    async def _compose_answer(self, *, question: str, intent: str, target_user_name: str | None, range_label: str, payload: dict[str, Any]) -> str:
        if self._ai is None or not self._ai.is_enabled() or self._ai.client() is None:
            if payload.get("barcello"):
                return f"Barcello ora: {payload['barcello'].get('color')} (score {payload['barcello'].get('score')})."
            if payload.get("aura_total") is not None:
                return f"Aura totale nel periodo: {payload.get('aura_total')} punti."
            return "Ho raccolto i dati richiesti, ma la generazione AI non è disponibile ora."
        model = self._ai.get_model("summary") or "gpt-4o-mini"
        prompt = {
            "system": "Sei il motore /domanda del server Discord. Rispondi in italiano, sintetico ma informativo, usando SOLO i dati forniti.",
            "question": question,
            "intent": intent,
            "target_user": target_user_name,
            "time_range": range_label,
            "data": payload,
            "rules": [
                "Non inventare.",
                "Se i dati sono scarsi, dillo in modo trasparente.",
                "Massimo 6 bullet o 1 breve paragrafo.",
            ],
        }
        response = await self._ai.client().responses.create(model=model, input=json.dumps(prompt, ensure_ascii=False))
        text = str(getattr(response, "output_text", "") or "").strip()
        return text or NO_DATA_REPLY

    @staticmethod
    def _clean_opt(value: Any) -> str | None:
        text = str(value or "").strip()
        return text if text else None
