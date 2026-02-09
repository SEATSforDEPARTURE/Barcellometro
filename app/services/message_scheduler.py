from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import discord

from app.services.barcello import BarcelloService
from app.services.community_insights import CommunityInsightsService
from app.services.database import DatabaseService

logger = logging.getLogger(__name__)

ROME_TZ = ZoneInfo("Europe/Rome")

QUIET_DEFAULT_START = "01:00"
QUIET_DEFAULT_END = "08:30"
QUIET_DEFAULT_ENABLED = True
CAP_DEFAULT = 6
CAP_DEFAULT_ENABLED = True
BARCELLO_CACHE_TTL_SECONDS = 60

BARCELLO_COLOR_MAP = {
    "GREEN": "GREEN",
    "YELLOW": "YELLOW",
    "RED": "RED",
    "BLACK": "BLACK",
    "VERDE": "GREEN",
    "GIALLO": "YELLOW",
    "ROSSO": "RED",
    "NERO": "BLACK",
    "VERDE ": "GREEN",
    "GIALLO ": "YELLOW",
    "ROSSO ": "RED",
    "NERO ": "BLACK",
    "🟢": "GREEN",
    "🟡": "YELLOW",
    "🔴": "RED",
    "⚫": "BLACK",
}


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


def is_in_quiet_hours(now_local_time: time, start_str: str, end_str: str) -> bool:
    start = _parse_local_time(start_str)
    end = _parse_local_time(end_str)
    if start <= end:
        return start <= now_local_time < end
    return now_local_time >= start or now_local_time < end


def should_skip_for_daily_cap(sent_today: int, cap: int) -> bool:
    if cap <= 0:
        return False
    return sent_today >= cap


def select_round_robin_campaign(
    campaigns: list[dict[str, object]],
    last_campaign_id: Optional[int],
    now: datetime,
) -> Optional[dict[str, object]]:
    if not campaigns:
        return None
    ordered = sorted(campaigns, key=lambda item: int(item["id"]))
    if last_campaign_id is None:
        rotation = ordered
    else:
        rotation = []
        for campaign in ordered:
            if int(campaign["id"]) > last_campaign_id:
                rotation.append(campaign)
        rotation.extend(campaign for campaign in ordered if int(campaign["id"]) <= last_campaign_id)

    for campaign in rotation:
        next_run_at = _parse_iso(campaign.get("next_run_at"))
        if next_run_at and next_run_at <= now:
            return campaign
    return None


def select_text_for_mood(
    *,
    mood_mode: str,
    base_text: Optional[str],
    text_green: Optional[str],
    text_yellow: Optional[str],
    text_red: Optional[str],
    text_black: Optional[str],
    barcello_color: Optional[str],
) -> tuple[Optional[str], Optional[str], str]:
    if mood_mode == "IGNORE_BARCELLO":
        return base_text, None, "base"
    if mood_mode == "GREEN_ONLY":
        return text_green or base_text, "barcello_green", "green" if text_green else "base"
    if mood_mode == "YELLOW_ONLY":
        return text_yellow or base_text, "barcello_yellow", "yellow" if text_yellow else "base"
    if mood_mode == "RED_ONLY":
        return text_red or base_text, "barcello_red", "red" if text_red else "base"
    if mood_mode == "BLACK_ONLY":
        return text_black or base_text, "barcello_black", "black" if text_black else "base"
    if barcello_color == "GREEN":
        return text_green or base_text, "barcello_green", "green" if text_green else "base"
    if barcello_color == "YELLOW":
        return text_yellow or base_text, "barcello_yellow", "yellow" if text_yellow else "base"
    if barcello_color == "RED":
        return text_red or base_text, "barcello_red", "red" if text_red else "base"
    if barcello_color == "BLACK":
        return text_black or base_text, "barcello_black", "black" if text_black else "base"
    return base_text, "barcello_unavailable", "base"


def _parse_iso(value: object) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass(frozen=True)
class QuietSettings:
    enabled: bool
    start: str
    end: str


@dataclass(frozen=True)
class CapSettings:
    enabled: bool
    cap: int


class MessageSchedulerService:
    def __init__(
        self,
        database: DatabaseService,
        bot: discord.Client,
        *,
        community_insights: Optional[CommunityInsightsService] = None,
        barcello_service: Optional[BarcelloService] = None,
    ) -> None:
        self._database = database
        self._bot = bot
        self._community_insights = community_insights
        self._barcello_service = barcello_service
        self._task: Optional[asyncio.Task[None]] = None
        self._barcello_cache: dict[str, tuple[datetime, str, Optional[int]]] = {}
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
        guilds = await self._database.list_campaign_guilds()
        for guild_id in guilds:
            await self._process_guild(guild_id, now)
        due = await self._database.due_message_campaigns(now.isoformat())
        for campaign in due:
            if str(campaign.get("type")) != "CUSTOM":
                await self._process_campaign(campaign, now)
        self._metrics["last_tick_ts"] = now.isoformat()

    async def _process_guild(self, guild_id: str, now: datetime) -> None:
        campaigns = await self._database.list_custom_campaigns_enabled(guild_id)
        if not campaigns:
            return
        last_campaign_id = await self._database.get_rotation_state(guild_id)
        selected = select_round_robin_campaign(campaigns, last_campaign_id, now)
        if selected is None:
            return
        await self._process_campaign(selected, now)
        await self._database.set_rotation_state(guild_id, int(selected["id"]))

    async def _process_campaign(self, campaign: dict[str, object], now: datetime) -> None:
        guild_id = str(campaign["guild_id"])
        campaign_id = int(campaign["id"])
        campaign_type = str(campaign["type"])

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
            skip_reason = await self._skip_for_quiet_hours(now)
            if skip_reason is None:
                skip_reason = await self._skip_for_daily_cap(guild_id, channel_id, now)
            if skip_reason is None:
                skip_reason = await self._skip_for_idle(
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

            resolved_text, send_reason, debug_payload = await self._resolve_campaign_text(campaign, guild_id, channel_id)
            logger.info(
                "Campaign selection guild=%s campaign=%s mode=%s color=%s score=%s source=%s cache=%s",
                guild_id,
                campaign_id,
                debug_payload["mood_mode"],
                debug_payload["barcello_color"],
                debug_payload["barcello_score"],
                debug_payload["selected_source"],
                debug_payload["cache_status"],
            )
            if debug_payload.get("barcello_reason"):
                logger.info(
                    "Campaign barcello reason guild=%s campaign=%s reason=%s",
                    guild_id,
                    campaign_id,
                    debug_payload["barcello_reason"],
                )
            if not resolved_text:
                await self._database.insert_send_log(
                    campaign_id=campaign_id,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    sent_at=now.isoformat(),
                    status="skipped",
                    reason="no_text_for_mode",
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
                await channel.send(content=str(resolved_text))
                await self._database.insert_send_log(
                    campaign_id=campaign_id,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    sent_at=now.isoformat(),
                    status="sent",
                    reason=send_reason,
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

    async def _skip_for_quiet_hours(self, now: datetime) -> Optional[str]:
        settings = await self._get_quiet_settings()
        if not settings.enabled:
            return None
        try:
            local_time = now.astimezone(ROME_TZ).time()
            if is_in_quiet_hours(local_time, settings.start, settings.end):
                return "quiet_hours"
        except ValueError:
            logger.warning("Invalid quiet hours settings: %s-%s", settings.start, settings.end)
        return None

    async def _skip_for_daily_cap(self, guild_id: str, channel_id: str, now: datetime) -> Optional[str]:
        settings = await self._get_cap_settings()
        if not settings.enabled:
            return None
        day_str = now.astimezone(ROME_TZ).date().isoformat()
        sent_today = await self._database.count_sent_today(guild_id, channel_id, day_str)
        if should_skip_for_daily_cap(sent_today, settings.cap):
            return "daily_cap"
        return None

    async def _skip_for_idle(self, *, guild_id: str, channel_id: str, only_if_idle_minutes: int, now: datetime) -> Optional[str]:
        if only_if_idle_minutes <= 0:
            return None
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

    async def _resolve_campaign_text(
        self,
        campaign: dict[str, object],
        guild_id: str,
        channel_id: str,
    ) -> tuple[Optional[str], Optional[str], dict[str, object]]:
        campaign_type = str(campaign["type"])
        if campaign_type == "AI_INSIGHTS":
            text = await self._get_ai_message(guild_id)
            return text, "barcello_unavailable" if text else None, {
                "mood_mode": "AI_INSIGHTS",
                "barcello_color": "BLACK",
                "barcello_score": None,
                "selected_source": "base",
                "cache_status": "n/a",
            }

        mood_mode = str(campaign.get("mood_mode") or "AUTO")
        barcello_color, barcello_score, cache_status, barcello_reason = await self._get_barcello_color(guild_id, channel_id)
        text, reason, selected_source = select_text_for_mood(
            mood_mode=mood_mode,
            base_text=campaign.get("text"),
            text_green=campaign.get("text_green"),
            text_yellow=campaign.get("text_yellow"),
            text_red=campaign.get("text_red"),
            text_black=campaign.get("text_black"),
            barcello_color=barcello_color,
        )
        if mood_mode == "AUTO" and barcello_color == "BLACK" and not text:
            return None, "no_text_for_mode", {
                "mood_mode": mood_mode,
                "barcello_color": barcello_color,
                "barcello_score": barcello_score,
                "barcello_reason": barcello_reason,
                "selected_source": selected_source,
                "cache_status": cache_status,
            }
        if barcello_reason:
            return text, barcello_reason, {
                "mood_mode": mood_mode,
                "barcello_color": barcello_color,
                "barcello_score": barcello_score,
                "barcello_reason": barcello_reason,
                "selected_source": selected_source,
                "cache_status": cache_status,
            }
        return text, reason, {
            "mood_mode": mood_mode,
            "barcello_color": barcello_color,
            "barcello_score": barcello_score,
            "barcello_reason": barcello_reason,
            "selected_source": selected_source,
            "cache_status": cache_status,
        }

    async def _get_quiet_settings(self) -> QuietSettings:
        enabled_raw = await self._get_setting_with_default("messages_quiet_enabled", "1" if QUIET_DEFAULT_ENABLED else "0")
        start = await self._get_setting_with_default("messages_quiet_start", QUIET_DEFAULT_START)
        end = await self._get_setting_with_default("messages_quiet_end", QUIET_DEFAULT_END)
        return QuietSettings(
            enabled=enabled_raw.lower() in {"1", "true", "yes", "y"},
            start=start,
            end=end,
        )

    async def _get_cap_settings(self) -> CapSettings:
        enabled_raw = await self._get_setting_with_default("messages_daily_cap_enabled", "1" if CAP_DEFAULT_ENABLED else "0")
        cap_raw = await self._get_setting_with_default("messages_daily_cap", str(CAP_DEFAULT))
        try:
            cap = int(cap_raw)
        except ValueError:
            logger.warning("Invalid messages_daily_cap: %s", cap_raw)
            cap = CAP_DEFAULT
        return CapSettings(
            enabled=enabled_raw.lower() in {"1", "true", "yes", "y"},
            cap=cap,
        )

    async def _get_setting_with_default(self, key: str, default: str) -> str:
        stored = await self._database.get_setting(key)
        if stored is None:
            await self._database.set_setting(key, default)
            return default
        return stored

    async def _get_barcello_color(self, guild_id: str, channel_id: str) -> tuple[str, Optional[int], str, Optional[str]]:
        if self._barcello_service is None:
            return "BLACK", None, "disabled", "barcello_unavailable"
        cached = self._barcello_cache.get(guild_id)
        now = datetime.now(timezone.utc)
        if cached and cached[0] > now:
            return cached[1], cached[2], "hit", None
        try:
            status = await self._barcello_service.get_current_status(
                guild_id,
                channel_id=channel_id,
                window_minutes=180,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Barcello status failed; fallback BLACK. guild=%s channel=%s err=%s",
                guild_id,
                channel_id,
                repr(exc),
            )
            status = {"color": "BLACK", "score": None, "source": "fallback"}
        raw_color = str(status.get("color", "BLACK")).strip().upper()
        normalized = BARCELLO_COLOR_MAP.get(raw_color, "BLACK")
        score = status.get("score")
        reason = status.get("reason")
        logger.info(
            "Barcello status: guild=%s channel=%s color=%s score=%s",
            guild_id,
            channel_id,
            normalized,
            score,
        )
        self._barcello_cache[guild_id] = (now + timedelta(seconds=BARCELLO_CACHE_TTL_SECONDS), normalized, score)
        return normalized, score, "miss", reason

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
