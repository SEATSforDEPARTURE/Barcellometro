from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from string import Formatter
from typing import Any

from app.services.dm_template_placeholders import build_reason_line
from app.services.member_flow_notifications import format_duration_human

_UNRESOLVED_PLACEHOLDER_RE = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")
_FORMATTER = Formatter()


class _SafePreviewDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return ""


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def build_dm_template_preview_payload(
    *,
    duration_seconds: int = 2 * 86400,
    event_type: str = "tempban",
    reason: str = "Inactivity",
    invite_url: str = "https://discord.gg/example",
    now: datetime | None = None,
    extra_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    utc_now = now or datetime(2026, 3, 28, 16, 0, tzinfo=timezone.utc)
    safe_duration_seconds = max(0, _to_int(duration_seconds, 2 * 86400))
    expires_at = utc_now + timedelta(seconds=safe_duration_seconds)
    safe_reason = str(reason or "").strip()
    safe_event_type = str(event_type or "").strip() or "tempban"
    safe_invite_url = str(invite_url or "").strip()

    payload: dict[str, Any] = {
        "mention": "<@1234567890>",
        "user": "@ExampleUser",
        "username": "ExampleUser",
        "display_name": "Example",
        "user_id": "1234567890",
        "server": "Barcellometro",
        "guild_id": "987654321",
        "event_type": safe_event_type,
        "reason": safe_reason,
        "reason_text": safe_reason,
        "reason_line": "",
        "reasoning": "template_preview",
        "duration_seconds": safe_duration_seconds,
        "duration_human": format_duration_human(safe_duration_seconds) or "0m",
        "started_at_utc": utc_now.strftime("%Y-%m-%d %H:%M UTC"),
        "started_at_it": utc_now.astimezone(ZoneInfo("Europe/Rome")).strftime("%d/%m/%Y %H:%M"),
        "expires_at_utc": expires_at.strftime("%Y-%m-%d %H:%M UTC"),
        "expires_at_it": expires_at.astimezone(ZoneInfo("Europe/Rome")).strftime("%d/%m/%Y %H:%M"),
        "now_utc": utc_now.strftime("%Y-%m-%d %H:%M UTC"),
        "now_it": utc_now.astimezone(ZoneInfo("Europe/Rome")).strftime("%d/%m/%Y %H:%M"),
        "invite_url": safe_invite_url,
        "invite_line": f"Invite: {safe_invite_url}" if safe_invite_url else "",
        "ban_days": max(1, safe_duration_seconds // 86400) if safe_duration_seconds else 2,
    }
    if extra_payload:
        payload.update(extra_payload)
    payload["reason_line"] = build_reason_line(
        reason=str(payload.get("reason") or "").strip(),
        reasoning=str(payload.get("reasoning") or "").strip(),
        event_type=str(payload.get("event_type") or "").strip(),
        event_state=str(payload.get("event_state") or "").strip(),
        event_cause=str(payload.get("event_cause") or "").strip(),
    )
    return payload


def render_dm_template_preview(template: str, payload: dict[str, Any]) -> str:
    base = str(template or "")
    safe_payload = _SafePreviewDict({key: value for key, value in payload.items()})
    try:
        rendered = _FORMATTER.vformat(base, (), safe_payload)
    except Exception:
        rendered = base
    clean = _UNRESOLVED_PLACEHOLDER_RE.sub("", rendered)
    return clean.strip()
