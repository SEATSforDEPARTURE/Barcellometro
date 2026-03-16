from __future__ import annotations

import asyncio
import io
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from dataclasses import dataclass

from typing import Any
from zoneinfo import ZoneInfo

import discord

from app.renderers.activity_daily_report_renderer import build_daily_activity_details_txt, build_daily_activity_embeds
from app.plugins.commands_modular.time_windows import infer_rolling_window_request
from app.services.activity_insights import ActivityInsightsService
from app.services.database import DatabaseService
from app.services.daily_activity_sorting import sort_channels_like_discord, sort_inactive_entries

logger = logging.getLogger(__name__)
ROME_TZ = ZoneInfo("Europe/Rome")

@dataclass
class ReportWindow:
    start_dt: datetime
    end_dt: datetime
    period_label: str
    requested_quantity: int | None = None
    requested_unit: str | None = None


def build_combined_activity_inactive_txt(
    *,
    activity_txt_payload: str | None,
    inactive_txt_payload: str | None,
    filename_prefix: str = "report_attivita_e_inattivi",
    now: datetime | None = None,
) -> tuple[str, str, discord.File]:
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M")
    filename = f"{filename_prefix}_{timestamp}.txt"

    sections: list[str] = []
    if activity_txt_payload:
        sections.append(
            "\n".join(
                [
                    "==================================================",
                    "SEZIONE 1 — REPORT ATTIVITÀ DETTAGLIATO",
                    "==================================================",
                    "",
                    activity_txt_payload.strip(),
                ]
            )
        )
    if inactive_txt_payload:
        sections.append(
            "\n".join(
                [
                    "==================================================",
                    "SEZIONE 2 — INATTIVI SERVER-WIDE",
                    "==================================================",
                    "",
                    inactive_txt_payload.strip(),
                ]
            )
        )

    final_payload = "\n\n\n".join(sections).strip() if sections else "Nessun dettaglio disponibile."
    txt_file = discord.File(io.BytesIO(final_payload.encode("utf-8")), filename=filename)
    return final_payload, filename, txt_file


class DailyReportPaginationView(discord.ui.View):
    def __init__(self, report_service: "DailyActivityReportService", *, current_index: int = 0, total_pages: int = 1) -> None:
        super().__init__(timeout=None)
        self._report_service = report_service
        self._current_index = current_index
        self._total_pages = max(1, int(total_pages))
        self._sync_button_states()

    def _sync_button_states(self) -> None:
        is_first = self._current_index <= 0
        is_last = self._current_index >= self._total_pages - 1
        self.start_button.disabled = is_first
        self.prev_button.disabled = is_first
        self.next_button.disabled = is_last

    async def _navigate(self, interaction: discord.Interaction, *, action: str) -> None:
        message = interaction.message
        if message is None:
            await interaction.response.send_message("⚠️ Messaggio non disponibile.", ephemeral=True)
            return
        record = await self._report_service.load_pagination_record(message_id=str(message.id))
        if record is None:
            await interaction.response.send_message("⚠️ Report non più disponibile per la navigazione.", ephemeral=True)
            return
        embeds_payload = record.get("embeds")
        if not isinstance(embeds_payload, list) or not embeds_payload:
            await interaction.response.send_message("⚠️ Pagine report non valide.", ephemeral=True)
            return

        current_index = int(record.get("current_index", 0))
        max_index = len(embeds_payload) - 1
        if action == "start":
            target_index = 0
        elif action == "prev":
            target_index = max(0, current_index - 1)
        else:
            target_index = min(max_index, current_index + 1)

        self._current_index = target_index
        self._total_pages = len(embeds_payload)
        self._sync_button_states()
        embed = discord.Embed.from_dict(embeds_payload[target_index])
        await self._report_service.persist_pagination_current_index(message_id=str(message.id), current_index=target_index)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⏮️ INIZIO", style=discord.ButtonStyle.secondary, custom_id="daily_report:nav:start")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        _ = button
        await self._navigate(interaction, action="start")

    @discord.ui.button(label="⬅️ INDIETRO", style=discord.ButtonStyle.secondary, custom_id="daily_report:nav:prev")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        _ = button
        await self._navigate(interaction, action="prev")

    @discord.ui.button(label="➡️ AVANTI", style=discord.ButtonStyle.primary, custom_id="daily_report:nav:next")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        _ = button
        await self._navigate(interaction, action="next")


class DailyActivityReportService:
    def __init__(
        self,
        database: DatabaseService,
        bot: discord.Client,
        activity_service: ActivityInsightsService,
        inactive_members_moderation: Any | None = None,
    ) -> None:
        self._database = database
        self._bot = bot
        self._activity = activity_service
        self._task: asyncio.Task[None] | None = None
        self._inactive_moderation = inactive_members_moderation
        self._persistent_view_registered = False

    def _ensure_persistent_view_registered(self) -> None:
        if self._persistent_view_registered:
            return
        self._bot.add_view(DailyReportPaginationView(self))
        self._persistent_view_registered = True

    def start(self) -> None:
        self._ensure_persistent_view_registered()
        if self._task is None:
            logger.info("daily activity report scheduler running in server_summary_schedule-only mode")
            self._task = asyncio.create_task(self._loop())

    async def persist_pagination_record(
        self,
        *,
        message_id: str,
        channel_id: str,
        guild_id: str,
        embeds: list[discord.Embed],
        metadata: dict[str, Any] | None = None,
        current_index: int = 0,
    ) -> None:
        embeds_payload = [embed.to_dict() for embed in embeds]
        await self._database.upsert_daily_report_pagination_state(
            message_id=message_id,
            channel_id=channel_id,
            guild_id=guild_id,
            report_type="activity_inactive",
            embeds_json=json.dumps(embeds_payload, ensure_ascii=False),
            metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
            current_index=current_index,
        )

    async def persist_pagination_current_index(self, *, message_id: str, current_index: int) -> None:
        await self._database.update_daily_report_pagination_current_index(message_id=message_id, current_index=current_index)

    async def load_pagination_record(self, *, message_id: str) -> dict[str, Any] | None:
        row = await self._database.get_daily_report_pagination_state(message_id=message_id)
        if not row:
            return None
        try:
            embeds = json.loads(str(row["embeds_json"] or "[]"))
        except json.JSONDecodeError:
            embeds = []
        try:
            metadata = json.loads(str(row["metadata_json"] or "{}"))
        except json.JSONDecodeError:
            metadata = {}
        return {
            "message_id": str(row["message_id"]),
            "embeds": embeds,
            "metadata": metadata,
            "current_index": int(row["current_index"] or 0),
        }

    @staticmethod
    def _extract_txt_payload(file: discord.File | None) -> str | None:
        if file is None:
            return None
        fp = getattr(file, "fp", None)
        if fp is None:
            return None
        try:
            if hasattr(fp, "seek"):
                fp.seek(0)
            data = fp.read()
            if isinstance(data, bytes):
                return data.decode("utf-8")
            if isinstance(data, str):
                return data
        except Exception:
            logger.debug("daily_activity_report: failed reading txt payload from discord.File", exc_info=True)
        return None

    async def _loop(self) -> None:
        await self._bot.wait_until_ready()
        while True:
            try:
                await self.run_once()
            except Exception:
                logger.exception("daily_activity_report tick failed")
            await asyncio.sleep(30)

    async def run_once(self) -> None:
        await self._run_server_summary_schedules_once()

    async def _run_server_summary_schedules_once(self) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        for guild in self._bot.guilds:
            guild_id = str(guild.id)
            enabled = await self._database.get_server_summary_auto_enabled(guild_id)
            if not enabled:
                continue
            target_channel_id = await self._database.get_server_summary_target_channel(guild_id)
            if not target_channel_id:
                continue
            rows = await self._database.list_due_server_summary_schedules(guild_id, now_iso)
            for row in rows:
                start_ts = str(row["start_ts"] or "")
                end_ts = str(row["end_ts"] or "")
                try:
                    start_dt = datetime.fromisoformat(start_ts.replace("Z", "+00:00")).astimezone(ROME_TZ)
                    end_dt = datetime.fromisoformat(end_ts.replace("Z", "+00:00")).astimezone(ROME_TZ)
                except Exception:
                    continue
                schedule_type = str(row["schedule_type"] or "oggi")
                requested_quantity = None
                requested_unit = None
                if schedule_type == "ultimi":
                    requested_quantity, requested_unit = infer_rolling_window_request(start_dt, end_dt)
                window = ReportWindow(
                    start_dt=start_dt,
                    end_dt=end_dt,
                    period_label=schedule_type,
                    requested_quantity=requested_quantity,
                    requested_unit=requested_unit,
                )
                await self._send_daily_report(guild_id=guild_id, mod_channel_id=target_channel_id, window=window)
                await self._database.mark_server_summary_schedule_sent(int(row["id"]))

    async def send_now(self, *, guild_id: str, mod_channel_id: str) -> None:
        logger.info("daily_activity_report: manual send guild=%s channel=%s", guild_id, mod_channel_id)
        await self._send_daily_report(guild_id=guild_id, mod_channel_id=mod_channel_id, window=None)

    async def send_window(self, *, guild_id: str, mod_channel_id: str, window: ReportWindow) -> None:
        logger.info("daily_activity_report: manual window send guild=%s channel=%s window=%s", guild_id, mod_channel_id, window.period_label)
        await self._send_daily_report(guild_id=guild_id, mod_channel_id=mod_channel_id, window=window)

    @staticmethod
    def _hour_stats_from_timestamps(ts_list: list[str]) -> tuple[int | None, int | None, int]:
        if not ts_list:
            return None, None, 0
        buckets = [0] * 24
        for ts in ts_list:
            try:
                hour = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(ROME_TZ).hour
                buckets[hour] += 1
            except Exception:
                continue
        total = sum(buckets)
        if total <= 0:
            return None, None, 0
        peak_hour = max(range(24), key=lambda h: (buckets[h], -h))
        silence_hour = min(range(24), key=lambda h: (buckets[h], h))
        continuity = sum(1 for v in buckets if v > 0)
        return peak_hour, silence_hour, continuity

    @staticmethod
    def _human_relative(ts_iso: str | None, ref_iso: str) -> str:
        if not ts_iso:
            return "—"
        try:
            ts = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
            ref = datetime.fromisoformat(ref_iso.replace("Z", "+00:00"))
            minutes = max(0, int((ref - ts).total_seconds() // 60))
            if minutes < 60:
                return f"{minutes}m fa"
            hours = minutes // 60
            if hours < 24:
                return f"{hours}h fa"
            return f"{hours // 24}g fa"
        except Exception:
            return "—"

    async def _count_non_bot_members(self, guild: discord.Guild) -> int | None:
        if guild.members:
            return sum(1 for m in guild.members if not m.bot)
        logger.warning("daily_activity_report: guild members cache not populated for guild=%s", guild.id)
        return None

    async def _count_members_with_access(self, guild: discord.Guild, channel: discord.abc.GuildChannel) -> int | None:
        if not guild.members:
            return None
        non_bot_members = [m for m in guild.members if not m.bot]
        try:
            everyone_can_view = channel.permissions_for(guild.default_role).view_channel
        except Exception:
            everyone_can_view = False
        if everyone_can_view:
            return len(non_bot_members)
        total = 0
        for member in non_bot_members:
            try:
                if channel.permissions_for(member).view_channel:
                    total += 1
            except Exception:
                continue
        return total

    async def _send_daily_report(self, *, guild_id: str, mod_channel_id: str, window: ReportWindow | None) -> None:
        if not mod_channel_id:
            return
        guild = self._bot.get_guild(int(guild_id))
        channel = self._bot.get_channel(int(mod_channel_id))
        if guild is None or not isinstance(channel, discord.abc.Messageable):
            return

        now_local = datetime.now(ROME_TZ)
        if window is None:
            start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            end_local = now_local
            period_label = "oggi"
        else:
            start_local = window.start_dt.astimezone(ROME_TZ)
            end_local = window.end_dt.astimezone(ROME_TZ)
            period_label = window.period_label
            requested_quantity = window.requested_quantity
            requested_unit = window.requested_unit
        if window is None:
            requested_quantity = None
            requested_unit = None
        start_ts = start_local.astimezone(timezone.utc).isoformat()
        end_ts = end_local.astimezone(timezone.utc).isoformat()
        lookback_start = (datetime.fromisoformat(end_ts) - timedelta(days=90)).isoformat()

        total_non_bot_members = await self._count_non_bot_members(guild)
        non_bot_ids = {m.id for m in guild.members if not m.bot} if guild.members else set()

        channel_ids = await self._database.list_enabled_activity_channels(guild_id)
        resolved_channels: list[discord.abc.GuildChannel] = []
        for channel_id in channel_ids:
            try:
                dc = guild.get_channel(int(channel_id))
            except Exception:
                dc = None
            if dc is None:
                logger.warning("daily_activity_report: skipping missing/inaccessible channel guild=%s channel=%s", guild_id, channel_id)
                continue
            if isinstance(dc, discord.Thread):
                logger.warning("daily_activity_report: skipping thread channel guild=%s channel=%s", guild_id, channel_id)
                continue
            resolved_channels.append(dc)
        sorted_channels = sort_channels_like_discord(resolved_channels)

        payloads: list[dict[str, Any]] = []
        server_active_non_bot: set[int] = set()
        server_hour_buckets = [0] * 24

        global_user_totals: dict[int, int] = defaultdict(int)
        global_user_last: dict[int, tuple[str, str]] = {}
        global_user_peak: dict[int, tuple[int, str, str]] = {}
        global_user_best_channel: dict[int, tuple[int, str]] = {}

        historical_counts_by_channel: dict[str, dict[int, int]] = {}
        historical_last_by_channel: dict[str, dict[int, tuple[str, str | None]]] = {}

        for dc in sorted_channels:
            channel_id = str(dc.id)
            channel_name = f"#{dc.name}"

            details = await self._activity.compute_activity_for_channel(guild_id, channel_id, start_ts, end_ts)
            ts_list = await self._database.fetch_message_timestamps_in_range_single_channel(guild_id, channel_id, start_ts, end_ts)
            peak_hour, silence_hour, continuity = self._hour_stats_from_timestamps(ts_list)

            for ts in ts_list:
                try:
                    hour = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(ROME_TZ).hour
                    server_hour_buckets[hour] += 1
                except Exception:
                    continue

            distinct_authors = await self._database.fetch_distinct_authors_in_range_channel(guild_id, channel_id, start_ts, end_ts)
            active_non_bot_ids = {uid for uid in distinct_authors if not non_bot_ids or uid in non_bot_ids}
            server_active_non_bot.update(active_non_bot_ids)

            member_access_count = await self._count_members_with_access(guild, dc)
            per_user_counts = await self._database.fetch_user_counts_in_range_channel(guild_id, channel_id, start_ts, end_ts)
            per_user_last = await self._database.fetch_user_last_message_in_range_channel(guild_id, channel_id, start_ts, end_ts)
            user_rows = await self._database.fetch_user_timestamps_in_range_channel(guild_id, channel_id, start_ts, end_ts)

            per_user_hour: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
            for uid, ts, _ in user_rows:
                if non_bot_ids and uid not in non_bot_ids:
                    continue
                try:
                    hour_key = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(ROME_TZ).replace(minute=0, second=0, microsecond=0).isoformat()
                    per_user_hour[uid][hour_key] += 1
                except Exception:
                    continue

            active_lines: list[str] = []
            ordered_active = sorted(
                [(u, c) for u, c in per_user_counts.items() if (not non_bot_ids or u in non_bot_ids)],
                key=lambda x: x[1],
                reverse=True,
            )
            for idx, (uid, cnt) in enumerate(ordered_active, start=1):
                last = per_user_last.get(uid)
                last_ts = last[0] if last else None
                peak_ts = None
                peak_cnt = 0
                if per_user_hour.get(uid):
                    peak_ts, peak_cnt = max(per_user_hour[uid].items(), key=lambda x: (x[1], x[0]))
                last_local = datetime.fromisoformat(last_ts.replace("Z", "+00:00")).astimezone(ROME_TZ).strftime("%d/%m %H:%M") if last_ts else "—"
                peak_local = datetime.fromisoformat(peak_ts.replace("Z", "+00:00")).astimezone(ROME_TZ).strftime("%d/%m %H:00") if peak_ts else "—"
                rel = self._human_relative(last_ts, end_ts)
                disp = getattr(guild.get_member(uid), "display_name", f"ID {uid}")
                active_lines.append(f"{idx}) <@{uid}> ({disp}) ({cnt} msg) | 💬 Ultimo: {last_local} 🕒 {rel} | 🔥 Picco: {peak_local} ({peak_cnt} msg)")

                global_user_totals[uid] += int(cnt)
                if uid not in global_user_last or (last_ts and last_ts > global_user_last[uid][0]):
                    global_user_last[uid] = (last_ts or "", channel_name)
                if peak_ts:
                    prev = global_user_peak.get(uid)
                    if prev is None or peak_cnt > prev[0]:
                        global_user_peak[uid] = (peak_cnt, peak_ts, channel_name)
                prev_best = global_user_best_channel.get(uid)
                if prev_best is None or cnt > prev_best[0]:
                    global_user_best_channel[uid] = (cnt, channel_name)

            hist_counts = await self._database.fetch_user_counts_in_range_channel(guild_id, channel_id, lookback_start, end_ts)
            hist_last = await self._database.fetch_user_last_message_in_channel_since(guild_id, channel_id, lookback_start)
            historical_counts_by_channel[channel_id] = hist_counts
            historical_last_by_channel[channel_id] = hist_last

            inactive_candidates = {m.id for m in guild.members if not m.bot} if guild.members else set()
            if member_access_count is not None and guild.members:
                inactive_candidates = {m.id for m in guild.members if not m.bot and dc.permissions_for(m).view_channel}
            inactive_ids = list(inactive_candidates - active_non_bot_ids)

            payloads.append(
                {
                    "channel": dc,
                    "details": details,
                    "active_non_bot": len(active_non_bot_ids),
                    "members_with_access": member_access_count,
                    "inactive_non_bot": len(inactive_ids),
                    "peak_hour": peak_hour,
                    "silence_hour": silence_hour,
                    "continuity_hours": continuity,
                    "is_voice": isinstance(dc, discord.VoiceChannel),
                    "voice_sessions_count": 0,
                    "voice_total_seconds": 0,
                    "voice_details": [],
                    "inactive_user_ids": inactive_ids,
                    "active_lines": active_lines,
                }
            )

        # Voice details + inactive per channel (recency ordering)
        global_last_ts_monitored: dict[int, str] = {}
        global_last_channel_monitored: dict[int, str] = {}
        for p in payloads:
            ch_id = str(p["channel"].id)
            ch_label = f"#{p['channel'].name}"
            for uid, info in historical_last_by_channel.get(ch_id, {}).items():
                ts = info[0]
                prev = global_last_ts_monitored.get(uid)
                if prev is None or ts > prev:
                    global_last_ts_monitored[uid] = ts
                    global_last_channel_monitored[uid] = ch_label

            if p.get("is_voice"):
                sessions = await self._database.fetch_voice_sessions_in_range(
                    guild_id=guild_id,
                    voice_channel_id=ch_id,
                    start_ts=start_ts,
                    end_ts=end_ts,
                )
                total_seconds = 0
                details_lines: list[str] = []
                for row in sessions:
                    started = datetime.fromisoformat(str(row["started_ts"]).replace("Z", "+00:00"))
                    ended_raw = row["ended_ts"]
                    ended = datetime.fromisoformat(str(ended_raw).replace("Z", "+00:00")) if ended_raw else datetime.now(timezone.utc)
                    dur = max(0, int((ended - started).total_seconds()))
                    total_seconds += dur
                    details_lines.append(f"- {started.astimezone(ROME_TZ).strftime('%H:%M')} → {ended.astimezone(ROME_TZ).strftime('%H:%M')} ({dur // 60}m)")
                p["voice_sessions_count"] = len(sessions)
                p["voice_total_seconds"] = total_seconds
                p["voice_details"] = details_lines

        for p in payloads:
            ch_id = str(p["channel"].id)
            hist_last_ch = historical_last_by_channel.get(ch_id, {})
            hist_counts_ch = historical_counts_by_channel.get(ch_id, {})
            entries = []
            for uid in p.get("inactive_user_ids", []):
                display_name = getattr(guild.get_member(uid), "display_name", f"ID {uid}")
                channel_last = hist_last_ch.get(uid)
                last_ts = channel_last[0] if channel_last else global_last_ts_monitored.get(uid)
                entries.append({"user_id": uid, "display_name": display_name, "last_message_ts": last_ts})
            ordered = sort_inactive_entries(entries)
            lines: list[str] = []
            for idx, e in enumerate(ordered, start=1):
                uid = int(e["user_id"])
                disp = str(e["display_name"])
                last_ts = e.get("last_message_ts")
                if last_ts:
                    ts_local = datetime.fromisoformat(str(last_ts).replace("Z", "+00:00")).astimezone(ROME_TZ).strftime("%d/%m %H:%M")
                    rel = self._human_relative(str(last_ts), end_ts)
                    hist_peak_cnt = int(hist_counts_ch.get(uid, 0))
                    lines.append(f"{idx}) <@{uid}> ({disp}) (0 msg) | 💬 Ultimo: {ts_local} 🕒 {rel} | 🔥 Picco: — ({hist_peak_cnt} msg)")
                else:
                    lines.append(f"{idx}) <@{uid}> ({disp}) (0 msg) (mai partecipato dall'ingresso 🥀)")
            p["inactive_lines"] = lines

        server_total_messages = sum(server_hour_buckets)
        server_peak = max(range(24), key=lambda h: (server_hour_buckets[h], -h)) if server_total_messages > 0 else None
        server_silence = min(range(24), key=lambda h: (server_hour_buckets[h], h)) if server_total_messages > 0 else None
        server_continuity = sum(1 for v in server_hour_buckets if v > 0)

        global_active_rows: list[str] = []
        for idx, (uid, total_cnt) in enumerate(sorted(global_user_totals.items(), key=lambda x: x[1], reverse=True), start=1):
            last = global_user_last.get(uid)
            peak = global_user_peak.get(uid)
            best = global_user_best_channel.get(uid)
            if last:
                last_ts, last_ch = last
                last_local = datetime.fromisoformat(last_ts.replace("Z", "+00:00")).astimezone(ROME_TZ).strftime("%d/%m %H:%M") if last_ts else "—"
                rel = self._human_relative(last_ts, end_ts)
            else:
                last_local, last_ch, rel = "—", "—", "—"
            if peak:
                peak_cnt, peak_ts, peak_ch = peak
                peak_local = datetime.fromisoformat(peak_ts.replace("Z", "+00:00")).astimezone(ROME_TZ).strftime("%d/%m %H:00")
            else:
                peak_cnt, peak_local, peak_ch = 0, "—", "—"
            best_ch = best[1] if best else "—"
            disp = getattr(guild.get_member(uid), "display_name", f"ID {uid}")
            global_active_rows.append(
                f"{idx}) <@{uid}> ({disp}) ({total_cnt} msg totali) | 💬 Ultimo: {last_local} in \"{last_ch}\" 🕒 {rel} | 🔥 Picco: {peak_local} in \"{peak_ch}\" ({peak_cnt} msg) | 🗣️ Ha partecipato maggiormente in: \"{best_ch}\""
            )

        active_ids = set(global_user_totals.keys())
        all_non_bot_ids = {m.id for m in guild.members if not m.bot} if guild.members else set()
        global_entries = []
        for uid in (all_non_bot_ids - active_ids):
            disp = getattr(guild.get_member(uid), "display_name", f"ID {uid}")
            global_entries.append({"user_id": uid, "display_name": disp, "last_message_ts": global_last_ts_monitored.get(uid)})
        ordered_global_inactive = sort_inactive_entries(global_entries)

        global_inactive_rows: list[str] = []
        for idx, e in enumerate(ordered_global_inactive, start=1):
            uid = int(e["user_id"])
            disp = str(e["display_name"])
            last_ts = e.get("last_message_ts")
            peak_ch = "—"
            peak_cnt = 0
            dom_ch = "—"
            for p in payloads:
                ch_id = str(p["channel"].id)
                ch_label = f"#{p['channel'].name}"
                cnt = int(historical_counts_by_channel.get(ch_id, {}).get(uid, 0))
                if cnt > peak_cnt:
                    peak_cnt = cnt
                    peak_ch = ch_label
                if cnt > 0:
                    dom_ch = ch_label
            if last_ts:
                last_ch = global_last_channel_monitored.get(uid, "—")
                ts_local = datetime.fromisoformat(str(last_ts).replace("Z", "+00:00")).astimezone(ROME_TZ).strftime("%d/%m %H:%M")
                rel = self._human_relative(str(last_ts), end_ts)
                global_inactive_rows.append(
                    f"{idx}) <@{uid}> ({disp}) (0 msg totali) | 💬 Ultimo: {ts_local} in \"{last_ch}\" 🕒 {rel} | 🔥 Picco: — in \"{peak_ch}\" ({peak_cnt} msg) | 🗣️ Ha partecipato maggiormente in: \"{dom_ch}\""
                )
            else:
                global_inactive_rows.append(f"{idx}) <@{uid}> ({disp}) (0 msg totali) (mai partecipato dall'ingresso 🥀)")

        avg_server_score = int(round(sum(p["details"].score.score for p in payloads) / len(payloads))) if payloads else 0
        server_label = "ASSENTE" if avg_server_score <= 20 else "SCARSA" if avg_server_score <= 40 else "MEDIOCRE" if avg_server_score <= 60 else "INTENSA"
        server_trend = payloads[0]["details"].score.trend_text if payloads else "Messaggi stabili rispetto alla finestra precedente."

        server_summary = {
            "active_non_bot": len(server_active_non_bot),
            "total_non_bot_members": total_non_bot_members,
            "inactive_non_bot": (max(0, (total_non_bot_members or 0) - len(server_active_non_bot)) if total_non_bot_members is not None else None),
            "peak_hour": server_peak,
            "silence_hour": server_silence,
            "continuity_hours": server_continuity,
            "label": server_label,
            "score": avg_server_score,
            "trend_text": server_trend,
            "global_active_rows": global_active_rows,
            "global_inactive_rows": global_inactive_rows,
            "window_start_local": start_local.strftime("%d/%m/%Y %H:%M"),
            "window_end_local": end_local.strftime("%d/%m/%Y %H:%M"),
            "period_label": period_label,
        }

        embeds = build_daily_activity_embeds(
            guild,
            guild.name,
            payloads,
            server_summary=server_summary,
            period_label=period_label,
            window_start_dt=start_local,
            window_end_dt=end_local,
            requested_quantity=requested_quantity,
            requested_unit=requested_unit,
        )
        activity_txt_payload = build_daily_activity_details_txt(
            guild,
            guild.name,
            payloads,
            server_summary=server_summary,
            period_label=period_label,
            window_start_dt=start_local,
            window_end_dt=end_local,
            requested_quantity=requested_quantity,
            requested_unit=requested_unit,
        )

        report_embeds = list(embeds)
        inactive_txt_file: discord.File | None = None
        inactive_txt_payload: str | None = None
        if self._inactive_moderation is not None:
            try:
                inactive_embeds, inactive_txt_file, _ = await self._inactive_moderation.build_serverwide_inactive_embeds(
                    guild_id,
                    mod_channel_id,
                    include_actions_view=False,
                )
                report_embeds.extend(inactive_embeds)
                inactive_txt_payload = self._extract_txt_payload(inactive_txt_file)

                cfg = await self._inactive_moderation._get_config(guild_id)
                if cfg and bool(cfg.get("enabled")) and bool(cfg.get("auto_enabled")):
                    reminder_stats = await self._inactive_moderation.execute_reminders(guild_id)
                    kick_stats = await self._inactive_moderation.execute_kick_pipeline(guild_id, require_grace=True)
                    report_embeds.append(self._inactive_moderation.build_auto_inactive_completed_embed(reminder_stats, kick_stats))
            except Exception:
                logger.exception("daily_activity_report: inactive moderation post-processing failed guild=%s", guild_id)

        if not report_embeds:
            return

        _, _, txt_file = build_combined_activity_inactive_txt(
            activity_txt_payload=activity_txt_payload,
            inactive_txt_payload=inactive_txt_payload,
        )

        view = DailyReportPaginationView(self, current_index=0, total_pages=len(report_embeds))
        try:
            message = await channel.send(embed=report_embeds[0], view=view, file=txt_file)
        except Exception:
            logger.warning("daily_activity_report: failed sending txt attachment guild=%s channel=%s", guild_id, mod_channel_id)
            message = await channel.send(embed=report_embeds[0], view=view)
        await self.persist_pagination_record(
            message_id=str(message.id),
            channel_id=str(message.channel.id),
            guild_id=guild_id,
            embeds=report_embeds,
            metadata={"has_activity": bool(activity_txt_payload), "has_inactive": bool(inactive_txt_payload)},
            current_index=0,
        )
