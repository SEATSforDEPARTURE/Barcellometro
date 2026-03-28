from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROME_TZ = ZoneInfo("Europe/Rome")


def _format_utc(dt: datetime | None) -> str:
    if dt is None:
        return "n/a"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _format_it(dt: datetime | None) -> str:
    if dt is None:
        return "n/a"
    return dt.astimezone(ROME_TZ).strftime("%d/%m/%Y %H:%M")


def build_time_placeholder_payload(*, now: datetime, expires_at: datetime | None = None) -> dict[str, str]:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return {
        "now_utc": _format_utc(now),
        "now_it": _format_it(now),
        "expires_at_utc": _format_utc(expires_at),
        "expires_at_it": _format_it(expires_at),
    }
