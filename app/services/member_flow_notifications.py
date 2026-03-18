from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import discord

from app.services.footer import attach_footer_meta

logger = logging.getLogger(__name__)

_DURATION_RE = re.compile(r"^\s*(\d+)\s*([dhm])\s*$", re.IGNORECASE)
_CARD_SIZE = (900, 300)


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


def build_template_context(
    *,
    user: discord.abc.User | discord.Member | Any,
    guild: discord.Guild | Any,
    moderator: discord.abc.User | discord.Member | None = None,
    reason: str | None = None,
    duration_seconds: int | None = None,
    expires_at: datetime | None = None,
    rejoin_link: str | None = None,
    days_inactive: int | None = None,
    inactivity_text: str | None = None,
) -> dict[str, Any]:
    username = getattr(user, "name", "Utente")
    display_name = getattr(user, "display_name", username)
    mention = getattr(user, "mention", f"<@{getattr(user, 'id', '0')}>")
    moderator_name = getattr(moderator, "display_name", getattr(moderator, "name", "Sistema")) if moderator else "Sistema"
    moderator_mention = getattr(moderator, "mention", moderator_name) if moderator else "Sistema"
    duration_human = format_duration_human(duration_seconds)
    duration_days = None if duration_seconds is None else max(1, int(duration_seconds // 86400))
    expires_text = ""
    if expires_at is not None:
        expires_text = expires_at.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    return {
        "user": username,
        "username": username,
        "display_name": display_name,
        "mention": mention,
        "user_id": str(getattr(user, "id", "")),
        "server": getattr(guild, "name", "Server"),
        "guild_id": str(getattr(guild, "id", "")),
        "moderator": moderator_name,
        "moderator_mention": moderator_mention,
        "reason": reason or "",
        "duration": duration_human or "",
        "duration_days": "" if duration_days is None else str(duration_days),
        "expires_at": expires_text,
        "rejoin_link": rejoin_link or "",
        "days_inactive": "" if days_inactive is None else str(days_inactive),
        "inactivity_text": inactivity_text or "",
    }


def render_moderation_template(template: str | None, **context: Any) -> str:
    base = template or ""
    try:
        return base.format(**context)
    except Exception as exc:  # noqa: BLE001
        return f"[Errore render template: {exc}]\n{base}"


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
    def __init__(self, database: Any, bot: discord.Client) -> None:
        self._database = database
        self._bot = bot
        self._recent_departures: dict[tuple[str, str], tuple[str, datetime]] = {}

    def remember_departure_action(self, guild_id: str, user_id: str, action_type: str) -> None:
        self._recent_departures[(guild_id, user_id)] = (action_type, datetime.now(timezone.utc))

    def should_skip_leave_event(self, guild_id: str, user_id: str, *, window_seconds: int = 15) -> bool:
        key = (guild_id, user_id)
        current = self._recent_departures.get(key)
        if current is None:
            return False
        _, ts = current
        if (datetime.now(timezone.utc) - ts) > timedelta(seconds=window_seconds):
            self._recent_departures.pop(key, None)
            return False
        return True

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
    ) -> None:
        await self._database.log_moderation_action(
            guild_id=guild_id,
            user_id=user_id,
            moderator_id=moderator_id,
            action_type=action_type,
            reason=reason,
            duration_seconds=duration_seconds,
            expires_at=expires_at,
            metadata=metadata or {},
        )
        if action_type in {"kick", "ban", "tempban", "inactive_kick", "inactive_tempban"}:
            self.remember_departure_action(guild_id, user_id, action_type)

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
        embed = discord.Embed(title="🚪 INGRESSI & USCITE", colour=discord.Colour.blurple(), timestamp=created_at)
        embed.add_field(name="Utente", value=getattr(user, "mention", f"<@{user.id}>"), inline=True)
        embed.add_field(name="Evento", value=action_type.replace("_", " "), inline=True)
        if reason:
            embed.add_field(name="Motivo", value=reason[:1024], inline=False)
        if duration_seconds is not None:
            embed.add_field(name="Durata", value=format_duration_human(duration_seconds) or "n/d", inline=True)
        if expires_at is not None:
            embed.add_field(name="Scadenza", value=expires_at.strftime("%d/%m/%Y %H:%M UTC"), inline=True)
        if moderator is not None:
            embed.add_field(name="Moderatore", value=getattr(moderator, "mention", moderator.display_name), inline=True)
        if metadata and metadata.get("inactivity_text"):
            embed.add_field(name="Dettaglio", value=str(metadata["inactivity_text"])[:1024], inline=False)
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
