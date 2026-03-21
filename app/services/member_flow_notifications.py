from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import discord

from app.services.footer import attach_footer_meta
from app.services.greetings_copy_service import GreetingsCopyService

logger = logging.getLogger(__name__)

_DURATION_RE = re.compile(r"^\s*(\d+)\s*([dhm])\s*$", re.IGNORECASE)
_CARD_SIZE = (900, 300)
_DEFAULT_LEAVE_DEDUPE_WINDOW_SECONDS = 300
_BLANK_FIELD_NAME = "​"
_VISIBLE_DEPARTURE_PRECEDENCE = {
    "leave": 10,
    "inactive_kick": 20,
    "kick": 30,
    "ban": 40,
    "tempban": 50,
    "inactive_tempban": 60,
}
_EXPLICIT_DEPARTURE_TYPES = frozenset(
    {
        "kick",
        "ban",
        "tempban",
        "inactive_kick",
        "inactive_tempban",
    }
)


def parse_duration_input(raw: str) -> int:
    match = _DURATION_RE.match((raw or "").strip())
    if not match:
        raise ValueError("Durata non valida. Usa un formato come 7d, 12h oppure 30m.")
    value = int(match.group(1))
    unit = match.group(2).lower()
    if value <= 0:
        raise ValueError("La durata deve essere maggiore di zero.")
    if unit == "d":
        return value * 86400
    if unit == "h":
        return value * 3600
    return value * 60


def format_duration_human(duration_seconds: int | None) -> str | None:
    if duration_seconds is None:
        return None
    total = max(0, int(duration_seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}g")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


async def generate_member_flow_card(
    *,
    member: discord.abc.User | discord.Member,
    guild_name: str,
    event_label: str,
) -> discord.File | None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None

    try:
        avatar_asset = getattr(member, "display_avatar", None)
        avatar_bytes = await avatar_asset.read() if avatar_asset is not None else None
        if not avatar_bytes:
            return None
        avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        avatar = avatar.resize((180, 180))

        canvas = Image.new("RGBA", _CARD_SIZE, (28, 31, 38, 255))
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle((20, 20, 880, 280), radius=24, fill=(47, 49, 54, 255))
        draw.ellipse((40, 60, 220, 240), fill=(88, 101, 242, 255))

        mask = Image.new("L", (180, 180), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 180, 180), fill=255)
        canvas.paste(avatar, (40, 60), mask)

        try:
            title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 42)
            body_font = ImageFont.truetype("DejaVuSans.ttf", 28)
        except Exception:
            title_font = ImageFont.load_default()
            body_font = ImageFont.load_default()

        display_name = getattr(member, "display_name", getattr(member, "name", "Utente"))
        draw.text((260, 78), event_label, font=title_font, fill=(255, 255, 255, 255))
        draw.text((260, 144), display_name[:32], font=body_font, fill=(220, 221, 222, 255))
        draw.text((260, 192), guild_name[:48], font=body_font, fill=(160, 164, 170, 255))

        out = io.BytesIO()
        canvas.save(out, format="PNG")
        out.seek(0)
        return discord.File(out, filename="member_flow_card.png")
    except Exception:
        logger.warning("member flow card generation failed", exc_info=True)
        return None


class MemberFlowNotificationsService:
    def __init__(self, database: Any, bot: discord.Client, *, barcello_service: Any | None = None) -> None:
        self._database = database
        self._copy_service = GreetingsCopyService(database, barcello_service=barcello_service)
        self._recent_departures: dict[tuple[str, str], tuple[str, datetime]] = {}

    def remember_departure_action(self, guild_id: str, user_id: str, action_type: str) -> None:
        self._recent_departures[(guild_id, user_id)] = (action_type, datetime.now(timezone.utc))

    def _recent_memory_departure(self, guild_id: str, user_id: str, *, window_seconds: int) -> str | None:
        key = (guild_id, user_id)
        current = self._recent_departures.get(key)
        if current is None:
            return None
        action_type, ts = current
        if (datetime.now(timezone.utc) - ts) > timedelta(seconds=window_seconds):
            self._recent_departures.pop(key, None)
            return None
        return action_type

    @staticmethod
    def _canonical_visibility_for_action(action_type: str, metadata: dict[str, Any]) -> bool:
        if "visible_in_greetings" in metadata:
            return bool(metadata["visible_in_greetings"])
        return True

    async def should_skip_leave_event(self, guild_id: str, user_id: str, *, window_seconds: int = _DEFAULT_LEAVE_DEDUPE_WINDOW_SECONDS) -> bool:
        recent_action = self._recent_memory_departure(guild_id, user_id, window_seconds=window_seconds)
        if recent_action in _EXPLICIT_DEPARTURE_TYPES:
            return True

        since_iso = (datetime.now(timezone.utc) - timedelta(seconds=window_seconds)).isoformat()
        if not hasattr(self._database, "list_recent_visible_departures"):
            return False
        rows = await self._database.list_recent_visible_departures(guild_id, user_id, since_iso)
        for row in rows:
            event_type = str(row.get("event_type_key") or "")
            if _VISIBLE_DEPARTURE_PRECEDENCE.get(event_type, 0) > _VISIBLE_DEPARTURE_PRECEDENCE["leave"]:
                return True
        return False

    async def log_action(
        self,
        *,
        guild_id: str,
        user_id: str,
        action_type: str,
        moderator_id: str | None = None,
        reason: str | None = None,
        duration_seconds: int | None = None,
        expires_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # `moderation_actions` resta l'audit raw append-only di qualunque azione
        # osservata o eseguita dal runtime; `member_flow_events` è invece la
        # timeline canonica letta dai GREETINGS per rendering, conteggi e dedupe.
        metadata_dict = dict(metadata or {})
        action_id = await self._database.log_moderation_action(
            guild_id=guild_id,
            user_id=user_id,
            moderator_id=moderator_id,
            action_type=action_type,
            reason=reason,
            duration_seconds=duration_seconds,
            expires_at=expires_at,
            metadata=metadata_dict,
        )
        source = str(metadata_dict.get("source") or "member_flow_notifications")
        operation_id = str(metadata_dict["operation_id"]) if metadata_dict.get("operation_id") else None
        visible_in_greetings = self._canonical_visibility_for_action(action_type, metadata_dict)
        should_write_canonical = True
        if action_type == "leave":
            should_write_canonical = not await self.should_skip_leave_event(guild_id, user_id)

        canonical_event: dict[str, Any] | None = None
        try:
            if should_write_canonical:
                canonical_event = await self._database.insert_member_flow_event(
                    guild_id=guild_id,
                    user_id=user_id,
                    event_type_key=action_type,
                    moderator_id=moderator_id,
                    reason=reason,
                    duration_seconds=duration_seconds,
                    expires_at=expires_at,
                    source=source,
                    source_ref=f"moderation_actions:{action_id}",
                    operation_id=operation_id,
                    visible_in_greetings=visible_in_greetings,
                    metadata={
                        **metadata_dict,
                        "raw_action_id": action_id,
                    },
                )
        except Exception:
            logger.warning("member flow event mirror failed guild=%s user=%s action=%s", guild_id, user_id, action_type, exc_info=True)
        if action_type in _EXPLICIT_DEPARTURE_TYPES and visible_in_greetings:
            self.remember_departure_action(guild_id, user_id, action_type)
        return {
            "action_id": action_id,
            "canonical_event": canonical_event,
            "canonical_written": canonical_event is not None,
            "canonical_visible": bool(canonical_event and canonical_event.get("visible_in_greetings")),
            "canonical_event_type": action_type if canonical_event is not None else None,
        }

    async def send_notification(
        self,
        *,
        guild: discord.Guild,
        user: discord.abc.User | discord.Member,
        action_type: str,
        reason: str | None = None,
        moderator: discord.abc.User | discord.Member | None = None,
        duration_seconds: int | None = None,
        expires_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
        canonical_event: dict[str, Any] | None = None,
    ) -> None:
        cfg = await self._database.get_inactivity_config(str(guild.id))
        if cfg is None:
            return
        notify_channel_id = cfg["notify_channel_id"] or cfg["atrio_channel_id"]
        if not notify_channel_id:
            return
        channel = guild.get_channel(int(notify_channel_id))
        if not isinstance(channel, discord.abc.Messageable):
            return

        created_at = datetime.now(timezone.utc)
        canonical_payload = canonical_event or self._build_fallback_canonical_event(
            action_type=action_type,
            reason=reason,
            duration_seconds=duration_seconds,
            expires_at=expires_at,
            metadata=metadata,
        )
        if not bool(canonical_payload.get("visible_in_greetings", True)):
            return
        canonical_metadata = canonical_payload.get("metadata")
        canonical_metadata_dict = dict(canonical_metadata) if isinstance(canonical_metadata, dict) else {}
        canonical_payload["metadata"] = {
            **canonical_metadata_dict,
            "notify_channel_id": str(notify_channel_id),
            "atrio_channel_id": str(cfg.get("atrio_channel_id") or ""),
            "rejoin_link": str(cfg.get("invite_url") or ""),
        }
        copy = await self._copy_service.render_canonical_event_copy(
            guild=guild,
            user=user,
            canonical_event=canonical_payload,
            moderator=moderator,
            channel_id=str(notify_channel_id),
            now=created_at,
        )
        embed = discord.Embed(title="🚪 INGRESSI & USCITE", colour=discord.Colour.blurple(), timestamp=created_at)
        # Layout canonico live: sempre e solo 3 campi, nell'ordine evento →
        # stato barcello → narrativa. I valori arrivano dalla timeline canonica.
        embed.add_field(name="Evento", value=copy.event_label, inline=True)
        embed.add_field(name=copy.status_field_name, value=copy.status_field_value[:1024], inline=True)
        embed.add_field(name=_BLANK_FIELD_NAME, value=copy.narrative[:1024], inline=False)
        attach_footer_meta(embed, service_name="member_flow_notifications", used_local_processing=True)

        files: list[discord.File] = []
        if bool(cfg["notify_card_enabled"]):
            label = "WELCOME" if action_type == "join" else "GOODBYE"
            card = await generate_member_flow_card(member=user, guild_name=guild.name, event_label=label)
            if card is not None:
                files.append(card)
        try:
            await channel.send(embed=embed, files=files or None)
        except Exception:
            logger.warning("member flow notification send failed guild=%s action=%s", guild.id, action_type, exc_info=True)

    def _build_fallback_canonical_event(
        self,
        *,
        action_type: str,
        reason: str | None,
        duration_seconds: int | None,
        expires_at: datetime | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "event_type_key": action_type,
            "reason": reason,
            "duration_seconds": duration_seconds,
            "expires_at": expires_at.isoformat() if expires_at is not None else None,
            "visible_in_greetings": True,
            "metadata": dict(metadata or {}),
        }
