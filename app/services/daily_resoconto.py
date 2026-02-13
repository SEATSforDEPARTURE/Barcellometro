from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import discord

from app.renderers.daily_resoconto_renderer import MessageMeta, QuoteRenderItem, build_daily_resoconto_embeds, format_day_label
from app.services.barcello import BarcelloResult, BarcelloService
from app.services.database import DatabaseService
from app.services.summary import SummaryResult, SummaryService
from app.utils.summary_names import resolve_display_name_from_message_id, resolve_primary_message_id

logger = logging.getLogger(__name__)
ROME_TZ = ZoneInfo("Europe/Rome")
DUE_WINDOW_SECONDS = 600


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
        self._missed_logged: dict[str, str] = {}
        self._loop_started_logged = False

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        await self._bot.wait_until_ready()
        if not self._loop_started_logged:
            logger.info("daily_resoconto loop started interval=30s window=%ss", DUE_WINDOW_SECONDS)
            self._loop_started_logged = True
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
                already_sent_today = row["last_sent_local_date"] == today
                send_time_setting = str(row["send_time_local"])
                last_sent_time_local = str(row["last_sent_time_local"] or "")
                if already_sent_today and send_time_setting == last_sent_time_local:
                    logger.debug("daily_resoconto skip channel=%s reason=already_sent", channel_id)
                    continue
                try:
                    hh, mm = send_time_setting.split(":", 1)
                    send_local = now_local.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
                except Exception:
                    logger.warning("daily_resoconto skip channel=%s reason=invalid_time_format", channel_id)
                    continue
                delta_seconds = (now_local - send_local).total_seconds()
                if delta_seconds < 0:
                    logger.debug("daily_resoconto skip channel=%s reason=not_due_yet", channel_id)
                    continue
                if delta_seconds > DUE_WINDOW_SECONDS:
                    missed_key = f"{guild.id}:{channel_id}"
                    if self._missed_logged.get(missed_key) != today:
                        logger.warning("daily_resoconto skip channel=%s reason=missed_window delta=%.0fs", channel_id, delta_seconds)
                        self._missed_logged[missed_key] = today
                    continue
                sent = await self.generate_and_send_for_channel(str(guild.id), channel_id, manual=False)
                if sent:
                    await self._database.mark_daily_report_sent(
                        str(guild.id),
                        channel_id,
                        today,
                        local_time_str=send_time_setting,
                        sent_kind="scheduled",
                    )
                    logger.info("daily_resoconto sent ok guild=%s channel=%s", guild.id, channel_id)

    def _integrate_author_in_moment(self, text: str, display_name: str | None) -> str:
        clean = str(text or "").strip()
        if not clean:
            return clean
        if not display_name:
            return clean.replace("{AUTHOR}", "").strip()
        if "{AUTHOR}" in clean:
            return clean.replace("{AUTHOR}", display_name).strip()
        first = clean[0].lower() + clean[1:] if len(clean) > 1 else clean.lower()
        return f"{display_name} {first}".strip()

    def _sanitize_invented_names(self, text: str, allowed_names: set[str]) -> str:
        allow_tokens = {"Oggi", "Ieri", "Barcello", "Discord"}
        allowed_lower = {name.lower() for name in allowed_names}

        def repl(match: re.Match[str]) -> str:
            token = match.group(0)
            if token in allow_tokens:
                return token
            if token.lower() in allowed_lower:
                return token
            return ""

        out = re.sub(r"\b[A-Z][A-Za-zÀ-ÖØ-öø-ÿ]{2,}\b", repl, text)
        return " ".join(out.split())

    async def generate_and_send_for_channel(self, guild_id: str, channel_id: str, *, manual: bool = False) -> bool:
        channel = self._bot.get_channel(int(channel_id))
        if not isinstance(channel, discord.abc.Messageable):
            logger.warning("daily_resoconto channel not accessible guild=%s channel=%s", guild_id, channel_id)
            return False

        now_local = datetime.now(ROME_TZ)
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        start_dt = start_local.astimezone(timezone.utc)
        end_dt = now_local.astimezone(timezone.utc)
        logger.debug("daily_resoconto period guild=%s channel=%s start_utc=%s end_utc=%s", guild_id, channel_id, start_dt.isoformat(), end_dt.isoformat())
        rows = await self._database.fetch_messages_in_range(channel_id=channel_id, start_ts=start_dt.isoformat(), end_ts=end_dt.isoformat(), limit=1200)
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

        bar = await self._barcello.compute_channel_range(
            guild_id=guild_id,
            channel_id=channel_id,
            start_ts=start_dt.isoformat(),
            end_ts=end_dt.isoformat(),
        )
        bar_yesterday = await self._compute_yesterday_barcello(guild_id=guild_id, channel_id=channel_id, start_local=start_local)
        config = await self._summary.get_config()
        ai_allowed = bool(self._ai and getattr(self._ai, "is_enabled", lambda: False)())
        summary = await self._summary.build_summary(
            guild_id=guild_id,
            channel_id=channel_id,
            start_ts=start_dt.isoformat(),
            end_ts=end_dt.isoformat(),
            tier="role3",
            include_names=True,
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

        trend_value = self._build_trend_vs_yesterday(bar_today=bar, bar_yesterday=bar_yesterday)
        barcello_line = await self._get_alert_vibe_line(barcello=bar, summary_result=summary, trend_value=trend_value)
        advice, proverbio = await self._get_advice_proverbio(summary, bar.color)
        day_label = format_day_label(now_local)

        message_index: dict[str, MessageMeta] = {}
        for row in rows:
            message_id = str(row["message_id"] or "").strip()
            if message_id:
                message_index[message_id] = MessageMeta(
                    message_id=message_id,
                    ts=str(row["ts"] or "") or None,
                    author_id=str(row["author_id"] or "") or None,
                )

        moment_primary: dict[int, str | None] = {}
        quote_primary: dict[int, str | None] = {}
        dynamic_primary: dict[int, str | None] = {}

        for moment in summary.moments:
            moment_primary[id(moment)] = await resolve_primary_message_id(
                database=self._database,
                channel_id=channel_id,
                start_ts=start_dt.isoformat(),
                end_ts=end_dt.isoformat(),
                ts=moment.ts,
                message_ids=moment.message_ids,
            )
        for quote in summary.quotes:
            quote_primary[id(quote)] = await resolve_primary_message_id(
                database=self._database,
                channel_id=channel_id,
                start_ts=start_dt.isoformat(),
                end_ts=end_dt.isoformat(),
                ts=quote.ts,
                message_ids=quote.message_ids,
            )
        for dynamic in summary.dynamics:
            dynamic_primary[id(dynamic)] = await resolve_primary_message_id(
                database=self._database,
                channel_id=channel_id,
                start_ts=start_dt.isoformat(),
                end_ts=end_dt.isoformat(),
                ts=dynamic.ts,
                message_ids=dynamic.message_ids,
            )

        message_cache: dict[str, dict[str, Any]] = {}
        dynamic_names: dict[int, list[str]] = {}
        allowed_names: set[str] = set()

        for moment in summary.moments:
            primary_id = moment_primary.get(id(moment))
            display = await resolve_display_name_from_message_id(
                database=self._database,
                guild_id=guild_id,
                channel_id=channel_id,
                message_id=primary_id,
                message_cache=message_cache,
            )
            if display:
                allowed_names.add(display)
            integrated = self._integrate_author_in_moment(moment.text, display)
            moment.text = self._sanitize_invented_names(integrated, allowed_names)

        for dynamic in summary.dynamics:
            names: list[str] = []
            seen: set[str] = set()
            candidate_ids = [dynamic_primary.get(id(dynamic)), *dynamic.message_ids]
            for candidate in candidate_ids:
                display = await resolve_display_name_from_message_id(
                    database=self._database,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    message_id=candidate,
                    message_cache=message_cache,
                )
                if display and display not in seen:
                    names.append(display)
                    seen.add(display)
                    allowed_names.add(display)
                if len(names) >= 3:
                    break
            dynamic_names[id(dynamic)] = names

        for message_id in {m for m in [*moment_primary.values(), *quote_primary.values(), *dynamic_primary.values()] if m}:
            if message_id in message_index:
                continue
            record = await self._database.fetch_message_by_id(channel_id=channel_id, message_id=message_id)
            if record:
                message_index[message_id] = MessageMeta(
                    message_id=message_id,
                    ts=str(record["ts"] or "") or None,
                    author_id=str(record["author_id"] or "") or None,
                )

        quote_render_items: list[QuoteRenderItem] = []
        for quote in summary.quotes:
            primary_id = quote_primary.get(id(quote))
            quote_text: str | None = None
            quote_ts: str | None = quote.ts
            author_display: str | None = None

            if primary_id:
                record = await self._database.fetch_message_by_id(channel_id=channel_id, message_id=primary_id)
                if record:
                    raw_content = str(record["content"] or "")
                    compact = " ".join(raw_content.split()).replace("```", "'''")
                    if compact:
                        quote_text = compact[:319] + "…" if len(compact) > 320 else compact
                    quote_ts = str(record["ts"] or "") or quote_ts
                    author_display = await resolve_display_name_from_message_id(
                        database=self._database,
                        guild_id=guild_id,
                        channel_id=channel_id,
                        message_id=primary_id,
                        message_cache=message_cache,
                    )

            if not quote_text:
                fallback = str(quote.text or "").strip()
                looks_quote = fallback.startswith(('"', "“", "'")) or fallback.endswith(('"', "”", "'"))
                if looks_quote and len(fallback) <= 320:
                    quote_text = fallback.strip('"”\'“ ')
            if not quote_text:
                continue

            quote_render_items.append(
                QuoteRenderItem(
                    message_id=primary_id,
                    ts=quote_ts,
                    quote_text=quote_text,
                    author_display=author_display,
                )
            )

        channel_name = getattr(channel, "name", None) or channel_id
        embeds = build_daily_resoconto_embeds(
            guild_id=int(guild_id),
            channel_id=int(channel_id),
            channel_name=str(channel_name),
            barcello_status=bar,
            barcello_line=barcello_line,
            summary_result=summary,
            message_index=message_index,
            advice_bullets=advice,
            proverbio=proverbio,
            day_label=day_label,
            moment_primary=moment_primary,
            dynamic_primary=dynamic_primary,
            dynamic_names=dynamic_names,
            quote_render_items=quote_render_items,
            trend_value=trend_value,
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
            await self._database.mark_daily_report_sent(
                guild_id,
                channel_id,
                today,
                local_time_str=datetime.now(ROME_TZ).strftime("%H:%M"),
                sent_kind="manual",
            )
        logger.info("daily_resoconto sent guild=%s channel=%s manual=%s", guild_id, channel_id, manual)
        return True

    def _build_barcello_line(self, score: int, color: str | None, summary: SummaryResult | None) -> str:
        degrade_count = len(getattr(summary, "degrade", []) or [])
        invigorate_count = len(getattr(summary, "invigorate", []) or [])
        cautious = degrade_count > invigorate_count
        positive = invigorate_count > degrade_count
        if score >= 85:
            return "Oggi barcello in modalità SPA: chill totale, ma senza stuzzicare troppo 🌿😌" if cautious else "Oggi barcello in modalità SPA: chill totale e vibe verde 🌿😌"
        if score >= 70:
            return "Giornata stabile e in crescita: il mood gira bene, teniamolo morbido 🌱" if positive else "Giornata stabile: si respira bene, ma teniamo il mood morbido 🌱"
        if score >= 55:
            return "Barcello frizzantino: qualche scintilla c'è, andiamo di calma e ironia leggera ⚡🙂" if cautious else "Barcello frizzantino: occhio alle scintille, ma si recupera facile ⚡🙂"
        if score >= 40:
            return "Giornata piccante ma recuperabile: risposte lente e toni gentili aiutano tanto 🧯🐹" if positive else "Giornata piccante: meglio risposte lente e toni gentili 🧯🐹"
        if color == "nero" and positive:
            return "Barcello in allerta, ma con segnali di ripresa: calma, pause e zero escalation ⚫🫶"
        return "Barcello in allerta: servono calma, pause e zero escalation ⚫🫶"

    async def _get_alert_vibe_line(self, *, barcello: BarcelloResult, summary_result: SummaryResult, trend_value: str) -> str:
        ai_enabled = bool(self._ai and getattr(self._ai, "is_enabled", lambda: False)() and getattr(self._ai, "client", lambda: None)())
        if ai_enabled:
            try:
                now_local = datetime.now(ROME_TZ)
                nonce = uuid4().hex[:10]
                payload = {
                    "score": barcello.score,
                    "color": barcello.color,
                    "trend": trend_value,
                    "themes": list(summary_result.themes[:2]),
                    "nonce": nonce,
                    "ts": now_local.isoformat(),
                }
                client = self._ai.client()
                model = self._ai.get_model("summary") or "gpt-4o-mini"
                response = await client.responses.create(
                    model=model,
                    input=[
                        {
                            "role": "system",
                            "content": (
                                "Scrivi UNA sola riga in italiano (max 140 caratteri), tono simpatico, coerente con score/colore barcello. "
                                "Deve descrivere il barcello di oggi e citare esplicitamente almeno uno tra score/colore/trend/motivo. "
                                "Non parlare di cose generiche scollegate. Non usare nomi persone. "
                                "Varia stile ad ogni risposta, non ripetere formule standard, no elenco puntato."
                            ),
                        },
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                )
                line = _extract_ai_text(response).splitlines()[0].strip()
                if line:
                    line = (line[:139] + "…") if len(line) > 140 else line
                    line_l = line.lower()
                    keywords = {
                        "barcello",
                        "verde",
                        "giallo",
                        "rosso",
                        "nero",
                        "stabile",
                        "miglioramento",
                        "peggioramento",
                        "punti",
                        str(barcello.score),
                    }
                    if any(k in line_l for k in keywords):
                        return line
            except Exception:
                logger.warning("daily_resoconto alert vibe ai fallback")
        return self._build_barcello_line(barcello.score, barcello.color, summary_result)

    async def _compute_yesterday_barcello(self, *, guild_id: str, channel_id: str, start_local: datetime) -> BarcelloResult | None:
        yesterday_local = start_local - timedelta(days=1)
        y_start_local = yesterday_local.replace(hour=0, minute=0, second=0, microsecond=0)
        y_end_local = yesterday_local.replace(hour=23, minute=59, second=59, microsecond=999000)
        try:
            return await self._barcello.compute_channel_range(
                guild_id=guild_id,
                channel_id=channel_id,
                start_ts=y_start_local.astimezone(timezone.utc).isoformat(),
                end_ts=y_end_local.astimezone(timezone.utc).isoformat(),
            )
        except Exception:
            logger.exception("daily_resoconto yesterday barcello failed guild=%s channel=%s", guild_id, channel_id)
            return None

    def _build_trend_vs_yesterday(self, *, bar_today: BarcelloResult, bar_yesterday: BarcelloResult | None) -> str:
        if bar_yesterday is None:
            return "Stabile (Δ +0): confronto con ieri non disponibile."
        delta = int(bar_today.score) - int(bar_yesterday.score)
        if delta >= 4:
            direction = "In miglioramento"
        elif delta <= -4:
            direction = "In peggioramento"
        else:
            direction = "Stabile"
        today_neg = int((bar_today.metrics or {}).get("negativity_hits") or 0)
        y_neg = int((bar_yesterday.metrics or {}).get("negativity_hits") or 0)
        today_pos = int((bar_today.metrics or {}).get("positive_hits") or 0)
        y_pos = int((bar_yesterday.metrics or {}).get("positive_hits") or 0)
        if today_neg < y_neg and today_pos >= y_pos:
            reason = "meno tensione e più supporto rispetto a ieri"
        elif today_neg > y_neg:
            reason = "più frizioni e callout rispetto a ieri"
        elif today_pos > y_pos:
            reason = "più messaggi costruttivi e supporto rispetto a ieri"
        else:
            reason = "clima simile a ieri, senza scossoni rilevanti"
        return f"{direction} (Δ {delta:+d}): {reason}."

    def _fallback_advice_proverbio(self, color: str) -> tuple[list[str], str]:
        fallback = {
            "verde": (["Mantieni il tono positivo e ringrazia chi aiuta.", "Conferma i prossimi passi in modo chiaro.", "Premia i contributi costruttivi del canale."], "Chi semina bene, raccoglie meglio."),
            "giallo": (["Evita messaggi impulsivi e usa frasi brevi.", "Fai una domanda chiarificatrice prima di rispondere.", "Ricapitola i punti in disaccordo senza accuse."], "Meglio una parola in meno che una di troppo."),
            "rosso": (["Sospendi i thread accesi per qualche minuto.", "Passa da accuse a fatti verificabili.", "Coinvolgi un moderatore se il tono non cala."], "Quando il ferro è caldo, la calma vale oro."),
        }
        return fallback.get(color, (["Fermati, respira e chiarisci l'obiettivo comune.", "Riduci sarcasmo e giudizi personali.", "Riparti da regole semplici di convivenza."], "Dopo la tempesta, torna il sereno."))

    async def _get_advice_proverbio(self, summary: object, color: str) -> tuple[list[str], str]:
        color_key = (color or "").lower()
        ai_enabled = self._ai and getattr(self._ai, "is_enabled", lambda: False)() and getattr(self._ai, "client", lambda: None)()
        if ai_enabled:
            try:
                client = self._ai.client()
                model = self._ai.get_model("summary") or "gpt-4o-mini"
                payload = {"color": color, "themes": getattr(summary, "themes", []), "moments": [m.text for m in getattr(summary, "moments", [])[:4]]}
                response = await client.responses.create(
                    model=model,
                    input=[
                        {"role": "system", "content": "Rispondi in italiano. Restituisci SOLO un blocco ```json``` con schema: {\"advice_bullets\": [\"...\"], \"proverbio\": \"...\"}. advice_bullets deve avere 3-5 elementi, proverbio una sola riga."},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                )
                data = _parse_json_safe(_extract_ai_text(response))
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
