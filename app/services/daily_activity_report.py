from __future__ import annotations

import asyncio
import io
import logging
from datetime import datetime, timezone
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

        channel_ids = await self._database.list_enabled_activity_channels(guild_id)
        payloads: list[tuple[discord.abc.GuildChannel | discord.Thread | None, ChannelActivityDetails]] = []
        for channel_id in channel_ids:
            try:
                dc = guild.get_channel(int(channel_id))
            except Exception:
                dc = None
            if dc is None:
                continue
            details = await self._activity.compute_activity_for_channel(guild_id, str(channel_id), start_ts, end_ts)
            payloads.append((dc, details))

        embeds = build_daily_activity_embeds(guild, guild.name, payloads, reference_ts=end_ts)
        txt_payload = build_daily_activity_details_txt(guild, guild.name, payloads, reference_ts=end_ts)
        txt_file = discord.File(io.BytesIO(txt_payload.encode("utf-8")), filename="attivita_dettagli_giornalieri.txt")

        for idx in range(0, len(embeds), 10):
            if idx == 0:
                await channel.send(embeds=embeds[idx : idx + 10], file=txt_file)
            else:
                await channel.send(embeds=embeds[idx : idx + 10])
