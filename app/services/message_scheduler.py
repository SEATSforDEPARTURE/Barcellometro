from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import discord

from app.services.community_insights import CommunityInsightsService
from app.services.database import DatabaseService

logger = logging.getLogger(__name__)

ROME_TZ = ZoneInfo("Europe/Rome")


def _parse_local_time(value: str) -> time:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError("start_time_local must be HH:MM")
    hour = int(parts[0])
    minute = int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("start_time_local must be HH:MM")
    return time(hour=hour, minute=minute)


def calculate_initial_next_run(now_utc: datetime, start_time_local: str, interval_minutes: int, tz: ZoneInfo = ROME_TZ) -> datetime:
    if interval_minutes <= 0:
        raise ValueError("interval_minutes must be > 0")
    start_clock = _parse_local_time(start_time_local)
    now_local = now_utc.astimezone(tz)
    candidate_local = now_local.replace(
        hour=start_clock.hour,
        minute=start_clock.minute,
        second=0,
        microsecond=0,
    )
    if candidate_local <= now_local:
        delta_minutes = int((now_local - candidate_local).total_seconds() // 60)
        steps = delta_minutes // interval_minutes + 1
        candidate_local = candidate_local + timedelta(minutes=steps * interval_minutes)
    return candidate_local.astimezone(timezone.utc)


def calculate_next_run_after_send(now_utc: datetime, interval_minutes: int, jitter_seconds: int) -> datetime:
    jitter = random.randint(0, max(jitter_seconds, 0))
    return now_utc + timedelta(minutes=interval_minutes, seconds=jitter)


def should_skip_for_idle(
    *,
    last_activity: Optional[datetime],
    only_if_idle_minutes: int,
    now_utc: datetime,
) -> bool:
    if only_if_idle_minutes <= 0:
        return False
    if last_activity is None:
        return False
    return now_utc - last_activity < timedelta(minutes=only_if_idle_minutes)


class MessageSchedulerService:
    def __init__(
        self,
        database: DatabaseService,
        bot: discord.Client,
        *,
        community_insights: Optional[CommunityInsightsService] = None,
    ) -> None:
        self._database = database
        self._bot = bot
        self._community_insights = community_insights
        self._task: Optional[asyncio.Task[None]] = None
        self._metrics = {
            "last_tick_ts": None,
            "errors": 0,
        }

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001
                logger.exception("Message scheduler tick failed")
                self._metrics["errors"] += 1
            await asyncio.sleep(30)

    async def run_once(self) -> None:
        now = datetime.now(timezone.utc)
        due = await self._database.due_message_campaigns(now.isoformat())
        if due:
            logger.info("Message scheduler: %s campaigns due", len(due))
        for campaign in due:
            await self._process_campaign(campaign, now)
        self._metrics["last_tick_ts"] = now.isoformat()

    async def _process_campaign(self, campaign: dict[str, object], now: datetime) -> None:
        guild_id = str(campaign["guild_id"])
        campaign_id = int(campaign["id"])
        campaign_type = str(campaign["type"])
        text = campaign.get("text")
        if campaign_type == "AI_INSIGHTS":
            text = await self._get_ai_message(guild_id)
            if not text:
                logger.warning("Campaign %s has no AI message ready", campaign_id)
        if not text:
            await self._database.update_campaign_next_run(
                guild_id=guild_id,
                campaign_id=campaign_id,
                next_run_at=calculate_next_run_after_send(now, int(campaign["interval_minutes"]), int(campaign["jitter_seconds"])).isoformat(),
                last_sent_at=now.isoformat(),
            )
            return

        channel_ids = await self._database.list_enabled_message_channels(guild_id)
        if not channel_ids:
            logger.info("Campaign %s skipped (no enabled channels)", campaign_id)
            await self._database.update_campaign_next_run(
                guild_id=guild_id,
                campaign_id=campaign_id,
                next_run_at=calculate_next_run_after_send(now, int(campaign["interval_minutes"]), int(campaign["jitter_seconds"])).isoformat(),
                last_sent_at=now.isoformat(),
            )
            return

        for channel_id in channel_ids:
            skip_reason = await self._skip_reason(
                guild_id=guild_id,
                channel_id=channel_id,
                only_if_idle_minutes=int(campaign["only_if_idle_minutes"]),
                now=now,
            )
            if skip_reason:
                await self._database.insert_send_log(
                    campaign_id=campaign_id,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    sent_at=now.isoformat(),
                    status="skipped",
                    reason=skip_reason,
                    error=None,
                )
                continue

            channel = self._bot.get_channel(int(channel_id))
            if channel is None or not isinstance(channel, discord.abc.Messageable):
                await self._database.insert_send_log(
                    campaign_id=campaign_id,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    sent_at=now.isoformat(),
                    status="error",
                    reason="missing_channel",
                    error="Channel not found or not messageable",
                )
                continue

            try:
                await channel.send(content=str(text))
                await self._database.insert_send_log(
                    campaign_id=campaign_id,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    sent_at=now.isoformat(),
                    status="sent",
                    reason=None,
                    error=None,
                )
            except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
                logger.warning("Failed to send campaign %s to channel %s: %s", campaign_id, channel_id, exc)
                await self._database.insert_send_log(
                    campaign_id=campaign_id,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    sent_at=now.isoformat(),
                    status="error",
                    reason="send_failed",
                    error=str(exc),
                )

        await self._database.update_campaign_next_run(
            guild_id=guild_id,
            campaign_id=campaign_id,
            next_run_at=calculate_next_run_after_send(now, int(campaign["interval_minutes"]), int(campaign["jitter_seconds"])).isoformat(),
            last_sent_at=now.isoformat(),
        )

    async def _skip_reason(self, *, guild_id: str, channel_id: str, only_if_idle_minutes: int, now: datetime) -> Optional[str]:
        if await self._is_quiet_hours(now):
            return "quiet_hours"
        if await self._cap_reached(guild_id, channel_id, now):
            return "daily_cap_reached"
        if only_if_idle_minutes > 0:
            last_activity_ts = await self._database.get_channel_last_activity(guild_id, channel_id)
            last_activity = None
            if last_activity_ts:
                try:
                    last_activity = datetime.fromisoformat(last_activity_ts)
                    if last_activity.tzinfo is None:
                        last_activity = last_activity.replace(tzinfo=timezone.utc)
                except ValueError:
                    logger.warning("Invalid last_activity_ts for channel %s", channel_id)
            if should_skip_for_idle(
                last_activity=last_activity,
                only_if_idle_minutes=only_if_idle_minutes,
                now_utc=now,
            ):
                return "idle_check_failed"
        return None

    async def _is_quiet_hours(self, now: datetime) -> bool:
        start = await self._database.get_setting("messages_quiet_hours_start")
        end = await self._database.get_setting("messages_quiet_hours_end")
        if not start or not end:
            return False
        try:
            start_time = _parse_local_time(start)
            end_time = _parse_local_time(end)
        except ValueError:
            logger.warning("Invalid quiet hours settings: %s-%s", start, end)
            return False
        local_time = now.astimezone(ROME_TZ).time()
        if start_time <= end_time:
            return start_time <= local_time < end_time
        return local_time >= start_time or local_time < end_time

    async def _cap_reached(self, guild_id: str, channel_id: str, now: datetime) -> bool:
        cap_raw = await self._database.get_setting("messages_daily_cap_per_channel")
        if not cap_raw:
            return False
        try:
            cap = int(cap_raw)
        except ValueError:
            logger.warning("Invalid messages_daily_cap_per_channel: %s", cap_raw)
            return False
        if cap <= 0:
            return False
        local_now = now.astimezone(ROME_TZ)
        local_midnight = datetime.combine(local_now.date(), time.min, tzinfo=ROME_TZ)
        since_utc = local_midnight.astimezone(timezone.utc).isoformat()
        sent_count = await self._database.count_message_send_log_since(guild_id, channel_id, since_utc)
        return sent_count >= cap

    async def _get_ai_message(self, guild_id: str) -> Optional[str]:
        if self._community_insights is None:
            return None
        return await self._community_insights.get_next_message(guild_id)

    def status(self) -> dict[str, object]:
        return {
            "active": True,
            "state": "running" if self._task else "stopped",
            "metrics": dict(self._metrics),
        }
