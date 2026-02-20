from __future__ import annotations

import asyncio
import io
import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import discord

from app.renderers.activity_daily_report_renderer import build_daily_activity_details_txt, build_daily_activity_embeds
from app.services.activity_insights import ActivityInsightsService, ChannelActivityDetails
from app.services.database import DatabaseService

logger = logging.getLogger(__name__)
ROME_TZ = ZoneInfo("Europe/Rome")
DUE_WINDOW_SECONDS = 600


class DailyActivityReportService:
    def __init__(self, database: DatabaseService, bot: discord.Client, activity_service: ActivityInsightsService) -> None:
        self._database = database
        self._bot = bot
        self._activity = activity_service
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
                logger.exception("daily_activity_report tick failed")
            await asyncio.sleep(30)

    async def run_once(self) -> None:
        now_local = datetime.now(timezone.utc).astimezone(ROME_TZ)
        rows = await self._database.list_enabled_activity_monitoring_configs()
        for row in rows:
            guild_id = str(row["guild_id"])
            if row["last_sent_local_date"] == now_local.date().isoformat():
                continue
            try:
                hh, mm = str(row["send_time_local"] or "09:00").split(":", 1)
                send_local = now_local.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            except Exception:
                continue
            delta = (now_local - send_local).total_seconds()
            if delta < 0 or delta > DUE_WINDOW_SECONDS:
                continue
            await self._send_daily_report(guild_id=guild_id, mod_channel_id=str(row["mod_channel_id"] or ""))
            await self._database.mark_activity_monitoring_sent(guild_id, now_local.date().isoformat())

    async def send_now(self, *, guild_id: str, mod_channel_id: str) -> None:
        logger.info("daily_activity_report: manual send guild=%s channel=%s", guild_id, mod_channel_id)
        await self._send_daily_report(guild_id=guild_id, mod_channel_id=mod_channel_id)

    async def _count_non_bot_members(self, guild: discord.Guild) -> int | None:
        if guild.members:
            return sum(1 for m in guild.members if not m.bot)
        logger.warning("daily_activity_report: guild members cache not populated for guild=%s", guild.id)
        return None

    async def _count_members_with_access(self, guild: discord.Guild, channel: discord.abc.GuildChannel | discord.Thread) -> int | None:
        if not guild.members:
            return None
        try:
            everyone_can_view = channel.permissions_for(guild.default_role).view_channel
        except Exception:
            everyone_can_view = False
        non_bot_members = [m for m in guild.members if not m.bot]
        if everyone_can_view:
            return len(non_bot_members)
        count = 0
        for member in non_bot_members:
            try:
                if channel.permissions_for(member).view_channel:
                    count += 1
            except Exception:
                continue
        return count

    async def _send_daily_report(self, *, guild_id: str, mod_channel_id: str) -> None:
        if not mod_channel_id:
            return
        guild = self._bot.get_guild(int(guild_id))
        channel = self._bot.get_channel(int(mod_channel_id))
        if guild is None or not isinstance(channel, discord.abc.Messageable):
            return

        now_local = datetime.now(ROME_TZ)
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        start_ts = start_local.astimezone(timezone.utc).isoformat()
        end_ts = now_local.astimezone(timezone.utc).isoformat()

        total_non_bot_members = await self._count_non_bot_members(guild)
        non_bot_ids = {m.id for m in guild.members if not m.bot} if guild.members else set()

        channel_ids = await self._database.list_enabled_activity_channels(guild_id)
        payloads: list[dict[str, Any]] = []
        server_active_non_bot: set[int] = set()
        for channel_id in channel_ids:
            try:
                dc = guild.get_channel(int(channel_id))
            except Exception:
                dc = None
            if dc is None:
                continue
            details = await self._activity.compute_activity_for_channel(guild_id, str(channel_id), start_ts, end_ts)

            distinct_authors = await self._database.fetch_distinct_authors_in_range_channel(guild_id, str(channel_id), start_ts, end_ts)
            active_non_bot_ids = {uid for uid in distinct_authors if not non_bot_ids or uid in non_bot_ids}
            server_active_non_bot.update(active_non_bot_ids)

            member_access_count = await self._count_members_with_access(guild, dc)

            is_voice = isinstance(dc, discord.VoiceChannel)
            voice_sessions_count = 0
            voice_total_seconds = 0
            voice_details: list[str] = []
            if is_voice:
                sessions = await self._database.fetch_voice_sessions_in_range(
                    guild_id=guild_id,
                    voice_channel_id=str(channel_id),
                    start_ts=start_ts,
                    end_ts=end_ts,
                )
                for row in sessions:
                    started = datetime.fromisoformat(str(row["started_ts"]).replace("Z", "+00:00"))
                    ended_raw = row["ended_ts"]
                    ended = datetime.fromisoformat(str(ended_raw).replace("Z", "+00:00")) if ended_raw else datetime.now(timezone.utc)
                    duration = max(0, int((ended - started).total_seconds()))
                    voice_total_seconds += duration
                    voice_sessions_count += 1
                    voice_details.append(f"- {started.astimezone(ROME_TZ).strftime('%H:%M')} → {ended.astimezone(ROME_TZ).strftime('%H:%M')} ({duration // 60}m)")

            payloads.append(
                {
                    "channel": dc,
                    "details": details,
                    "active_non_bot": len(active_non_bot_ids),
                    "members_with_access": member_access_count,
                    "is_voice": is_voice,
                    "voice_sessions_count": voice_sessions_count,
                    "voice_total_seconds": voice_total_seconds,
                    "voice_details": voice_details,
                }
            )

        server_summary = {
            "active_non_bot": len(server_active_non_bot),
            "total_non_bot_members": total_non_bot_members,
        }
        embeds = build_daily_activity_embeds(guild, guild.name, payloads, server_summary=server_summary, reference_ts=end_ts)
        txt_payload = build_daily_activity_details_txt(guild, guild.name, payloads, server_summary=server_summary, reference_ts=end_ts)
        txt_file = discord.File(io.BytesIO(txt_payload.encode("utf-8")), filename="attivita_dettagli_giornalieri.txt")

        for idx in range(0, len(embeds), 10):
            batch = embeds[idx : idx + 10]
            if idx == 0:
                try:
                    await channel.send(embeds=batch, file=txt_file)
                except Exception:
                    logger.warning("daily_activity_report: failed sending txt attachment guild=%s channel=%s", guild_id, mod_channel_id)
                    await channel.send(embeds=batch)
            else:
                await channel.send(embeds=batch)
