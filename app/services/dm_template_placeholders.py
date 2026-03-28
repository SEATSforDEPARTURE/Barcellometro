from __future__ import annotations

import re
from datetime import datetime
from string import Formatter
from typing import Any

from app.services.dm_time_placeholders import build_time_placeholder_payload
from app.services.dm_user_placeholders import build_user_placeholder_payload
from app.services.member_flow_notifications import format_duration_human

DM_BASE_SUPPORTED_PLACEHOLDERS: tuple[str, ...] = (
    "mention",
    "user",
    "username",
    "display_name",
    "user_id",
    "server",
    "guild_id",
    "event_type",
    "reason",
    "reason_text",
    "reason_line",
    "reasoning",
    "duration_seconds",
    "duration_human",
    "started_at_utc",
    "started_at_it",
    "expires_at_utc",
    "expires_at_it",
    "now_utc",
    "now_it",
    "invite_url",
    "invite_line",
)

_UNRESOLVED_PLACEHOLDER_RE = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")
_FORMATTER = Formatter()


class _SafePlaceholderDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return ""


def _render_reason_line(reason_text: str) -> str:
    if not reason_text:
        return ""
    return f"Reason: {reason_text}. "


def _render_invite_line(invite_url: str) -> str:
    if not invite_url:
        return ""
    return f"Invite: {invite_url}"


def build_dm_base_placeholder_payload(
    *,
    user: Any,
    guild: Any,
    event_type: str,
    now: datetime,
    duration_seconds: int | None = None,
    reason: str | None = None,
    reasoning: str | None = None,
    started_at: datetime | None = None,
    expires_at: datetime | None = None,
    invite_url: str | None = None,
) -> dict[str, Any]:
    safe_reason = str(reason or "").strip()
    safe_reasoning = str(reasoning or "").strip()
    safe_invite_url = str(invite_url or "").strip()
    clean_duration_seconds = max(0, int(duration_seconds or 0))
    safe_started_at = started_at or now
    time_payload = build_time_placeholder_payload(now=now, started_at=safe_started_at, expires_at=expires_at)
    return {
        **build_user_placeholder_payload(user),
        **time_payload,
        "server": str(getattr(guild, "name", "") or ""),
        "guild_id": str(getattr(guild, "id", "") or ""),
        "event_type": str(event_type or "").strip(),
        "reason": safe_reason,
        "reason_text": safe_reason,
        "reason_line": _render_reason_line(safe_reason),
        "reasoning": safe_reasoning,
        "duration_seconds": clean_duration_seconds,
        "duration_human": format_duration_human(clean_duration_seconds) or "0m",
        "invite_url": safe_invite_url,
        "invite_line": _render_invite_line(safe_invite_url),
    }


def render_dm_template(template: str, payload: dict[str, Any]) -> str:
    base = str(template or "")
    safe_payload = _SafePlaceholderDict(payload)
    try:
        rendered = _FORMATTER.vformat(base, (), safe_payload)
    except Exception:
        rendered = base
    return _UNRESOLVED_PLACEHOLDER_RE.sub("", rendered)
