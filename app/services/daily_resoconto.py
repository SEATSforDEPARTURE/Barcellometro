from __future__ import annotations

import asyncio
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
from app.utils.summary_names import resolve_display_name_from_message_id, resolve_primary_message_id, safe_display_name

logger = logging.getLogger(__name__)
ROME_TZ = ZoneInfo("Europe/Rome")
DUE_WINDOW_SECONDS = 600



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

    def _cleanup_placeholder_artifacts(self, text: str, *, had_author_placeholder: bool, has_display_name: bool) -> str:
        clean = str(text or "")
        clean = re.sub(r"\s+a\s*,\s*", " ", clean)
        clean = re.sub(r"\s*,\s*", ", ", clean)
        clean = re.sub(r",\s*,+", ", ", clean)
        clean = re.sub(r",\s*([\.!\?])", r"\1", clean)
        clean = re.sub(r"^[\s,–—-]+", "", clean)
        clean = re.sub(r"^,\s+", "", clean)
        clean = re.sub(r"\s{2,}", " ", clean).strip()

        lower_clean = clean.lower()
        if not has_display_name and had_author_placeholder:
            if lower_clean.startswith("tardi,"):
                clean = f"Più {clean[0].lower() + clean[1:] if clean else ''}"
            if re.match(r"^(ha\b|ha condiviso\b)", clean, flags=re.IGNORECASE):
                clean = f"Qualcuno {clean[0].lower() + clean[1:] if clean else ''}".strip()

        return clean.strip()

    def _apply_author_placeholder(self, text: str, display_name: str | None) -> str:
        clean = str(text or "").strip()
        if not clean:
            return clean
        display = safe_display_name(display_name)
        had_placeholder = "{AUTHOR}" in clean
        if had_placeholder:
            clean = clean.replace("{AUTHOR}", display or "")
        clean = self._cleanup_placeholder_artifacts(
            clean,
            had_author_placeholder=had_placeholder,
            has_display_name=bool(display),
        )
        if not clean:
            return "Qualcuno ha partecipato alla conversazione in modo costruttivo."
        return clean

    def _sanitize_moment_text(self, text: str) -> str:
        clean = str(text or "").strip()
        if not clean:
            return clean
        clean = re.sub(r"^(?:alba|mattina|pomeriggio|sera)\s*,\s+", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"^[^\wÀ-ÖØ-öø-ÿA-Za-z0-9#]{1,4}\s+", "", clean)
        return " ".join(clean.split())

    def _contains_vague_actor(self, text: str) -> bool:
        return bool(re.search(r"\b(un membro|una persona|qualcuno|diverse persone|alcuni membri)\b", str(text or ""), flags=re.IGNORECASE))

    def _ensure_past_tense_vibe(self, text: str, bar: BarcelloResult) -> str:
        raw = " ".join(str(text or "").split())
        if raw:
            raw = raw.replace("\n", " ").strip()
            raw = (raw[:139] + "…") if len(raw) > 140 else raw
            if re.search(r"\b(è stato|è rimasto|ha tenuto|si è mantenuto|si è stabilizzato|ha chiuso)\b", raw, flags=re.IGNORECASE):
                return raw
        return f"Nella giornata di oggi il barcello è rimasto {bar.color} ({bar.score}/100), con un clima complessivamente disteso."

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
            summary_mode="daily_resoconto",
            summary_context={
                "score": bar.score,
                "color": bar.color,
                "barcello_verde": (bar.color == "verde" and int(bar.score) >= 70),
                "nonce": f"{now_local.isoformat()}-{uuid4().hex[:10]}",
            },
        )

        trend_value = self._build_trend_vs_yesterday(bar_today=bar, bar_yesterday=bar_yesterday)
        barcello_line = self._ensure_past_tense_vibe(getattr(summary, "vibe_line", None), bar)
        advice = [str(x).strip()[:160] for x in (getattr(summary, "advice", []) or []) if str(x).strip()][:5]
        proverbio = str(getattr(summary, "proverbio", "") or "").strip()
        if not advice or not proverbio:
            fallback_advice, fallback_proverbio = self._fallback_advice_proverbio(bar.color)
            if not advice:
                advice = fallback_advice
            if not proverbio:
                proverbio = fallback_proverbio
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
        is_green = (bar.color == "verde" and int(bar.score) >= 70)
        for moment in summary.moments:
            primary_id = moment_primary.get(id(moment))
            display = safe_display_name(await resolve_display_name_from_message_id(
                database=self._database,
                guild_id=guild_id,
                channel_id=channel_id,
                message_id=primary_id,
                message_cache=message_cache,
            ))
            integrated = self._apply_author_placeholder(moment.text, display)
            if is_green and display and self._contains_vague_actor(integrated):
                integrated = re.sub(
                    r"\b(un membro|una persona|qualcuno|diverse persone|alcuni membri)\b",
                    display,
                    integrated,
                    count=1,
                    flags=re.IGNORECASE,
                )
            moment.text = self._sanitize_moment_text(integrated)

        for dynamic in summary.dynamics:
            names: list[str] = []
            seen: set[str] = set()
            candidate_ids = [dynamic_primary.get(id(dynamic)), *dynamic.message_ids]
            for candidate in candidate_ids:
                display = safe_display_name(await resolve_display_name_from_message_id(
                    database=self._database,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    message_id=candidate,
                    message_cache=message_cache,
                ))
                if display and display not in seen:
                    names.append(display)
                    seen.add(display)
                if len(names) >= 3:
                    break
            dynamic_names[id(dynamic)] = names
            primary_display = names[0] if names else None
            dynamic_text = self._apply_author_placeholder(dynamic.text, primary_display)
            if "{AUTHOR}" in dynamic_text:
                dynamic_text = self._cleanup_placeholder_artifacts(dynamic_text.replace("{AUTHOR}", ""), had_author_placeholder=True, has_display_name=False)
            dynamic.text = self._sanitize_moment_text(dynamic_text)

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
                    author_display = safe_display_name(await resolve_display_name_from_message_id(
                        database=self._database,
                        guild_id=guild_id,
                        channel_id=channel_id,
                        message_id=primary_id,
                        message_cache=message_cache,
                    ))

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

