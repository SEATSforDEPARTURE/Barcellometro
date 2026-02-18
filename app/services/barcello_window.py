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
