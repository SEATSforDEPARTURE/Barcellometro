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
_DM_IMPORTANT_PLACEHOLDERS: frozenset[str] = frozenset(
    {
        "mention",
        "user",
        "username",
        "display_name",
        "server",
        "event_type",
        "reason",
        "reason_text",
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
    }
)


def _escape_markdown(value: str) -> str:
    escaped = str(value or "")
    for token in ("\\", "*", "_", "`", "~", "|"):
        escaped = escaped.replace(token, f"\\{token}")
    return escaped


def _to_bold_italic(value: Any) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    return f"***{_escape_markdown(clean)}***"


class _SafePlaceholderDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return ""


def _render_reason_line(reason_text: str) -> str:
    return reason_text


_AUTO_REASON_LINE_BY_REASONING: dict[str, str] = {
    "users_manual_grace_expired_tempban": "periodo di grazia manuale scaduto",
    "inactivity_grace_expired_tempban": "periodo di grazia per inattività scaduto",
}


def build_reason_line(
    *,
    reason: str | None = None,
    reasoning: str | None = None,
    event_type: str | None = None,
    event_state: str | None = None,
    event_cause: str | None = None,
) -> str:
    safe_reasoning = str(reasoning or "").strip().lower()
    if safe_reasoning in _AUTO_REASON_LINE_BY_REASONING:
        return _AUTO_REASON_LINE_BY_REASONING[safe_reasoning]
    safe_event_type = str(event_type or "").strip().lower()
    safe_event_state = str(event_state or "").strip().lower()
    safe_event_cause = str(event_cause or "").strip().lower()
    if safe_event_type == "tempban" and safe_event_state == "grace_expired" and safe_event_cause == "inactivity":
        return _AUTO_REASON_LINE_BY_REASONING["inactivity_grace_expired_tempban"]
    safe_reason = str(reason or "").strip()
    if not safe_reason:
        return ""
    return safe_reason


def _render_invite_line(invite_url: str) -> str:
    if not invite_url:
        return ""
    return f" Invite: {_to_bold_italic(invite_url)}"


def format_reason_text(reason: str | None) -> str:
    safe_reason = str(reason or "").strip()
    if not safe_reason:
        return ""
    return f"La moderazione aggiunge: {safe_reason}"


def build_dm_base_placeholder_payload(
    *,
    user: Any,
    guild: Any,
    event_type: str,
    now: datetime,
    duration_seconds: int | None = None,
    reason: str | None = None,
    reasoning: str | None = None,
    event_state: str | None = None,
    event_cause: str | None = None,
    started_at: datetime | None = None,
    expires_at: datetime | None = None,
    invite_url: str | None = None,
) -> dict[str, Any]:
    safe_reason = str(reason or "").strip()
    reason_text = format_reason_text(safe_reason)
    safe_reasoning = str(reasoning or "").strip()
    safe_invite_url = str(invite_url or "").strip()
    clean_duration_seconds = max(0, int(duration_seconds or 0))
    safe_started_at = started_at or now
    time_payload = build_time_placeholder_payload(now=now, started_at=safe_started_at, expires_at=expires_at)
    reason_line = _render_reason_line(
        build_reason_line(
            reason=safe_reason,
            reasoning=safe_reasoning,
            event_type=event_type,
            event_state=event_state,
            event_cause=event_cause,
        )
    )
    return {
        **build_user_placeholder_payload(user),
        **time_payload,
        "server": str(getattr(guild, "name", "") or ""),
        "guild_id": str(getattr(guild, "id", "") or ""),
        "event_type": str(event_type or "").strip(),
        "reason": safe_reason,
        "reason_text": reason_text,
        "reason_line": _render_reason_line(safe_reason),
        "reasoning": safe_reasoning,
        "duration_seconds": clean_duration_seconds,
        "duration_human": format_duration_human(clean_duration_seconds) or "0m",
        "invite_url": safe_invite_url,
        "invite_line": _render_invite_line(safe_invite_url),
    }


def render_dm_template(template: str, payload: dict[str, Any]) -> str:
    base = str(template or "")
    styled_payload: dict[str, Any] = {}
    for key, value in payload.items():
        if key in {"reason_line", "invite_line"}:
            styled_payload[key] = str(value or "")
            continue
        if key in _DM_IMPORTANT_PLACEHOLDERS:
            styled_payload[key] = _to_bold_italic(value)
            continue
        if isinstance(value, str):
            styled_payload[key] = _escape_markdown(value)
            continue
        styled_payload[key] = value
    safe_payload = _SafePlaceholderDict(styled_payload)
    try:
        rendered = _FORMATTER.vformat(base, (), safe_payload)
    except Exception:
        rendered = base
    clean = _UNRESOLVED_PLACEHOLDER_RE.sub("", rendered).strip()
    if not clean:
        return ""
    return f"_{clean}_"
