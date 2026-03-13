from __future__ import annotations

import json
import logging
import re
import unicodedata
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
        self._intent_response_format_supported: bool | None = None

    async def answer(self, *, guild_id: str, channel_id: str, question: str, source: discord.Interaction | discord.Message | None = None) -> str:
        parsed = await self._parse_intent(question)
        start_ts, end_ts, range_label = self._resolve_time_range(parsed.time_range or "", question)
        target_user_id, target_user_name = await self._resolve_target_user(parsed.target_user, question, guild_id, source)
        if parsed.target_user and target_user_id is None and self._intent_requires_user(parsed.intent):
            return "Per identificare bene la persona, taggala direttamente nella domanda con @utente."
        resolved_channel_id, resolved_channel_name = self._resolve_channel(parsed.channel, question, source)
        if parsed.intent == "voice_activity" and parsed.channel and not resolved_channel_id:
            return "Non riesco a capire quale canale vocale devo analizzare."
        payload = await self._fetch_intent_data(
            intent=parsed.intent,
            guild_id=guild_id,
            channel_id=channel_id,
            resolved_channel_id=resolved_channel_id,
            resolved_channel_name=resolved_channel_name,
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
            if payload.get("needs_user_tag"):
                return "Per identificare bene le persone, taggale direttamente nella domanda con @utente."
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
            "instruction": "Classifica la domanda di una community Discord italiana in JSON puro.",
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
            "rules": [
                "Rispondi SOLO JSON valido.",
                "Non aggiungere testo fuori dal JSON.",
                "Non usare markdown e non usare code fences.",
                "Intents disponibili: user_activity_summary, topic_discussion_summary, server_activity_summary, user_opinion_on_topic, voice_activity, aura_query, barcello_status, user_stats, conversation_between_users.",
                "Usa user_opinion_on_topic per domande come 'cosa pensa X di Y' o 'cosa ha detto X su Y'.",
                "Usa user_activity_summary per domande come 'di che ha parlato X ieri'.",
                "Usa topic_discussion_summary per domande come 'di che si è parlato ieri'.",
                "Le mention Discord come <@123> rappresentano utenti, non topic.",
                "Non usare l'ID numerico di chi fa la domanda come topic.",
                "Per 'cosa pensa X di Y', X è target_user e Y è topic.",
                "Per 'di che ha parlato X ieri', X è target_user e topic deve essere null.",
                "Se non c'è un topic testuale chiaro, topic = null.",
                "Copia target_user/topic/time_range/channel quando presenti nella domanda.",
            ],
            "examples": [
                {"question": "di che ha parlato <@123> ieri?", "json": {"intent": "user_activity_summary", "target_user": "<@123>", "topic": None, "time_range": "ieri", "channel": None, "metric": None, "limit": 8}},
                {"question": "cosa pensa Luca di Sanremo?", "json": {"intent": "user_opinion_on_topic", "target_user": "Luca", "topic": "Sanremo", "time_range": None, "channel": None, "metric": None, "limit": 8}},
                {"question": "cosa ha detto <@123> su Eurovision ieri?", "json": {"intent": "user_opinion_on_topic", "target_user": "<@123>", "topic": "Eurovision", "time_range": "ieri", "channel": None, "metric": None, "limit": 8}},
                {"question": "quanta aura ha <@123>?", "json": {"intent": "aura_query", "target_user": "<@123>", "topic": None, "time_range": None, "channel": None, "metric": None, "limit": 8}},
            ],
        }
        try:
            logger.info("qna_intent_parse model=%s", model)
            response = await self._create_intent_response(model, prompt)
            raw_text = self._extract_response_text(response)
            clean_text = self._strip_json_fences(raw_text)
            data = json.loads(clean_text)
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
        except Exception:  # noqa: BLE001
            logger.exception(
                "qna_intent_parse_failed raw_text=%s clean_text=%s",
                locals().get("raw_text", "")[:500],
                locals().get("clean_text", "")[:500],
            )
            return fallback

    @staticmethod
    def _strip_json_fences(text: str) -> str:
        cleaned = (text or "").strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        if cleaned.startswith("```"):
            cleaned = cleaned[3:].strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
        if cleaned.startswith("{") and cleaned.endswith("}"):
            return cleaned
        start = cleaned.find("{")
        if start < 0:
            return cleaned
        depth = 0
        for idx in range(start, len(cleaned)):
            char = cleaned[idx]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return cleaned[start : idx + 1].strip()
        return cleaned

    async def _create_intent_response(self, model: str, prompt: dict[str, Any]) -> Any:
        if self._intent_response_format_supported is False:
            return await self._ai.client().responses.create(model=model, input=json.dumps(prompt, ensure_ascii=False))
        try:
            response = await self._ai.client().responses.create(
                model=model,
                input=json.dumps(prompt, ensure_ascii=False),
                response_format={"type": "json_object"},
            )
            self._intent_response_format_supported = True
            return response
        except Exception as exc:  # noqa: BLE001
            if "response_format" not in str(exc):
                raise
            self._intent_response_format_supported = False
            return await self._ai.client().responses.create(model=model, input=json.dumps(prompt, ensure_ascii=False))

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
        return QnaIntent(
            intent=intent,
            target_user=self._extract_target_user_hint(question),
            topic=self._extract_topic_hint(question),
            time_range=self._extract_time_range_hint(question),
            channel=self._extract_channel_hint(question),
            metric=None,
            limit=8,
        )

    def _extract_time_range_hint(self, question: str) -> str | None:
        q = question.lower()
        for token in ["ieri", "oggi", "ultima ora", "ultimi 7 giorni", "settimana", "adesso"]:
            if token in q:
                return token
        return None

    def _extract_target_user_hint(self, question: str) -> str | None:
        mention = re.search(r"<@!?(\d+)>", question)
        if mention:
            return mention.group(1)
        patterns = [
            r"di che ha parlato\s+([\w._-]+)",
            r"ha parlato\s+con\s+([\w._-]+)",
            r"cosa pensa\s+([\w._-]+)\s+di",
            r"cosa ha detto\s+([\w._-]+)\s+su",
            r"quanta aura ha\s+([\w._-]+)",
            r"chi ha parlato con\s+([\w._-]+)",
            r"conversazione tra\s+([\w._-]+)\s+e\s+[\w._-]+",
        ]
        for pattern in patterns:
            match = re.search(pattern, question, re.IGNORECASE)
            if match:
                return match.group(1).strip("@ ")
        return None

    def _extract_topic_hint(self, question: str) -> str | None:
        patterns = [
            r"cosa pensa\s+[\w._-]+\s+di\s+(.+?)(?:\?|$)",
            r"cosa ha detto\s+[\w._-]+\s+su\s+(.+?)(?:\?|$)",
            r"ha detto\s+.+?\s+su\s+(.+?)(?:\?|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, question, re.IGNORECASE)
            if match:
                return self._sanitize_topic_candidate(match.group(1))
        return None

    @staticmethod
    def _sanitize_topic_candidate(text: str | None) -> str | None:
        candidate = str(text or "").strip(" ?!.,")
        if not candidate:
            return None
        if re.fullmatch(r"<@!?\d+>", candidate):
            return None
        if re.fullmatch(r"\d{6,}", candidate):
            return None
        if "<@" in candidate and re.sub(r"<@!?\d+>", "", candidate).strip() == "":
            return None
        return candidate

    @staticmethod
    def _normalize_match_text(text: str) -> str:
        lowered = unicodedata.normalize("NFKD", str(text or "").lower())
        lowered = "".join(ch for ch in lowered if not unicodedata.combining(ch))
        lowered = re.sub(r"[._-]+", " ", lowered)
        lowered = re.sub(r"\s+", " ", lowered)
        return lowered.strip()

    def _score_candidate_match(self, query: str, candidate: str) -> int:
        q = self._normalize_match_text(query)
        c = self._normalize_match_text(candidate)
        if not q or not c:
            return 0
        if q == c:
            return 100
        if c.startswith(q):
            return 85
        q_tokens = [t for t in q.split(" ") if t]
        c_tokens = set(c.split(" "))
        if q_tokens and all(token in c_tokens for token in q_tokens):
            return 70
        if q in c:
            return 55
        return 0

    def _extract_channel_hint(self, question: str) -> str | None:
        match = re.search(r"in\s+([a-zA-Z0-9_-]{2,})", question, re.IGNORECASE)
        if match:
            return match.group(1)
        if "auditorium" in question.lower():
            return "auditorium"
        return None

    async def _resolve_target_user(self, target_user: str | None, question: str, guild_id: str, source: discord.Interaction | discord.Message | None) -> tuple[str | None, str | None]:
        mention = re.search(r"<@!?(\d+)>", question)
        if mention:
            mention_id = mention.group(1)
            if source and getattr(source, "guild", None):
                member = source.guild.get_member(int(mention_id))
                if member is not None:
                    return mention_id, getattr(member, "display_name", None) or getattr(member, "name", None)
            return mention_id, None
        candidate = (target_user or "").strip()
        if not candidate:
            return None, None
        best: tuple[int, str | None, str | None] = (0, None, None)
        second_best = 0

        def _consider(score: int, user_id: str | None, name: str | None) -> None:
            nonlocal best, second_best
            if score <= 0:
                return
            if score > best[0]:
                second_best = best[0]
                best = (score, user_id, name)
            elif score == best[0]:
                second_best = score
            elif score > second_best:
                second_best = score

        if source and getattr(source, "guild", None):
            guild = source.guild
            for member in getattr(guild, "members", []):
                candidate_names = [
                    str(getattr(member, "display_name", "") or ""),
                    str(getattr(member, "name", "") or ""),
                    str(getattr(member, "global_name", "") or ""),
                    str(getattr(member, "nick", "") or ""),
                ]
                score = max((self._score_candidate_match(candidate, item) for item in candidate_names if item), default=0)
                _consider(score, str(member.id), getattr(member, "display_name", None) or getattr(member, "name", None))
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
            score = self._score_candidate_match(candidate, display)
            _consider(score, str(row["user_id"]), display)
        if best[1] and best[0] >= 55 and second_best < best[0]:
            return best[1], best[2]
        return None, candidate

    @staticmethod
    def _intent_requires_user(intent: str) -> bool:
        return intent in {
            "user_activity_summary",
            "user_opinion_on_topic",
            "aura_query",
            "user_stats",
            "conversation_between_users",
        }

    def _resolve_channel(self, parsed_channel: str | None, question: str, source: discord.Interaction | discord.Message | None) -> tuple[str | None, str | None]:
        guild = getattr(source, "guild", None) if source else None
        if guild is None:
            return None, parsed_channel
        query = (parsed_channel or self._extract_channel_hint(question) or "").strip().lower()
        if not query:
            return None, None
        for channel in getattr(guild, "channels", []):
            name = str(getattr(channel, "name", "") or "").lower()
            if name == query and isinstance(channel, discord.VoiceChannel):
                return str(channel.id), getattr(channel, "name", None)
        for channel in getattr(guild, "channels", []):
            name = str(getattr(channel, "name", "") or "").lower()
            if query in name and isinstance(channel, discord.VoiceChannel):
                return str(channel.id), getattr(channel, "name", None)
        return None, parsed_channel

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
            voice_channel_id = kwargs.get("resolved_channel_id") or kwargs.get("channel_id")
            sessions = await self._db.fetch_voice_sessions_in_range(
                guild_id=kwargs["guild_id"],
                voice_channel_id=voice_channel_id,
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

        topic = self._sanitize_topic_candidate(kwargs.get("topic"))
        if kwargs["intent"] == "user_activity_summary":
            pool_limit = max(kwargs["limit"], 50)
        elif kwargs["intent"] == "user_opinion_on_topic" and topic:
            pool_limit = max(kwargs["limit"], 80)
        else:
            pool_limit = max(kwargs["limit"], 30 if kwargs.get("target_user_id") else kwargs["limit"])
        rows = await self._db.fetch_qna_messages(
            guild_id=kwargs["guild_id"],
            start_ts=kwargs["start_ts"],
            end_ts=kwargs["end_ts"],
            limit=kwargs["limit"],
            candidate_pool_limit=pool_limit,
            user_id=kwargs.get("target_user_id"),
            topic=topic,
        )
        if intent == "conversation_between_users":
            if not kwargs.get("target_user_id"):
                return {"has_data": False, "needs_user_tag": True}
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
            "system": "Sei il motore /domanda del server Discord. Rispondi in italiano, in modo preciso, usando solo i dati forniti.",
            "question": question,
            "intent": intent,
            "target_user": target_user_name,
            "time_range": range_label,
            "data": payload,
            "rules": [
                "Non inventare.",
                "Se i dati sono scarsi, dillo in modo trasparente.",
                "Se la domanda è 'di che ha parlato X', sintetizza temi ricorrenti invece di copiare messaggi casuali.",
                "Non ripetere la domanda.",
                "Non usare disclaimer inutili.",
                "Non iniziare mai con la parola 'Risposta'.",
                "Massimo 6 bullet o 1 breve paragrafo.",
            ],
        }
        response = await self._ai.client().responses.create(model=model, input=json.dumps(prompt, ensure_ascii=False))
        text = self._extract_response_text(response)
        if text:
            return text
        return self._compose_local_fallback(intent=intent, range_label=range_label, payload=payload)

    def _compose_local_fallback(self, *, intent: str, range_label: str, payload: dict[str, Any]) -> str:
        if payload.get("barcello"):
            return f"Barcello ora: {payload['barcello'].get('color')} (score {payload['barcello'].get('score')})."
        if payload.get("aura_total") is not None:
            return f"Aura totale nel periodo: {payload.get('aura_total')} punti."
        if intent == "voice_activity":
            return f"Nel periodo {range_label} risultano {len(payload.get('sessions') or [])} sessioni vocali per un totale di {payload.get('voice_minutes') or 0} minuti."
        messages = payload.get("messages") or []
        if messages:
            top = messages[:3]
            bullets = [f"- {str(row.get('author_name') or 'utente')}: {str(row.get('content') or '')[:120]}" for row in top]
            return "Messaggi trovati:\n" + "\n".join(bullets)
        return NO_DATA_REPLY

    @staticmethod
    def _extract_response_text(response: Any) -> str:
        output_text = str(getattr(response, "output_text", "") or "").strip()
        if output_text:
            return output_text
        chunks: list[str] = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                text = getattr(content, "text", None)
                if text:
                    chunks.append(str(text))
        return "\n".join(chunks).strip()

    @staticmethod
    def _clean_opt(value: Any) -> str | None:
        text = str(value or "").strip()
        return text if text else None
