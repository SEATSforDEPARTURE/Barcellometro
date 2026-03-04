from __future__ import annotations

import asyncio
import logging
import random
import re
from urllib.parse import urljoin
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import aiohttp
import discord

from app.services.barcello import BarcelloService
from app.services.community_insights import CommunityInsightsService
from app.services.database import DatabaseService
from app.services.ai import AiService

logger = logging.getLogger(__name__)

ROME_TZ = ZoneInfo("Europe/Rome")

QUIET_DEFAULT_START = "01:00"
QUIET_DEFAULT_END = "08:30"
QUIET_DEFAULT_ENABLED = True
CAP_DEFAULT = 6
CAP_DEFAULT_ENABLED = True
BARCELLO_CACHE_TTL_SECONDS = 60
DEFAULT_CAMPAIGN_EMBED_COLOR = 0x2F3136
CAMPAIGN_EMBED_FOOTER = "Questo servizio è offerto dal vostro Barcellometruccio di fiducia."
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
    ) -> None:
        self._database = database
        self._bot = bot
        self._community_insights = community_insights
        self._barcello_service = barcello_service
        self._ai_service = ai_service
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
                next_run_at=calculate_next_run_after_send(now, int(campaign["interval_minutes"]), int(campaign["jitter_seconds"])).isoformat(),
                last_sent_at=None,
            )
            return
        channel_id = str(campaign_channel_id)

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
                    next_run_at=calculate_next_run_after_send(now, int(campaign["interval_minutes"]), int(campaign["jitter_seconds"])).isoformat(),
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
                next_run_at=calculate_next_run_after_send(now, int(campaign["interval_minutes"]), int(campaign["jitter_seconds"])).isoformat(),
                last_sent_at=None,
            )
            return

        resolved_text, send_reason, debug_payload = await self._resolve_campaign_text(campaign, guild_id, channel_id)
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
                next_run_at=calculate_next_run_after_send(now, int(campaign["interval_minutes"]), int(campaign["jitter_seconds"])).isoformat(),
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
                    next_run_at=calculate_next_run_after_send(now, int(campaign["interval_minutes"]), int(campaign["jitter_seconds"])).isoformat(),
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
                next_run_at=calculate_next_run_after_send(now, int(campaign["interval_minutes"]), int(campaign["jitter_seconds"])).isoformat(),
                last_sent_at=None,
            )
            return

        logger.info("Sending campaign id=%s to channel_id=%s", campaign_id, channel_id)
        try:
            await self.send_campaign_embed(channel, campaign, resolved_text)
            await self._database.insert_send_log(
                campaign_id=campaign_id,
                guild_id=guild_id,
                channel_id=channel_id,
                sent_at=now.isoformat(),
                status="sent",
                reason=send_reason,
                error=None,
            )
            await self._database.update_campaign_next_run(
                guild_id=guild_id,
                campaign_id=campaign_id,
                next_run_at=calculate_next_run_after_send(now, int(campaign["interval_minutes"]), int(campaign["jitter_seconds"])).isoformat(),
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
                next_run_at=calculate_next_run_after_send(now, int(campaign["interval_minutes"]), int(campaign["jitter_seconds"])).isoformat(),
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
        return await self._resolve_campaign_text(campaign, guild_id, channel_id)

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
    ) -> None:
        base_title = str(campaign.get("embed_title") or campaign.get("name") or "📣 Campagna")
        raw_text = str(rendered_text or "")
        campaign_type = str(campaign.get("type") or "")
        color = self._parse_embed_color(campaign.get("embed_color"))

        if campaign_type == "AI_PROMPT":
            items, tail_text = self._parse_ai_prompt_news_items(raw_text)
            if items:
                limited_items = items[:MAX_EMBEDS_PER_MESSAGE]
                embeds: list[discord.Embed] = []
                og_fetches = 0
                for index, item in enumerate(limited_items):
                    description = str(item.get("summary") or "").strip()
                    if index == len(limited_items) - 1 and tail_text.strip():
                        description = f"{description}\n\n{tail_text.strip()}".strip()
                    embed_kwargs: dict[str, object] = {
                        "title": f"{str(item.get('emoji') or '').strip()} {str(item.get('title') or '').strip()}".strip(),
                        "description": description or None,
                        "colour": color,
                    }
                    source_url = str(item.get("source_url") or "").strip()
                    if self._is_http_url(source_url):
                        embed_kwargs["url"] = source_url
                    embed = discord.Embed(**embed_kwargs)

                    image_url = str(item.get("image_url") or "").strip()
                    if not self._is_http_url(image_url) and self._is_http_url(source_url) and og_fetches < 3:
                        og_fetches += 1
                        try:
                            image_url = (await self._fetch_og_image(source_url)) or ""
                        except Exception:  # noqa: BLE001
                            logger.warning("Failed OG image fetch for source %s", source_url, exc_info=True)
                            image_url = ""
                    if self._is_http_url(image_url):
                        embed.set_image(url=image_url)

                    embed.set_footer(text=CAMPAIGN_EMBED_FOOTER)
                    embeds.append(embed)

                logger.info(
                    "campaign_send_embed_news items=%s raw_len=%s title=%s campaign_id=%s",
                    len(embeds),
                    len(raw_text),
                    base_title,
                    campaign.get("id"),
                )
                await channel.send(embeds=embeds)
                return

        pages = split_embed_pages(raw_text, limit=3900)
        if len(pages) > MAX_EMBEDS_PER_MESSAGE:
            pages = split_embed_pages(raw_text, limit=4096)
        total = len(pages)

        embeds: list[discord.Embed] = []
        for page_index, page in enumerate(pages, start=1):
            title = base_title if total == 1 else f"{base_title} • PAG {page_index}/{total}"
            embed = discord.Embed(title=title, description=page, colour=color)
            embed.set_footer(text=CAMPAIGN_EMBED_FOOTER)
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

    def _is_http_url(self, value: str) -> bool:
        return bool(re.match(r"^https?://\S+$", value.strip(), flags=re.IGNORECASE))

    def _extract_url(self, value: str) -> str:
        match = re.search(r"https?://\S+", value, flags=re.IGNORECASE)
        if not match:
            return ""
        return match.group(0).rstrip(").,;!]")

    def _parse_news_title_line(self, line: str) -> tuple[str, str, str]:
        content = re.sub(r"^\s*[•*-]\s*", "", line).strip()
        emoji = ""
        parts = content.split(maxsplit=1)
        if parts and not any(ch.isalnum() for ch in parts[0]) and len(parts) > 1:
            emoji = parts[0].strip()
            content = parts[1].strip()

        source_url = ""
        md_link = re.search(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", content)
        if md_link:
            title = md_link.group(1).strip()
            source_url = md_link.group(2).strip()
            return emoji, title, source_url

        bold = re.search(r"\*\*([^*]+)\*\*", content)
        if bold:
            title = bold.group(1).strip()
        else:
            title = content.strip()
        return emoji, title, source_url

    def _parse_ai_prompt_news_items(self, text: str) -> tuple[list[dict[str, str]], str]:
        lines = text.splitlines()
        item_start_indexes = [idx for idx, line in enumerate(lines) if re.match(r"^\s*[•*-]\s+", line)]
        if not item_start_indexes:
            return [], ""

        items: list[dict[str, str]] = []
        tail_text = ""
        for index, start_idx in enumerate(item_start_indexes):
            end_idx = item_start_indexes[index + 1] if index + 1 < len(item_start_indexes) else len(lines)
            block = lines[start_idx:end_idx]
            if not block:
                continue

            emoji, title, source_url = self._parse_news_title_line(block[0])
            if not title:
                continue

            summary_lines: list[str] = []
            image_url = ""
            in_tail = False
            tail_lines: list[str] = []

            for body_line in block[1:]:
                stripped = body_line.strip()
                if not stripped:
                    if summary_lines and index == len(item_start_indexes) - 1:
                        in_tail = True
                    if in_tail:
                        tail_lines.append("")
                    continue

                source_match = re.match(r"^\s*(?:🔗\s*)?fonte\s*:\s*(.+)$", stripped, flags=re.IGNORECASE)
                if source_match:
                    maybe_url = self._extract_url(source_match.group(1))
                    if self._is_http_url(maybe_url):
                        source_url = maybe_url
                    continue

                image_match = re.match(r"^\s*(?:📸\s*)?immagine\s*:\s*(.+)$", stripped, flags=re.IGNORECASE)
                if image_match:
                    maybe_image = self._extract_url(image_match.group(1))
                    if self._is_http_url(maybe_image):
                        image_url = maybe_image
                    continue

                if in_tail and index == len(item_start_indexes) - 1:
                    tail_lines.append(body_line)
                else:
                    summary_lines.append(body_line)

            cleaned_summary = "\n".join(line.rstrip() for line in summary_lines).strip()
            items.append(
                {
                    "emoji": emoji,
                    "title": title,
                    "summary": cleaned_summary,
                    "source_url": source_url if self._is_http_url(source_url) else "",
                    "image_url": image_url if self._is_http_url(image_url) else "",
                }
            )
            if index == len(item_start_indexes) - 1 and tail_lines:
                tail_text = "\n".join(tail_lines).strip()

        return items, tail_text

    async def _fetch_og_image(self, url: str) -> Optional[str]:
        if not self._is_http_url(url):
            return None

        timeout = aiohttp.ClientTimeout(total=8)
        max_bytes = 512 * 1024
        headers = {"User-Agent": "BarcellometroBot/1.0"}
        html = ""
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url, allow_redirects=True) as response:
                    if response.status >= 400:
                        return None
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.content.iter_chunked(16384):
                        chunks.append(chunk)
                        total += len(chunk)
                        if total >= max_bytes:
                            break
                    html = b"".join(chunks).decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            logger.debug("OG image fetch failed for %s", url, exc_info=True)
            return None

        for tag in re.findall(r"<meta[^>]+>", html, flags=re.IGNORECASE):
            attrs = {key.lower(): value for key, value in re.findall(r'([a-zA-Z_:]+)\s*=\s*["\']([^"\']+)["\']', tag)}
            property_name = attrs.get("property", "").lower()
            name_name = attrs.get("name", "").lower()
            if property_name not in {"og:image", "twitter:image"} and name_name not in {"og:image", "twitter:image"}:
                continue
            content = attrs.get("content", "").strip()
            if not content:
                continue
            resolved = urljoin(url, content)
            if self._is_http_url(resolved):
                return resolved
        return None

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
        if campaign_type == "AI_PROMPT":
            prompt = str(campaign.get("text") or "")
            if not prompt:
                return None, "no_prompt", {"mood_mode": "AI_PROMPT", "barcello_color": None, "barcello_score": None, "selected_source": "base", "cache_status": "n/a"}
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
                return None, "ai_disabled", {"mood_mode": "AI_PROMPT", "barcello_color": barcello_color, "barcello_score": barcello_score, "selected_source": "fallback", "cache_status": "n/a"}
            model = self._ai_service.get_model("summary") or "gpt-4o-mini"
            web_enabled_raw = await self._get_setting_with_default("messages_ai_prompt_web_enabled", "true")
            web_enabled = web_enabled_raw.lower() in {"1", "true", "yes", "y"}
            logger.info("AI_PROMPT resolve settings: ai_prompt_web=%s model=%s", str(web_enabled).lower(), model)

            persona_system = self._campaign_persona_system_prompt(include_web_instruction=web_enabled)
            if web_enabled:
                try:
                    text = await self._ai_service.ask_general_with_web(
                        resolved_prompt,
                        persona_system,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("AI_PROMPT web generation failed, fallback to non-web")
                    text = await self._ai_service.ask_general(resolved_prompt, self._campaign_persona_system_prompt())
            else:
                text = await self._ai_service.ask_general(resolved_prompt, persona_system)

            text = (text or "").strip() or "AI non disponibile"
            return text, "ai_prompt", {"mood_mode": "AI_PROMPT", "barcello_color": barcello_color, "barcello_score": barcello_score, "selected_source": "ai", "cache_status": "n/a"}

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
