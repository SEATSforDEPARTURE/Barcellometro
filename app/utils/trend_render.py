from __future__ import annotations

from typing import Any


def normalize_trend(trend_value: Any) -> tuple[str | None, int | None]:
    if isinstance(trend_value, dict):
        direction = trend_value.get("direction")
        delta_raw = trend_value.get("delta")
        try:
            delta = int(delta_raw) if delta_raw is not None else None
        except (TypeError, ValueError):
            delta = None
        return str(direction) if direction else None, delta
    if isinstance(trend_value, str):
        value = trend_value.strip().lower()
        mapping = {
            "stable": "stable",
            "stabile": "stable",
            "improving": "improving",
            "miglioramento": "improving",
            "in miglioramento": "improving",
            "worsening": "worsening",
            "peggioramento": "worsening",
            "in peggioramento": "worsening",
        }
        return mapping.get(value, None), None
    return None, None


def render_trend(direction: str | None, delta: int | None) -> str:
    if direction == "improving":
        base = "In miglioramento."
    elif direction == "worsening":
        base = "In peggioramento."
    else:
        base = "Stabile."
    if delta is None:
        return base
    return f"{base} (Δ {delta:+d})."


def render_trend_value(trend: dict[str, Any] | str | None) -> str:
    direction, delta = normalize_trend(trend)
    return render_trend(direction, delta)
