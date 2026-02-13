from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import discord

from app.renderers.daily_resoconto_renderer import MessageMeta, build_daily_resoconto_embeds, format_day_label
from app.services.barcello import BarcelloService
from app.services.database import DatabaseService
from app.services.summary import SummaryService

logger = logging.getLogger(__name__)
ROME_TZ = ZoneInfo("Europe/Rome")
DUE_WINDOW_SECONDS = 90


def _extract_ai_text(response: Any) -> str:
    output_text = getattr(response, "output_text", "") or ""
    if output_text:
        return output_text
    output = getattr(response, "output", None)
    if not isinstance(output, list):
        return ""
    parts: list[str] = []
    for item in output:
        contents = getattr(item, "content", None)
        if not isinstance(contents, list):
            continue
        for content in contents:
            text = getattr(content, "text", None)
            if not text and getattr(content, "type", None) in {"output_text", "text"}:
                text = getattr(content, "value", None)
            if isinstance(text, str) and text:
                parts.append(text)
    return "\n".join(parts).strip()


def _parse_json_safe(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    fenced_matches = re.findall(r"```json\s*(\{[\s\S]*?\})\s*```", raw, flags=re.IGNORECASE)
    for fenced in fenced_matches:
        try:
            parsed = json.loads(fenced)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue

    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


class DailyResocontoService:
    def __init__(
        self,
        database: DatabaseService,
        bot: discord.Client,
        summary_service: SummaryService,
        barcello_service: BarcelloService,
        ai_service: object | None = None,
    ) -> None:
        self._database = database
        self._bot = bot
        self._summary = summary_service
        self._barcello = barcello_service
        self._ai = ai_service
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        await self._bot.wait_until_ready()
        while True:
            try:
                await self.run_once()
            except Exception:
                logger.exception("daily_resoconto tick failed")
            await asyncio.sleep(30)

    async def run_once(self) -> None:
        now_utc = datetime.now(timezone.utc)
        now_local = now_utc.astimezone(ROME_TZ)
        for guild in self._bot.guilds:
            rows = await self._database.list_enabled_daily_report_channels(str(guild.id))
            for row in rows:
                channel_id = str(row["channel_id"])
                today = now_local.date().isoformat()
                if row["last_sent_local_date"] == today:
                    logger.debug("daily_resoconto skip channel=%s reason=already_sent", channel_id)
                    continue
                try:
                    hh, mm = str(row["send_time_local"]).split(":", 1)
                    send_local = now_local.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
                except Exception:
                    logger.warning("daily_resoconto skip channel=%s reason=invalid_time_format", channel_id)
                    continue
                delta_seconds = (now_local - send_local).total_seconds()
                if delta_seconds < 0:
                    logger.debug("daily_resoconto skip channel=%s reason=not_due_yet", channel_id)
                    continue
                if delta_seconds > DUE_WINDOW_SECONDS:
                    logger.debug(
                        "daily_resoconto skip channel=%s reason=missed_window delta=%.0fs",
                        channel_id,
                        delta_seconds,
                    )
                    continue
                sent = await self.generate_and_send_for_channel(str(guild.id), channel_id, manual=False)
                if sent:
                    await self._database.mark_daily_report_sent(str(guild.id), channel_id, today)
                    logger.info("daily_resoconto sent ok guild=%s channel=%s", guild.id, channel_id)

    async def generate_and_send_for_channel(self, guild_id: str, channel_id: str, *, manual: bool = False) -> bool:
        channel = self._bot.get_channel(int(channel_id))
        if not isinstance(channel, discord.abc.Messageable):
            logger.warning("daily_resoconto channel not accessible guild=%s channel=%s", guild_id, channel_id)
            return False

        now_local = datetime.now(ROME_TZ)
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        start_dt = start_local.astimezone(timezone.utc)
        end_dt = now_local.astimezone(timezone.utc)
        rows = await self._database.fetch_messages_in_range(
            channel_id=channel_id,
            start_ts=start_dt.isoformat(),
            end_ts=end_dt.isoformat(),
            limit=1200,
        )
        messages = [
            {
                "ts": row["ts"],
                "author_id": str(row["author_id"] or "") or None,
                "content": str(row["content"] or ""),
                "message_id": str(row["message_id"] or "") or None,
                "meta": {"kind": "chat", "in_call": False},
            }
            for row in rows
            if str(row["content"] or "").strip()
        ]

        bar = await self._barcello.compute_channel(guild_id, channel_id, 1440, now_ts=end_dt.isoformat())
        config = await self._summary.get_config()
        ai_allowed = bool(self._ai and getattr(self._ai, "is_enabled", lambda: False)())
        summary = await self._summary.build_summary(
            guild_id=guild_id,
            channel_id=channel_id,
            start_ts=start_dt.isoformat(),
            end_ts=end_dt.isoformat(),
            tier="role3",
            include_names=False,
            ai_allowed=ai_allowed,
            evidence_mode=False,
            voice_context=False,
            config=config,
            barcello_metrics=bar.metrics,
            max_message_ts=messages[-1]["ts"] if messages else None,
            messages=messages,
            granularity_hint="days",
            summary_mode="daily_report",
        )

        tones = self._build_tone_line(bar.metrics)
        advice, proverbio = await self._get_advice_proverbio(summary, bar.color)
        day_label = format_day_label(now_local)

        referenced_message_ids: set[str] = set()
        for item in summary.moments:
            referenced_message_ids.update(str(mid) for mid in item.message_ids if str(mid).strip())
        for item in summary.quotes:
            referenced_message_ids.update(str(mid) for mid in item.message_ids if str(mid).strip())
        for item in summary.dynamics:
            referenced_message_ids.update(str(mid) for mid in item.message_ids if str(mid).strip())

        message_index: dict[str, MessageMeta] = {}
        for row in rows:
            message_id = str(row["message_id"] or "").strip()
            if message_id:
                message_index[message_id] = MessageMeta(message_id=message_id, ts=str(row["ts"] or "") or None)

        for message_id in referenced_message_ids:
            if message_id in message_index:
                continue
            record = await self._database.fetch_message_by_id(channel_id=channel_id, message_id=message_id)
            if record:
                message_index[message_id] = MessageMeta(message_id=message_id, ts=str(record["ts"] or "") or None)

        channel_name = getattr(channel, "name", None) or channel_id
        embeds = build_daily_resoconto_embeds(
            guild_id=int(guild_id),
            channel_id=int(channel_id),
            channel_name=str(channel_name),
            barcello_status=bar,
            tones_line=tones,
            summary_result=summary,
            message_index=message_index,
            advice_bullets=advice,
            proverbio=proverbio,
            day_label=day_label,
        )
        embeds[0].set_footer(text="Stima calcolata in loco. Può variare in base ai dati disponibili.")
        for embed in embeds[1:]:
            embed.set_footer(text="")
        if len(embeds) > 1:
            ai_status = getattr(summary, "ai_status", {}) or {}
            ai_used = bool(ai_status.get("enabled"))
            model_name = str(ai_status.get("model") or getattr(self._ai, "get_model", lambda _k: None)("summary") or "")
            if ai_used and model_name:
                embeds[-1].set_footer(text=f"Resoconto elaborato con {model_name}. Eventuali imprecisioni sono possibili.")
            else:
                embeds[-1].set_footer(text="Resoconto elaborato in loco. Eventuali imprecisioni sono possibili.")
        try:
            await channel.send(embeds=embeds)
        except discord.HTTPException:
            logger.exception("daily_resoconto send failed guild=%s channel=%s", guild_id, channel_id)
            return False
        if manual:
            today = datetime.now(ROME_TZ).date().isoformat()
            await self._database.mark_daily_report_sent(guild_id, channel_id, today)
        logger.info("daily_resoconto sent guild=%s channel=%s manual=%s", guild_id, channel_id, manual)
        return True

    def _build_tone_line(self, metrics: dict[str, object]) -> str:
        negativity_hits = int(metrics.get("negativity_hits") or 0)
        positive_hits = int(metrics.get("positive_hits") or 0)
        questions = int(metrics.get("questions") or 0)
        if negativity_hits > 0:
            return "tono con tensione e bisogno di chiarimenti 🧯"
        if positive_hits > 0:
            return "tono collaborativo e scambi costruttivi 🌿"
        if questions > 1:
            return "giornata ricca di domande e chiarimenti ❓"
        return "scambi regolari e ritmo stabile 🌤️"

    def _fallback_advice_proverbio(self, color: str) -> tuple[list[str], str]:
        fallback = {
            "verde": (
                [
                    "Mantieni il tono positivo e ringrazia chi aiuta.",
                    "Conferma i prossimi passi in modo chiaro.",
                    "Premia i contributi costruttivi del canale.",
                ],
                "Chi semina bene, raccoglie meglio.",
            ),
            "giallo": (
                [
                    "Evita messaggi impulsivi e usa frasi brevi.",
                    "Fai una domanda chiarificatrice prima di rispondere.",
                    "Ricapitola i punti in disaccordo senza accuse.",
                ],
                "Meglio una parola in meno che una di troppo.",
            ),
            "rosso": (
                [
                    "Sospendi i thread accesi per qualche minuto.",
                    "Passa da accuse a fatti verificabili.",
                    "Coinvolgi un moderatore se il tono non cala.",
                ],
                "Quando il ferro è caldo, la calma vale oro.",
            ),
        }
        return fallback.get(
            color,
            (
                [
                    "Fermati, respira e chiarisci l'obiettivo comune.",
                    "Riduci sarcasmo e giudizi personali.",
                    "Riparti da regole semplici di convivenza.",
                ],
                "Dopo la tempesta, torna il sereno.",
            ),
        )

    async def _get_advice_proverbio(self, summary: object, color: str) -> tuple[list[str], str]:
        color_key = (color or "").lower()
        ai_enabled = self._ai and getattr(self._ai, "is_enabled", lambda: False)() and getattr(self._ai, "client", lambda: None)()
        if ai_enabled:
            try:
                client = self._ai.client()
                model = self._ai.get_model("summary") or "gpt-4o-mini"
                payload = {
                    "color": color,
                    "themes": getattr(summary, "themes", []),
                    "moments": [m.text for m in getattr(summary, "moments", [])[:4]],
                }
                response = await client.responses.create(
                    model=model,
                    input=[
                        {
                            "role": "system",
                            "content": (
                                "Rispondi in italiano. Restituisci SOLO un blocco ```json``` con schema: "
                                '{"advice_bullets": ["..."], "proverbio": "..."}. '
                                "advice_bullets deve avere 3-5 elementi, proverbio una sola riga."
                            ),
                        },
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                )
                text = _extract_ai_text(response)
                data = _parse_json_safe(text)
                if not data:
                    raise ValueError("invalid_json")
                advice_raw = [str(x).strip() for x in data.get("advice_bullets", []) if str(x).strip()]
                advice = [item[:160] for item in advice_raw][:5]
                proverbio = str(data.get("proverbio") or "").strip()
                if advice and proverbio:
                    return advice, proverbio
                raise ValueError("missing_fields")
            except Exception as exc:
                logger.warning("daily_resoconto advice fallback reason=%s", exc.__class__.__name__)
        else:
            logger.info("daily_resoconto advice fallback reason=ai_disabled")
        return self._fallback_advice_proverbio(color_key)
