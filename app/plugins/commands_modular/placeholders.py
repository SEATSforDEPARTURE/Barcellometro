from __future__ import annotations

from app.services.inactivity_dm_templates import INACTIVITY_DM_SUPPORTED_PLACEHOLDERS


def describe_placeholders() -> str:
    placeholders = ", ".join(f"{{{name}}}" for name in INACTIVITY_DM_SUPPORTED_PLACEHOLDERS)
    return f"Placeholder: {placeholders}."
