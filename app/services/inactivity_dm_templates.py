from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import discord

from app.services.dm_template_placeholders import DM_BASE_SUPPORTED_PLACEHOLDERS, build_dm_base_placeholder_payload

INACTIVITY_DM_SUPPORTED_PLACEHOLDERS: tuple[str, ...] = (
    *DM_BASE_SUPPORTED_PLACEHOLDERS,
    "days_inactive",
    "window_days",
    "min_messages",
    "message_count",
    "grace_days",
    "reminder_count",
    "ban_days",
    "rejoin_link",
    "inactivity_text",
    "event_state",
    "event_cause",
)


def build_inactivity_dm_template_payload(
    *,
    member: discord.Member,
    guild: discord.Guild,
    event_type: str,
    days_inactive: int,
    policy: dict[str, Any],
    cfg: dict[str, Any],
    message_count: int | None = None,
    reminder_count: int | None = None,
    reason: str | None = None,
    reasoning: str | None = None,
    inactivity_text: str | None = None,
    event_state: str | None = None,
    event_cause: str | None = None,
    duration_seconds: int | None = None,
    now: datetime | None = None,
    started_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> dict[str, Any]:
    utc_now = now or datetime.now(timezone.utc)
    safe_event_type = str(event_type or "").strip() or "inactivity"
    invite_url = str(cfg.get("invite_url") or "").strip()
    base_payload = build_dm_base_placeholder_payload(
        user=member,
        guild=guild,
        event_type=safe_event_type,
        now=utc_now,
        duration_seconds=duration_seconds,
        reason=reason,
        reasoning=reasoning,
        started_at=started_at or utc_now,
        expires_at=expires_at,
        invite_url=invite_url,
    )
    return {
        **base_payload,
        "days_inactive": days_inactive,
        "window_days": int(policy.get("window_days", 30) or 30),
        "min_messages": int(policy.get("min_messages", 1) or 1),
        "message_count": message_count if message_count is not None else 0,
        "grace_days": int(cfg.get("grace_days_after_reminder", 7) or 7),
        "reminder_count": reminder_count if reminder_count is not None else 0,
        "ban_days": int(cfg.get("ban_days", 7) or 7),
        "rejoin_link": invite_url,
        "inactivity_text": inactivity_text or f"è stato inattivo per {days_inactive} giorni",
        "event_state": str(event_state or ""),
        "event_cause": str(event_cause or ""),
    }
