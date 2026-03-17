from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Optional

import discord

from app.services.footer import attach_footer_meta

from app.services.barcello import BarcelloService
from app.services.community_insights import CommunityInsightsService
from app.services.database import DatabaseService
from app.services.ai import AiService
from app.services.scheduler_utils import (
    ROME_TZ,
    calculate_initial_next_run,
    calculate_next_run_after_send,
    is_in_quiet_hours,
)

ONE_SHOT_RETRY_MINUTES = 5

if TYPE_CHECKING:
    from app.services.campaign_content_service import CampaignContentService

logger = logging.getLogger(__name__)

QUIET_DEFAULT_START = "01:00"
QUIET_DEFAULT_END = "08:30"
QUIET_DEFAULT_ENABLED = True
CAP_DEFAULT = 6
CAP_DEFAULT_ENABLED = True
BARCELLO_CACHE_TTL_SECONDS = 60
AI_PROMPT_SLOT_CACHE_TTL_SECONDS = 600
DEFAULT_CAMPAIGN_EMBED_COLOR = 0x2F3136
MAX_EMBEDS_PER_MESSAGE = 10

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


def _campaign_footer_service_name(campaign_type: str) -> str:
    return "campagne_prompt" if str(campaign_type or "").upper() == "AI_PROMPT" else "campagne_timer"


def split_embed_pages(text: str, limit: int = 3900) -> list[str]:
    if limit <= 0:
        raise ValueError("limit must be > 0")
    if not text:
        return [""]

    pages: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if current:
                pages.append(current)
                current = ""
            pages.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) <= limit:
            current += line
        else:
            if current:
                pages.append(current)
            current = line

    if current or not pages:
        pages.append(current)
    return pages


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
        ai_service: Optional[AiService] = None,
        campaign_content_service: Optional["CampaignContentService"] = None,
    ) -> None:
        self._database = database
        self._bot = bot
        self._community_insights = community_insights
        self._barcello_service = barcello_service
        self._ai_service = ai_service
        self._campaign_content_service = campaign_content_service
        self._task: Optional[asyncio.Task[None]] = None
        self._barcello_cache: dict[str, tuple[datetime, str, Optional[int]]] = {}
        self._ai_prompt_slot_cache: dict[tuple[int, str], tuple[datetime, str]] = {}
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
        if self._campaign_content_service is not None:
            await self._campaign_content_service.process_due_services(now)
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
        interval_minutes = int(campaign["interval_minutes"])
        is_one_shot = interval_minutes <= 0
        next_run_dt = (
            now + timedelta(minutes=ONE_SHOT_RETRY_MINUTES)
            if is_one_shot
            else calculate_next_run_after_send(now, interval_minutes, int(campaign["jitter_seconds"]))
        )
        next_run_at = next_run_dt.isoformat()
        campaign_channel_id = campaign.get("channel_id")
        if not campaign_channel_id:
            logger.error("Campaign %s missing channel_id", campaign_id)
            await self._database.insert_send_log(
                campaign_id=campaign_id,
                guild_id=guild_id,
                channel_id="unknown",
                sent_at=now.isoformat(),
                status="error",
                reason="missing_channel_id",
                error="missing channel_id",
            )
            await self._database.update_campaign_next_run(
                guild_id=guild_id,
                campaign_id=campaign_id,
                next_run_at=next_run_at,
                last_sent_at=None,
            )
            return
        channel_id = str(campaign_channel_id)
        due_slot = str(campaign.get("next_run_at") or now.isoformat())
        await self._database.update_campaign_next_run(
            guild_id=guild_id,
            campaign_id=campaign_id,
            next_run_at=next_run_at,
            last_sent_at=None,
        )

        if campaign_type == "AI_PROMPT":
            enabled_prompt = await self._database.get_trigger_enabled(guild_id, channel_id, "prompt")
            if not enabled_prompt:
                await self._database.insert_send_log(
                    campaign_id=campaign_id,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    sent_at=now.isoformat(),
                    status="skipped",
                    reason="prompt_trigger_disabled",
                    error=None,
                )
                await self._database.update_campaign_next_run(
                    guild_id=guild_id,
                    campaign_id=campaign_id,
                    next_run_at=next_run_at,
                    last_sent_at=None,
                )
                return

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
            await self._database.update_campaign_next_run(
                guild_id=guild_id,
                campaign_id=campaign_id,
                next_run_at=next_run_at,
                last_sent_at=None,
            )
            return

        resolved_text, send_reason, debug_payload = await self._resolve_campaign_text(campaign, guild_id, channel_id, due_slot=due_slot)
        logger.info(
            "Campaign selection guild=%s campaign=%s channel_id=%s mode=%s color=%s score=%s source=%s cache=%s",
            guild_id,
            campaign_id,
            channel_id,
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
                reason=send_reason or "no_text_for_mode",
                error=None,
            )
            await self._database.update_campaign_next_run(
                guild_id=guild_id,
                campaign_id=campaign_id,
                next_run_at=next_run_at,
                last_sent_at=None,
            )
            return

        channel = self._bot.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await self._bot.fetch_channel(int(channel_id))
            except (discord.Forbidden, discord.NotFound, discord.HTTPException, ValueError) as exc:
                logger.warning("Failed to resolve channel for campaign %s channel %s: %s", campaign_id, channel_id, exc)
                await self._database.insert_send_log(
                    campaign_id=campaign_id,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    sent_at=now.isoformat(),
                    status="error",
                    reason="missing_channel",
                    error=str(exc),
                )
                await self._database.update_campaign_next_run(
                    guild_id=guild_id,
                    campaign_id=campaign_id,
                    next_run_at=next_run_at,
                    last_sent_at=None,
                )
                return
        if not isinstance(channel, discord.abc.Messageable):
            await self._database.insert_send_log(
                campaign_id=campaign_id,
                guild_id=guild_id,
                channel_id=channel_id,
                sent_at=now.isoformat(),
                status="error",
                reason="missing_channel",
                error="Channel not messageable",
            )
            await self._database.update_campaign_next_run(
                guild_id=guild_id,
                campaign_id=campaign_id,
                next_run_at=next_run_at,
                last_sent_at=None,
            )
            return

        logger.info("Sending campaign id=%s to channel_id=%s", campaign_id, channel_id)
        try:
            await self.send_campaign_embed(
                channel,
                campaign,
                resolved_text,
                footer_contributors=debug_payload.get("footer_contributors"),
                used_local_processing=debug_payload.get("used_local_processing"),
            )
            await self._database.insert_send_log(
                campaign_id=campaign_id,
                guild_id=guild_id,
                channel_id=channel_id,
                sent_at=now.isoformat(),
                status="sent",
                reason=send_reason,
                error=None,
            )
            if is_one_shot and campaign_type == "AI_PROMPT":
                await self._database.soft_delete_message_campaign(guild_id, campaign_id)
                self._ai_prompt_slot_cache = {
                    key: value for key, value in self._ai_prompt_slot_cache.items() if key[0] != campaign_id
                }
                logger.info("One-shot campaign %s executed and deleted", campaign_id)
            elif is_one_shot:
                await self._database.update_campaign_next_run(
                    guild_id=guild_id,
                    campaign_id=campaign_id,
                    next_run_at=now.isoformat(),
                    last_sent_at=now.isoformat(),
                )
                await self._database.set_message_campaign_enabled(guild_id, campaign_id, False)
            else:
                await self._database.update_campaign_next_run(
                    guild_id=guild_id,
                    campaign_id=campaign_id,
                    next_run_at=next_run_at,
                    last_sent_at=now.isoformat(),
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
                next_run_at=next_run_at,
                last_sent_at=None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Campaign %s failed during processing/send", campaign_id)
            await self._database.insert_send_log(
                campaign_id=campaign_id,
                guild_id=guild_id,
                channel_id=channel_id,
                sent_at=now.isoformat(),
                status="error",
                reason="processing_failed",
                error=str(exc),
            )
            await self._database.update_campaign_next_run(
                guild_id=guild_id,
                campaign_id=campaign_id,
                next_run_at=next_run_at,
                last_sent_at=None,
            )

    async def preview_campaign_text(
        self,
        campaign: dict[str, object],
        *,
        channel_id_override: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[str], dict[str, object]]:
        guild_id = str(campaign["guild_id"])
        channel_id = channel_id_override or str(campaign.get("channel_id") or "")
        return await self._resolve_campaign_text(campaign, guild_id, channel_id, due_slot=None)

    def is_valid_embed_color(self, value: Optional[str]) -> bool:
        if value is None:
            return True
        parsed = str(value).strip()
        if not parsed:
            return True
        if parsed.startswith("#"):
            parsed = parsed[1:]
        elif parsed.lower().startswith("0x"):
            parsed = parsed[2:]
        return len(parsed) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in parsed)

    def _parse_embed_color(self, value: Optional[str]) -> int:
        if value is None:
            return DEFAULT_CAMPAIGN_EMBED_COLOR
        parsed = str(value).strip()
        if not parsed:
            return DEFAULT_CAMPAIGN_EMBED_COLOR
        if parsed.startswith("#"):
            parsed = parsed[1:]
        elif parsed.lower().startswith("0x"):
            parsed = parsed[2:]
        if len(parsed) != 6:
            logger.warning("Invalid embed_color=%s; using default", value)
            return DEFAULT_CAMPAIGN_EMBED_COLOR
        try:
            return int(parsed, 16)
        except ValueError:
            logger.warning("Invalid embed_color=%s; using default", value)
            return DEFAULT_CAMPAIGN_EMBED_COLOR

    async def send_campaign_embed(
        self,
        channel: discord.abc.Messageable,
        campaign: dict[str, object],
        rendered_text: Optional[str],
        *,
        footer_contributors: list[str] | None = None,
        used_local_processing: bool | None = None,
    ) -> None:
        campaign_type = str(campaign.get("type") or "").upper()
        embed_title = campaign.get("embed_title")
        campaign_name = str(campaign.get("name") or "").strip()
        if embed_title is not None and str(embed_title).strip():
            base_title = str(embed_title).strip()
        elif campaign_type == "AI_PROMPT" and not campaign_name:
            base_title = "🤔 CURIOSITÀ"
        elif campaign_name:
            base_title = campaign_name
        else:
            base_title = "📣 Campagna"
        raw_text = str(rendered_text or "")
        color = self._parse_embed_color(campaign.get("embed_color"))

        pages = split_embed_pages(raw_text, limit=3900)
        if len(pages) > MAX_EMBEDS_PER_MESSAGE:
            pages = split_embed_pages(raw_text, limit=4096)
        total = len(pages)

        embeds: list[discord.Embed] = []
        for page_index, page in enumerate(pages, start=1):
            title = base_title if total == 1 else f"{base_title} • PAG {page_index}/{total}"
            embed = discord.Embed(title=title, description=page, colour=color)
            footer_service = _campaign_footer_service_name(campaign_type)
            attach_footer_meta(
                embed,
                service_name=footer_service,
                contributors=footer_contributors,
                used_local_processing=(True if used_local_processing is None else used_local_processing),
            )
            embeds.append(embed)

        logger.info(
            "campaign_send_embed pages=%s raw_len=%s title=%s campaign_id=%s",
            total,
            len(raw_text),
            base_title,
            campaign.get("id"),
        )

        if total <= MAX_EMBEDS_PER_MESSAGE:
            await channel.send(embeds=embeds)
            return

        logger.warning(
            "campaign_send_embed_exceeds_message_limit pages=%s campaign_id=%s; sending in chunks",
            total,
            campaign.get("id"),
        )
        for idx in range(0, total, MAX_EMBEDS_PER_MESSAGE):
            await channel.send(embeds=embeds[idx : idx + MAX_EMBEDS_PER_MESSAGE])

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
        *,
        due_slot: str | None = None,
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
        if campaign_type == "AI_PROMPT":
            prompt = str(campaign.get("text") or "")
            if not prompt:
                return None, "no_prompt", {"mood_mode": "AI_PROMPT", "barcello_color": None, "barcello_score": None, "selected_source": "base", "cache_status": "n/a", "footer_contributors": None, "used_local_processing": True, "used_model_display": None, "used_model_config": None, "used_provider": None, "used_fallback": False}
            barcello_color, barcello_score, _, _ = await self._get_barcello_color(guild_id, channel_id)
            resolved_channel_id = int(channel_id) if channel_id.isdigit() else None
            channel = self._bot.get_channel(resolved_channel_id) if resolved_channel_id is not None else None
            channel_name = channel.name if channel and hasattr(channel, "name") else "canale"
            guild = self._bot.get_guild(int(guild_id))
            guild_name = guild.name if guild else "guild"
            today = datetime.now(ROME_TZ).date().isoformat()
            resolved_prompt = (
                prompt.replace("{guild_name}", guild_name)
                .replace("{channel_name}", channel_name)
                .replace("{barcello_score}", str(barcello_score or "n/a"))
                .replace("{barcello_color}", str(barcello_color or "n/a"))
                .replace("{today_date}", today)
            )
            if self._ai_service is None or not self._ai_service.is_enabled() or self._ai_service.client() is None:
                return None, "ai_disabled", {"mood_mode": "AI_PROMPT", "barcello_color": barcello_color, "barcello_score": barcello_score, "selected_source": "fallback", "cache_status": "n/a", "footer_contributors": None, "used_local_processing": True, "used_model_display": None, "used_model_config": None, "used_provider": None, "used_fallback": False}

            slot = due_slot or datetime.now(timezone.utc).isoformat()
            cache_key = (int(campaign["id"]), slot)
            cached = self._ai_prompt_slot_cache.get(cache_key)
            now_utc = datetime.now(timezone.utc)
            runtime_model = self._ai_service.get_runtime_model("campaign_prompt")
            model = self._ai_service.get_model_display_name("campaign_prompt") or "unknown"
            provider = str(runtime_model).split(":", 1)[0] if runtime_model else None
            used_fallback = bool(runtime_model and runtime_model != self._ai_service.get_model_config("campaign_prompt"))
            contributors = [model] if model and model != "unknown" else None
            if cached and cached[0] > now_utc:
                logger.info("AI cache hit campaign=%s slot=%s", campaign.get("id"), slot)
                return cached[1], "ai_prompt", {
                    "mood_mode": "AI_PROMPT",
                    "barcello_color": barcello_color,
                    "barcello_score": barcello_score,
                    "selected_source": "ai",
                    "cache_status": "hit",
                    "footer_contributors": contributors,
                    "used_local_processing": False if contributors else True,
                    "used_model_display": model,
                    "used_model_config": runtime_model,
                    "used_provider": provider,
                    "used_fallback": used_fallback,
                }
            logger.info("AI cache miss campaign=%s slot=%s", campaign.get("id"), slot)
            web_enabled_raw = await self._get_setting_with_default("messages_ai_prompt_web_enabled", "true")
            web_enabled = web_enabled_raw.lower() in {"1", "true", "yes", "y"}
            logger.info("AI_PROMPT resolve settings: ai_prompt_web=%s model=%s", str(web_enabled).lower(), model)

            persona_system = self._campaign_persona_system_prompt(include_web_instruction=web_enabled)
            if web_enabled:
                try:
                    text = await self._ai_service.ask_for_task_with_web(
                        "campaign_prompt",
                        resolved_prompt,
                        persona_system,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("AI_PROMPT web generation failed, fallback to non-web")
                    text = await self._ai_service.ask_for_task("campaign_prompt", resolved_prompt, self._campaign_persona_system_prompt())
            else:
                text = await self._ai_service.ask_for_task("campaign_prompt", resolved_prompt, persona_system)

            text = (text or "").strip() or "AI non disponibile"
            runtime_model = self._ai_service.get_runtime_model("campaign_prompt")
            provider = str(runtime_model).split(":", 1)[0] if runtime_model else provider
            model_display = self._ai_service.get_model_display_name("campaign_prompt") or model
            used_fallback = bool(runtime_model and runtime_model != self._ai_service.get_model_config("campaign_prompt"))
            contributors = [model_display] if model_display and model_display != "unknown" else None
            self._ai_prompt_slot_cache[cache_key] = (now_utc + timedelta(seconds=AI_PROMPT_SLOT_CACHE_TTL_SECONDS), text)
            return text, "ai_prompt", {
                "mood_mode": "AI_PROMPT",
                "barcello_color": barcello_color,
                "barcello_score": barcello_score,
                "selected_source": "ai",
                "cache_status": "miss",
                "footer_contributors": contributors,
                "used_local_processing": False if contributors else True,
                "used_model_display": model_display,
                "used_model_config": runtime_model,
                "used_provider": provider,
                "used_fallback": used_fallback,
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

    def _campaign_persona_system_prompt(self, *, include_web_instruction: bool = False) -> str:
        base = (
            "Sei il Barcellometro: tono brillante, chiaro e coinvolgente per community Discord. "
            "Non dire che non puoi fare real-time, non scusarti e non parlare dei limiti. "
            "Restituisci SOLO il testo finale pronto per Discord. "
            "Per ogni notizia usa un'emoji coerente col tema specifico (non sempre la stessa). "
            "Non stampare domini o link tra parentesi nel testo e non aggiungere la riga Fonte se il link è già nel titolo."
        )
        if include_web_instruction:
            return f"{base} Includi link diretti alle fonti nel testo quando usi il web."
        return base

    def status(self) -> dict[str, object]:
        return {
            "active": True,
            "state": "running" if self._task else "stopped",
            "metrics": dict(self._metrics),
        }
