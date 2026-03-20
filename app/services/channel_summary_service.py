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

from app.services.footer import attach_footer_meta

from app.plugins.commands_modular.time_windows import TimeWindowResult, infer_rolling_window_request, resolve_ieri_window, resolve_oggi_window
from app.renderers.channel_summary import MessageMeta, QuoteRenderItem, build_channel_summary_embeds, build_channel_summary_insufficient_data_embed, format_window_header
from app.services.barcello_service import BarcelloResult, BarcelloService
from app.services.aura import aura_reason_to_human
from app.renderers.aura_renderer import ChannelAuraEmbedData, ChannelAuraMissionTrend, ChannelAuraTopUserItem, build_channel_aura_advice, build_channel_aura_embed
from app.services.database import DatabaseService
from app.services.content_summary_service import SummaryResult, SummaryService
from app.shared.discord.embed_limits import _estimate_embed_size, estimate_embeds_total_size
from app.services.message_name_service import resolve_display_name_from_message_id, resolve_primary_message_id, safe_display_name

logger = logging.getLogger(__name__)
ROME_TZ = ZoneInfo("Europe/Rome")

MIN_CHANNEL_SUMMARY_MESSAGES = 8
MIN_CHANNEL_SUMMARY_DISTINCT_USERS = 2
MIN_CHANNEL_SUMMARY_USABLE_CONTENT_MESSAGES = 5


def _summary_footer_inputs(ai_status: dict[str, Any]) -> tuple[list[str], bool]:
    used_ai_output = bool(ai_status.get("used_ai_output"))
    used_display_model = str(ai_status.get("used_display_model") or "").strip()
    contributors = [used_display_model] if used_ai_output and used_display_model else []
    return contributors, (not used_ai_output)


async def compute_moment_barcello_map(
    *,
    barcello_service: BarcelloService,
    guild_id: str,
    channel_id: str,
    summary: SummaryResult,
    moment_primary: dict[int, str | None],
    message_index: dict[str, MessageMeta],
    fallback: BarcelloResult,
    limit: int = 8,
) -> dict[int, BarcelloResult]:
    snapshots: dict[int, BarcelloResult] = {}
    half_window = timedelta(minutes=30)
    for moment in summary.moments[:limit]:
        point_ts = moment.ts
        primary_id = moment_primary.get(id(moment))
        if primary_id and primary_id in message_index:
            point_ts = message_index[primary_id].ts or point_ts
        if not point_ts:
            snapshots[id(moment)] = fallback
            continue
        try:
            point_dt = datetime.fromisoformat(str(point_ts).replace("Z", "+00:00"))
            if point_dt.tzinfo is None:
                point_dt = point_dt.replace(tzinfo=timezone.utc)
            start_dt = point_dt - half_window
            end_dt = point_dt + half_window
            snapshots[id(moment)] = await barcello_service.compute_channel_range(
                guild_id=guild_id,
                channel_id=channel_id,
                start_ts=start_dt.astimezone(timezone.utc).isoformat(),
                end_ts=end_dt.astimezone(timezone.utc).isoformat(),
            )
        except Exception:
            logger.exception("channel_summary moment barcello failed guild=%s channel=%s", guild_id, channel_id)
            snapshots[id(moment)] = fallback
    return snapshots


class ChannelSummaryService:
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
        self._loop_started_logged = False

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        await self._bot.wait_until_ready()
        if not self._loop_started_logged:
            logger.info("channel_summary loop started interval=30s")
            self._loop_started_logged = True
        while True:
            try:
                await self.run_once()
            except Exception:
                logger.exception("channel_summary tick failed")
            await asyncio.sleep(30)

    async def run_once(self) -> None:
        await self._run_scheduled_channel_summaries()

    async def _run_scheduled_channel_summaries(self) -> None:
        now_utc = datetime.now(timezone.utc)
        now_local = now_utc.astimezone(ROME_TZ)
        for guild in self._bot.guilds:
            rows = await self._database.list_due_channel_summary_schedules(str(guild.id), now_utc.isoformat())
            for row in rows:
                schedule = dict(row)
                channel_id = str(schedule.get("channel_id") or "")
                schedule_id = int(schedule.get("id") or 0)
                try:
                    enabled = await self._database.get_channel_summary_auto_enabled(str(guild.id), channel_id)
                    if not enabled:
                        logger.debug("channel_summary skip schedule=%s channel=%s reason=auto_off", schedule_id, channel_id)
                        continue
                    window = self._resolve_window_from_schedule(schedule, now_local=now_local)
                    sent = await self.generate_and_send_for_channel(str(guild.id), channel_id, manual=False, window=window)
                    if sent:
                        await self._database.mark_channel_summary_schedule_sent(schedule_id)
                        logger.info("channel_summary sent ok guild=%s channel=%s schedule_id=%s", guild.id, channel_id, schedule_id)
                except Exception:
                    logger.exception("channel_summary scheduled run failed guild=%s channel=%s schedule_id=%s", guild.id, channel_id, schedule_id)

    def _resolve_window_from_schedule(self, row: dict[str, Any], *, now_local: datetime) -> TimeWindowResult:
        schedule_type = str(row.get("type") or "oggi").lower()
        if schedule_type == "ieri":
            return resolve_ieri_window()
        if schedule_type == "ultimi":
            start_raw = str(row.get("start_ts") or "")
            end_raw = str(row.get("end_ts") or "")
            try:
                start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00")).astimezone(ROME_TZ)
                end_dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00")).astimezone(ROME_TZ)
                delta = max(timedelta(minutes=1), end_dt - start_dt)
            except Exception:
                delta = timedelta(hours=1)
            start_dt = now_local - delta
            requested_qty, requested_unit = infer_rolling_window_request(start_dt, end_dt)
            return TimeWindowResult(
                start_dt=start_dt,
                end_dt=now_local,
                period_label="ultimi",
                label_periodo="ultimi",
                requested_quantity=requested_qty,
                requested_unit=requested_unit,
            )
        if schedule_type == "range":
            start_raw = str(row.get("start_ts") or "")
            end_raw = str(row.get("end_ts") or "")
            start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00")).astimezone(ROME_TZ)
            end_dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00")).astimezone(ROME_TZ)
            return TimeWindowResult(start_dt=start_dt, end_dt=end_dt, period_label="range", label_periodo="range")
        return resolve_oggi_window()

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

    def _bold_display_name(self, text: str, display_name: str | None) -> str:
        clean_name = str(display_name or "").strip()
        raw_text = str(text or "")
        if not clean_name or not raw_text:
            return raw_text
        if f"**{clean_name}**" in raw_text:
            return raw_text

        chunks = re.split(r"(\*\*[^*]+\*\*)", raw_text)
        for idx, chunk in enumerate(chunks):
            if idx % 2 == 1:
                continue
            chunks[idx] = chunk.replace(clean_name, f"**{clean_name}**")
        return "".join(chunks)

    def _is_single_day_style(self, *, period_label: str | None, start_local: datetime, end_local: datetime) -> bool:
        normalized = str(period_label or "").strip().lower()
        if normalized in {"oggi", "ieri"}:
            return True
        if normalized in {"ultimi", "range"}:
            return start_local.date() == end_local.date()
        return start_local.date() == end_local.date()

    def _apply_author_placeholder(self, text: str, display_name: str | None) -> str:
        clean = str(text or "").strip()
        if not clean:
            return clean
        display = safe_display_name(display_name)
        had_placeholder = "{AUTHOR}" in clean
        if had_placeholder:
            clean = clean.replace("{AUTHOR}", f"**{display}**" if display else "")
        clean = self._cleanup_placeholder_artifacts(
            clean,
            had_author_placeholder=had_placeholder,
            has_display_name=bool(display),
        )
        if not clean:
            return "Qualcuno ha partecipato alla conversazione in modo costruttivo."
        return clean

    def _sanitize_moment_text(
        self,
        text: str,
        *,
        multi_day: bool = False,
        moment_ts: str | None = None,
        is_last: bool = False,
        ordinal: int = 0,
    ) -> str:
        clean = str(text or "").strip()
        if not clean:
            return clean
        clean = re.sub(r"^(?:alba|mattina|pomeriggio|sera)\s*,\s+", "", clean, flags=re.IGNORECASE)
        if multi_day:
            # Multi-day windows should be neutral event notes, not single-day time-of-day storytelling.
            clean = re.sub(
                r"^(?:di prima mattina|la mattina|durante la tarda mattinata|verso mezzogiorno|in piena giornata|nel pomeriggio|più tardi|in serata|sul finire della giornata|in chiusura|la giornata si chiude con|all'avvio della giornata)\s*,?\s+",
                "",
                clean,
                flags=re.IGNORECASE,
            )
        clean = re.sub(r"^[^\wÀ-ÖØ-öø-ÿA-Za-z0-9#]{1,4}\s+", "", clean)
        clean = " ".join(clean.split())
        if multi_day:
            return clean
        clean = re.sub(r"^((?:di prima mattina|all'avvio della giornata|la mattina|durante la tarda mattinata|verso mezzogiorno|in piena giornata|nel pomeriggio|più tardi|in serata|sul finire della giornata|in chiusura|la giornata si chiude con)\s*,?)\s*durante la discussione,\s+", r"\1 ", clean, flags=re.IGNORECASE)
        if self._has_day_narrative_hook(clean):
            return clean
        hook = self._single_day_narrative_hook(moment_ts=moment_ts, is_last=is_last, ordinal=ordinal)
        if re.match(r"^[a-zà-öø-ÿ]", clean):
            clean = clean[0].upper() + clean[1:]
        return f"{hook} {clean}"

    def _has_day_narrative_hook(self, text: str) -> bool:
        return bool(re.match(
            r"^(?:la giornata inizia|di prima mattina|all'avvio della giornata|la mattina|durante la tarda mattinata|verso mezzogiorno|in piena giornata|nel pomeriggio|più tardi|in serata|sul finire della giornata|in chiusura|la giornata si chiude con)\b",
            str(text or "").strip(),
            flags=re.IGNORECASE,
        ))

    def _single_day_narrative_hook(self, *, moment_ts: str | None, is_last: bool, ordinal: int) -> str:
        if is_last:
            return "In chiusura,"
        hour: int | None = None
        if moment_ts:
            try:
                dt = datetime.fromisoformat(str(moment_ts).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                hour = dt.astimezone(ROME_TZ).hour
            except Exception:
                hour = None
        if hour is None:
            fallback_hooks = ["La giornata inizia con", "Più tardi,", "Nel pomeriggio,", "In serata,"]
            return fallback_hooks[ordinal % len(fallback_hooks)]
        if 6 <= hour <= 10:
            hooks = ["Di prima mattina,", "All'avvio della giornata,", "La mattina,"]
        elif 11 <= hour <= 14:
            hooks = ["Durante la tarda mattinata,", "Verso mezzogiorno,", "In piena giornata,"]
        elif 15 <= hour <= 18:
            hooks = ["Nel pomeriggio,", "Più tardi,"]
        elif 19 <= hour <= 22:
            hooks = ["In serata,", "Sul finire della giornata,"]
        else:
            hooks = ["La giornata inizia con", "Più tardi,"]
        return hooks[ordinal % len(hooks)]

    def _contains_vague_actor(self, text: str) -> bool:
        return bool(re.search(r"\b(un membro|una persona|qualcuno|diverse persone|alcuni membri)\b", str(text or ""), flags=re.IGNORECASE))

    def _ensure_past_tense_vibe(self, text: str, bar: BarcelloResult, *, period_label: str) -> str:
        raw = " ".join(str(text or "").split())
        if raw:
            raw = raw.replace("\n", " ").strip()
            raw = (raw[:139] + "…") if len(raw) > 140 else raw
            if re.search(r"\b(è stato|è rimasto|ha tenuto|si è mantenuto|si è stabilizzato|ha chiuso)\b", raw, flags=re.IGNORECASE):
                banned = ("trend", "stabile", "miglioramento", "peggioramento", "delta", "Δ", "rispetto a ieri")
                lower_raw = raw.lower()
                if not any(tok in lower_raw for tok in banned):
                    return raw
        lead = "Nel periodo selezionato"
        if period_label == "oggi":
            lead = "Nella giornata di oggi"
        elif period_label == "ieri":
            lead = "Nella giornata di ieri"
        return f"{lead} il barcello è rimasto {bar.color} ({bar.score}/100), con un clima complessivamente disteso."

    async def _build_who_interacted_candidates(self, *, rows: list[Any], guild_id: str) -> tuple[list[dict[str, Any]], list[str]]:
        stats: dict[str, dict[str, Any]] = {}
        for row in rows:
            row_map = dict(row) if not isinstance(row, dict) else row
            author_id = str(row_map.get("author_id") or "").strip()
            if not author_id:
                continue
            item = stats.setdefault(author_id, {"msg_count": 0, "mentions_made": 0, "replies": 0, "hour_slots": set()})
            item["msg_count"] += 1
            if str(row_map.get("reply_to_message_id") or "").strip():
                item["replies"] += 1
            try:
                mentions = json.loads(str(row_map.get("mentions_json") or "[]"))
                if isinstance(mentions, list):
                    item["mentions_made"] += len([m for m in mentions if str(m).strip()])
            except Exception:
                pass
            ts = str(row_map.get("ts") or "")
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(ROME_TZ)
                item["hour_slots"].add(dt.hour // 3)
            except Exception:
                pass

        scored: list[tuple[str, dict[str, Any]]] = []
        for author_id, st in stats.items():
            st["interaction_score"] = int(st["msg_count"]) + 2 * int(st["mentions_made"]) + int(st["replies"]) + len(st["hour_slots"])
            st["weight"] = int(st["msg_count"]) + int(st["interaction_score"])
            scored.append((author_id, st))

        top_writers = sorted(scored, key=lambda x: x[1]["msg_count"], reverse=True)[:5]
        top_interactors = sorted(scored, key=lambda x: x[1]["interaction_score"], reverse=True)[:5]
        ordered_ids: list[str] = []
        for author_id, _ in [*top_writers, *top_interactors]:
            if author_id not in ordered_ids:
                ordered_ids.append(author_id)
        ordered_ids = sorted(ordered_ids, key=lambda aid: stats[aid]["weight"], reverse=True)[:8]

        candidates: list[dict[str, Any]] = []
        fallback_lines: list[str] = []
        for author_id in ordered_ids:
            st = stats[author_id]
            name = safe_display_name(await self._database.fetch_user_display_name(guild_id=guild_id, user_id=author_id)) or "Qualcuno"
            notes: list[str] = []
            if st["msg_count"] >= 8:
                notes.append("presenza costante in chat")
            if st["mentions_made"] >= 3:
                notes.append("ha coinvolto altre persone")
            if len(st["hour_slots"]) >= 3:
                notes.append("ha coperto più momenti della giornata")
            if not notes:
                notes.append("ha partecipato con continuità")
            candidates.append({
                "name": name,
                "msg_count": int(st["msg_count"]),
                "interaction_score": int(st["interaction_score"]),
                "notes": notes,
            })
            fallback_lines.append(f"{name} ha tenuto viva la chat: {', '.join(notes[:2])}.")

        return candidates, fallback_lines

    def _channel_summary_data_is_sufficient(self, *, rows: list[Any], messages: list[dict[str, Any]]) -> tuple[bool, dict[str, int]]:
        total_messages = len(rows)
        distinct_users = len({str((dict(row) if not isinstance(row, dict) else row).get("author_id") or "").strip() for row in rows if str((dict(row) if not isinstance(row, dict) else row).get("author_id") or "").strip()})
        usable_content_messages = len(messages)
        enough = (
            total_messages >= MIN_CHANNEL_SUMMARY_MESSAGES
            and distinct_users >= MIN_CHANNEL_SUMMARY_DISTINCT_USERS
            and usable_content_messages >= MIN_CHANNEL_SUMMARY_USABLE_CONTENT_MESSAGES
        )
        return enough, {
            "messages": total_messages,
            "users": distinct_users,
            "usable_messages": usable_content_messages,
        }

    async def generate_and_send_for_channel(self, guild_id: str, channel_id: str, *, manual: bool = False, window: TimeWindowResult | None = None) -> bool:
        channel = self._bot.get_channel(int(channel_id))
        if not isinstance(channel, discord.abc.Messageable):
            logger.warning("channel_summary channel not accessible guild=%s channel=%s", guild_id, channel_id)
            return False

        if window is None:
            window = resolve_oggi_window()
        now_local = datetime.now(ROME_TZ)
        start_local = window.start_dt.astimezone(ROME_TZ)
        end_local = window.end_dt.astimezone(ROME_TZ)
        start_dt = start_local.astimezone(timezone.utc)
        end_dt = end_local.astimezone(timezone.utc)
        logger.debug("channel_summary period guild=%s channel=%s start_utc=%s end_utc=%s", guild_id, channel_id, start_dt.isoformat(), end_dt.isoformat())
        rows = await self._database.fetch_messages_in_range(channel_id=channel_id, start_ts=start_dt.isoformat(), end_ts=end_dt.isoformat(), limit=1200)
        who_candidates, who_fallback_lines = await self._build_who_interacted_candidates(rows=rows, guild_id=guild_id)
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

        window_header = format_window_header(
            period_label=window.period_label,
            start_dt=start_local,
            end_dt=end_local,
            requested_quantity=window.requested_quantity,
            requested_unit=window.requested_unit,
        )
        data_is_sufficient, data_counts = self._channel_summary_data_is_sufficient(rows=rows, messages=messages)
        if not data_is_sufficient:
            logger.info(
                "channel_summary skipped_ai_insufficient_data guild=%s channel=%s messages=%s users=%s usable_messages=%s",
                guild_id,
                channel_id,
                data_counts["messages"],
                data_counts["users"],
                data_counts["usable_messages"],
            )
            channel_name = getattr(channel, "name", None) or channel_id
            embed = build_channel_summary_insufficient_data_embed(channel_name=str(channel_name), window_header=window_header)
            attach_footer_meta(embed, service_name="channel_summary", used_local_processing=True)
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                logger.exception("channel_summary send failed guild=%s channel=%s", guild_id, channel_id)
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
            logger.info("channel_summary sent_insufficient_data guild=%s channel=%s manual=%s", guild_id, channel_id, manual)
            return True

        bar = await self._barcello.compute_channel_range(
            guild_id=guild_id,
            channel_id=channel_id,
            start_ts=start_dt.isoformat(),
            end_ts=end_dt.isoformat(),
        )
        previous_bar = await self._compute_previous_equivalent_barcello(
            guild_id=guild_id,
            channel_id=channel_id,
            current_start_local=start_local,
            current_end_local=end_local,
        )
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
            summary_mode="channel_summary",
            summary_context={
                "period_label": window.period_label,
                "score": bar.score,
                "color": bar.color,
                "barcello_verde": (bar.color == "verde" and int(bar.score) >= 70),
                "nonce": f"{now_local.isoformat()}-{uuid4().hex[:10]}",
                "who_interacted_candidates": who_candidates,
                "trend_reason": "",
                "signals": {
                    "negative_hits": int((bar.metrics or {}).get("negativity_hits") or 0),
                    "positive_hits": int((bar.metrics or {}).get("positive_hits") or 0),
                },
            },
        )

        trend_value = self._build_trend_vs_previous_equivalent(
            bar_current=bar,
            bar_previous=previous_bar,
            current_start_local=start_local,
            current_end_local=end_local,
            period_label=window.period_label,
        )
        barcello_line = self._ensure_past_tense_vibe(getattr(summary, "vibe_line", None), bar, period_label=window.period_label)
        advice = [str(x).strip()[:160] for x in (getattr(summary, "advice", []) or []) if str(x).strip()][:5]
        proverbio = str(getattr(summary, "proverbio", "") or "").strip()
        if not advice or not proverbio:
            fallback_advice, fallback_proverbio = self._fallback_advice_proverbio(bar.color)
            if not advice:
                advice = fallback_advice
            if not proverbio:
                proverbio = fallback_proverbio
        who_lines = [str(line).strip() for line in (getattr(summary, "who_interacted_today", []) or []) if str(line).strip()][:8]
        if not who_lines:
            who_lines = who_fallback_lines[:8]
        is_single_day_style = self._is_single_day_style(
            period_label=window.period_label,
            start_local=start_local,
            end_local=end_local,
        )
        multi_day_style = not is_single_day_style

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
        for idx, moment in enumerate(summary.moments):
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
            moment.text = self._bold_display_name(self._sanitize_moment_text(
                integrated,
                multi_day=multi_day_style,
                moment_ts=moment.ts,
                is_last=(idx == len(summary.moments) - 1),
                ordinal=idx,
            ), display)

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
            dynamic.text = self._bold_display_name(self._sanitize_moment_text(dynamic_text, multi_day=multi_day_style, moment_ts=dynamic.ts), primary_display)

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

        moment_barcello = await self._compute_moment_barcello_map(
            guild_id=guild_id,
            channel_id=channel_id,
            summary=summary,
            moment_primary=moment_primary,
            message_index=message_index,
            fallback=bar,
        )

        channel_name = getattr(channel, "name", None) or channel_id
        known_display_names = sorted({name for names in dynamic_names.values() for name in names if str(name).strip()}, key=len, reverse=True)

        aura_embed = await self._build_channel_aura_embed(
            guild_id=guild_id,
            channel_id=channel_id,
            start_local=start_local,
            end_local=end_local,
        )

        embeds = build_channel_summary_embeds(
            guild_id=int(guild_id),
            channel_id=int(channel_id),
            channel_name=str(channel_name),
            barcello_status=bar,
            barcello_line=barcello_line,
            summary_result=summary,
            message_index=message_index,
            advice_bullets=advice,
            proverbio=proverbio,
            window_header=window_header,
            moment_primary=moment_primary,
            dynamic_primary=dynamic_primary,
            dynamic_names=dynamic_names,
            quote_render_items=quote_render_items,
            moment_barcello=moment_barcello,
            trend_value=trend_value,
            who_interacted_lines=who_lines,
            known_display_names=known_display_names,
            multi_day=multi_day_style,
            aura_embed=aura_embed,
        )

        footer_contributors, footer_local = _summary_footer_inputs(summary.ai_status)

        attach_footer_meta(
            embeds[0],
            service_name="channel_summary",
            contributors=footer_contributors,
            used_local_processing=footer_local,
        )
        if len(embeds) >= 2:
            embeds[1].title = "🗒️ DETTAGLI CANALE (Pag 1/2)"
            attach_footer_meta(
                embeds[1],
                service_name="channel_summary",
                contributors=footer_contributors,
                used_local_processing=footer_local,
            )
        if len(embeds) >= 3:
            aura_chars_final = _estimate_embed_size(embeds[2])
            logger.debug("aura_embed_chars_final_with_footer=%s guild=%s channel=%s", aura_chars_final, guild_id, channel_id)
            if aura_chars_final > 5800:
                logger.warning("channel_summary aura_embed_over_budget chars=%s guild=%s channel=%s", aura_chars_final, guild_id, channel_id)
                embeds = embeds[:2]
        try:
            if len(embeds) >= 3:
                first_batch = embeds[:2]
                second_batch = [embeds[2]]
                logger.debug(
                    "channel_summary send_batch1 embeds=%s total_chars=%s guild=%s channel=%s",
                    len(first_batch),
                    estimate_embeds_total_size(first_batch),
                    guild_id,
                    channel_id,
                )
                await channel.send(embeds=first_batch)
                logger.debug(
                    "channel_summary send_batch2 embeds=%s total_chars=%s guild=%s channel=%s",
                    len(second_batch),
                    estimate_embeds_total_size(second_batch),
                    guild_id,
                    channel_id,
                )
                await channel.send(embeds=second_batch)
            else:
                logger.debug(
                    "channel_summary send_batch1 embeds=%s total_chars=%s guild=%s channel=%s",
                    len(embeds),
                    estimate_embeds_total_size(embeds),
                    guild_id,
                    channel_id,
                )
                await channel.send(embeds=embeds)
        except discord.HTTPException:
            logger.exception("channel_summary send failed guild=%s channel=%s", guild_id, channel_id)
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
        logger.info("channel_summary sent guild=%s channel=%s manual=%s", guild_id, channel_id, manual)
        return True


    def _previous_equivalent_window(self, *, current_start_local: datetime, current_end_local: datetime) -> tuple[datetime, datetime]:
        duration = max(timedelta(minutes=1), current_end_local - current_start_local)
        previous_start_local = current_start_local - duration
        previous_end_local = current_start_local
        return previous_start_local, previous_end_local


    def _rank_trend(self, prev_rank: int | None, current_rank: int) -> tuple[str, str]:
        if prev_rank is None:
            return "🆕", "nuovo ingresso nel ranking"
        if prev_rank > current_rank:
            return "⬆️", "sale in classifica"
        if prev_rank < current_rank:
            return "⬇️", "perde posizioni"
        return "↔️", "stabile nel ranking"

    def _aura_trend(self, current: int, previous: int) -> tuple[str, str]:
        if current > previous:
            return "⬆️", "in crescita rispetto al periodo precedente"
        if current < previous:
            return "⬇️", "in calo rispetto al periodo precedente"
        return "↔️", "stabile rispetto al periodo precedente"

    async def generate_channel_aura_embed(
        self,
        *,
        guild_id: str,
        channel_id: str,
        start_local: datetime,
        end_local: datetime,
        title: str = "🗒️ DETTAGLI PUNTI AURA",
    ) -> discord.Embed | None:
        embed = await self._build_channel_aura_embed(
            guild_id=guild_id,
            channel_id=channel_id,
            start_local=start_local,
            end_local=end_local,
        )
        if embed is not None:
            embed.title = title
        return embed

    async def _build_channel_aura_embed(
        self,
        *,
        guild_id: str,
        channel_id: str,
        start_local: datetime,
        end_local: datetime,
    ) -> discord.Embed | None:
        start_ts = start_local.astimezone(timezone.utc).isoformat()
        end_ts = end_local.astimezone(timezone.utc).isoformat()
        prev_start_local, prev_end_local = self._previous_equivalent_window(current_start_local=start_local, current_end_local=end_local)
        prev_start_ts = prev_start_local.astimezone(timezone.utc).isoformat()
        prev_end_ts = prev_end_local.astimezone(timezone.utc).isoformat()

        current = await self._database.fetch_aura_channel_ledger_report(guild_id, channel_id, start_ts, end_ts)
        total_users = int(current["totals"].get("users_count") or 0)
        total_positive = int(current["totals"].get("positive") or 0)
        total_negative = int(current["totals"].get("negative") or 0)
        if total_users <= 0 and total_positive <= 0 and total_negative == 0:
            return None

        top_now = await self._database.fetch_aura_channel_top_users(guild_id, channel_id, start_ts, end_ts, limit=10)
        top_prev = await self._database.fetch_aura_channel_top_users(guild_id, channel_id, prev_start_ts, prev_end_ts, limit=50)
        prev_ranks = {str(r["user_id"]): idx for idx, r in enumerate(top_prev, start=1)}

        top_items: list[ChannelAuraTopUserItem] = []
        for idx, row in enumerate(top_now, start=1):
            uid = str(row["user_id"])
            score = max(0, int(row["total"] or 0))
            prev_rank = prev_ranks.get(uid)
            trend_emoji, comment = self._rank_trend(prev_rank, idx)
            top_items.append(ChannelAuraTopUserItem(user_id=uid, score=score, trend_emoji=trend_emoji, trend_comment=comment, rank=idx))

        by_reason = list(current.get("by_reason", []))
        pos_reasons = [(f"{aura_reason_to_human(str(it['reason_code']))}", int(it["total"] or 0)) for it in by_reason if int(it["total"] or 0) > 0]
        neg_reasons = [(f"{aura_reason_to_human(str(it['reason_code']))}", int(it["total"] or 0)) for it in by_reason if int(it["total"] or 0) < 0]

        missions_now = await self._database.fetch_aura_channel_mission_stats(guild_id, channel_id, start_ts, end_ts)
        missions_prev = await self._database.fetch_aura_channel_mission_stats(guild_id, channel_id, prev_start_ts, prev_end_ts)
        now_completed_role1 = int(missions_now.get("completed_role1") or 0)
        now_completed_role2 = int(missions_now.get("completed_role2") or 0)
        prev_completed_role1 = int(missions_prev.get("completed_role1") or 0)
        prev_completed_role2 = int(missions_prev.get("completed_role2") or 0)
        mission_role1 = self._aura_trend(now_completed_role1, prev_completed_role1)
        mission_role2 = self._aura_trend(now_completed_role2, prev_completed_role2)

        top_positive_reason = str(pos_reasons[0][0]) if pos_reasons else None
        advice = build_channel_aura_advice(
            positive_points=total_positive,
            negative_points=total_negative,
            users_count=total_users,
            mission_completed=now_completed_role1 + now_completed_role2,
            top_positive_reason=top_positive_reason,
        )

        aura_embed = build_channel_aura_embed(
            title="🗒️ DETTAGLI PUNTI AURA",
            footer_text="Il sistema PUNTI AURA è in fase di sviluppo. I dati potrebbero non essere accurati.",
            data=ChannelAuraEmbedData(
                positive_points=total_positive,
                negative_points=total_negative,
                users_count=total_users,
                top_users=top_items,
                positive_reasons=pos_reasons,
                negative_reasons=neg_reasons,
                missions=ChannelAuraMissionTrend(
                    assigned_role1=int(missions_now.get("assigned_role1") or 0),
                    assigned_role2=int(missions_now.get("assigned_role2") or 0),
                    completed_role1=now_completed_role1,
                    completed_role2=now_completed_role2,
                    eligible_role1=int(missions_now.get("eligible_role1") or 0),
                    eligible_role2=int(missions_now.get("eligible_role2") or 0),
                    trend_role1=mission_role1,
                    trend_role2=mission_role2,
                ),
                advice_lines=advice,
            )
        )
        logger.debug("channel_summary aura_embed_chars=%s guild=%s channel=%s", _estimate_embed_size(aura_embed), guild_id, channel_id)
        return aura_embed

    async def _compute_previous_equivalent_barcello(
        self,
        *,
        guild_id: str,
        channel_id: str,
        current_start_local: datetime,
        current_end_local: datetime,
    ) -> BarcelloResult | None:
        # Compare against the immediately previous window with equivalent duration.
        previous_start_local, previous_end_local = self._previous_equivalent_window(current_start_local=current_start_local, current_end_local=current_end_local)
        try:
            return await self._barcello.compute_channel_range(
                guild_id=guild_id,
                channel_id=channel_id,
                start_ts=previous_start_local.astimezone(timezone.utc).isoformat(),
                end_ts=previous_end_local.astimezone(timezone.utc).isoformat(),
            )
        except Exception:
            logger.exception("channel_summary previous equivalent barcello failed guild=%s channel=%s", guild_id, channel_id)
            return None

    async def _compute_moment_barcello_map(
        self,
        *,
        guild_id: str,
        channel_id: str,
        summary: SummaryResult,
        moment_primary: dict[int, str | None],
        message_index: dict[str, MessageMeta],
        fallback: BarcelloResult,
    ) -> dict[int, BarcelloResult]:
        return await compute_moment_barcello_map(
            barcello_service=self._barcello,
            guild_id=guild_id,
            channel_id=channel_id,
            summary=summary,
            moment_primary=moment_primary,
            message_index=message_index,
            fallback=fallback,
        )

    def _build_trend_vs_previous_equivalent(
        self,
        *,
        bar_current: BarcelloResult,
        bar_previous: BarcelloResult | None,
        current_start_local: datetime,
        current_end_local: datetime,
        period_label: str | None = None,
    ) -> str:
        if bar_previous is None:
            return "Stabile (Δ +0): confronto con finestra equivalente precedente non disponibile."
        delta = int(bar_current.score) - int(bar_previous.score)
        if delta >= 4:
            direction = "In miglioramento"
        elif delta <= -4:
            direction = "In peggioramento"
        else:
            direction = "Stabile"

        prev_start = (current_start_local - (current_end_local - current_start_local)).strftime("%d/%m %H:%M")
        prev_end = current_start_local.strftime("%d/%m %H:%M")

        cur_neg = int((bar_current.metrics or {}).get("negativity_hits") or 0)
        prev_neg = int((bar_previous.metrics or {}).get("negativity_hits") or 0)
        cur_pos = int((bar_current.metrics or {}).get("positive_hits") or 0)
        prev_pos = int((bar_previous.metrics or {}).get("positive_hits") or 0)
        if cur_neg < prev_neg and cur_pos >= prev_pos:
            reason = "meno tensione e più supporto"
        elif cur_neg > prev_neg:
            reason = "più frizioni e callout"
        elif cur_pos > prev_pos:
            reason = "più messaggi costruttivi e supporto"
        else:
            reason = "clima simile, senza scossoni rilevanti"
        if period_label in {"oggi", "ieri"}:
            period_cmp = "rispetto al giorno precedente"
            if period_label == "oggi":
                period_cmp = "rispetto a ieri"
            return f"{direction} (Δ {delta:+d}): {reason} {period_cmp}."
        return f"{direction} (Δ {delta:+d}): {reason} rispetto a {prev_start} → {prev_end}."

    def _fallback_advice_proverbio(self, color: str) -> tuple[list[str], str]:
        fallback = {
            "verde": (["Voi mantenete il tono positivo e ringraziate chi aiuta.", "Voi confermate i prossimi passi in modo chiaro.", "Voi valorizzate i contributi costruttivi del canale."], "Chi semina bene, raccoglie meglio."),
            "giallo": (["Voi evitate messaggi impulsivi e usate frasi brevi.", "Voi fate una domanda chiarificatrice prima di rispondere.", "Voi ricapitolate i punti in disaccordo senza accuse."], "Meglio una parola in meno che una di troppo."),
            "rosso": (["Voi sospendete i thread accesi per qualche minuto.", "Voi passate da accuse a fatti verificabili.", "Voi coinvolgete un moderatore se il tono non cala."], "Quando il ferro è caldo, la calma vale oro."),
        }
        return fallback.get(color, (["Voi vi fermate, respirate e chiarite l'obiettivo comune.", "Voi riducete sarcasmo e giudizi personali.", "Voi ripartite da regole semplici di convivenza."], "Dopo la tempesta, torna il sereno."))
