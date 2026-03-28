from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import discord

from app.services.dm_time_placeholders import build_time_placeholder_payload
from app.services.dm_user_placeholders import build_user_placeholder_payload

INACTIVITY_DM_SUPPORTED_PLACEHOLDERS: tuple[str, ...] = (
    "mention",
    "user",
    "username",
    "display_name",
    "user_id",
    "server",
    "guild_id",
    "days_inactive",
    "window_days",
    "min_messages",
    "message_count",
    "grace_days",
    "reminder_count",
    "ban_days",
    "rejoin_link",
    "reason",
    "inactivity_text",
    "now_utc",
    "now_it",
    "expires_at_utc",
    "expires_at_it",
)


def build_inactivity_dm_template_payload(
    *,
    member: discord.Member,
    guild: discord.Guild,
    days_inactive: int,
    policy: dict[str, Any],
    cfg: dict[str, Any],
    message_count: int | None = None,
    reminder_count: int | None = None,
    reason: str | None = None,
    inactivity_text: str | None = None,
    now: datetime | None = None,
    expires_at: datetime | None = None,
) -> dict[str, Any]:
    time_payload = build_time_placeholder_payload(now=now or datetime.now(timezone.utc), expires_at=expires_at)
    return {
        **build_user_placeholder_payload(member),
        **time_payload,
        "username": member.display_name,
        "display_name": member.display_name,
        "server": guild.name,
        "guild_id": guild.id,
        "days_inactive": days_inactive,
        "window_days": policy.get("window_days", 30),
        "min_messages": policy.get("min_messages", 1),
        "message_count": message_count if message_count is not None else 0,
        "grace_days": cfg.get("grace_days_after_reminder", 7),
        "reminder_count": reminder_count if reminder_count is not None else 0,
        "ban_days": cfg.get("ban_days", 7),
        "rejoin_link": cfg.get("invite_url") or "",
        "reason": reason or "",
        "inactivity_text": inactivity_text or f"è stato inattivo per {days_inactive} giorni",
    }
