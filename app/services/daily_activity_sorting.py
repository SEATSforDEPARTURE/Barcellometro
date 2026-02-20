from __future__ import annotations

from datetime import datetime
from typing import Any


def sort_channels_like_discord(channels: list[Any]) -> list[Any]:
    inf = 10**9

    def _key(channel: Any) -> tuple[int, int, int, int]:
        category = getattr(channel, "category", None)
        channel_pos = int(getattr(channel, "position", 0))
        channel_id = int(getattr(channel, "id", 0))
        if category is None:
            return (inf, 0, channel_pos, channel_id)
        return (
            int(getattr(category, "position", inf)),
            int(getattr(category, "id", 0)),
            channel_pos,
            channel_id,
        )

    return sorted(channels, key=_key)


def sort_inactive_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _timestamp(value: Any) -> float | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except Exception:
            return None

    def _key(item: dict[str, Any]) -> tuple[int, float, str, int]:
        ts = _timestamp(item.get("last_message_ts"))
        display = str(item.get("display_name") or "").casefold()
        user_id = int(item.get("user_id") or 0)
        return (0 if ts is not None else 1, -(ts or 0.0), display, user_id)

    return sorted(entries, key=_key)
