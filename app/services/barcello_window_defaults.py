from __future__ import annotations

from typing import Any


def resolve_window_minutes(channel_id: int | str, *, default_window: int, trigger_config: dict[str, Any]) -> int:
    resolved_default = default_window if isinstance(default_window, int) and not isinstance(default_window, bool) and default_window > 0 else 30
    overrides = trigger_config.get("channel_overrides") if isinstance(trigger_config.get("channel_overrides"), dict) else {}
    channel_cfg = overrides.get(str(channel_id)) if isinstance(overrides.get(str(channel_id)), dict) else {}
    override_window = channel_cfg.get("window_minutes")
    if isinstance(override_window, int) and not isinstance(override_window, bool) and override_window > 0:
        return override_window
    return resolved_default


def resolve_default_window_minutes(channel_id: int | str, raw_default: str | int | None, trigger_config: dict[str, Any]) -> int:
    try:
        default_window = int(raw_default) if raw_default is not None else 30
    except (TypeError, ValueError):
        default_window = 30
    if default_window <= 0:
        default_window = 30
    return resolve_window_minutes(channel_id, default_window=default_window, trigger_config=trigger_config)
