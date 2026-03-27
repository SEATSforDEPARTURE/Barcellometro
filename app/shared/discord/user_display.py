from __future__ import annotations

from typing import Any

import discord


def format_user_display_name(user: Any, *, fallback: str = "utente") -> str:
    """Return a safe visual label for UI text without Discord mentions."""
    raw_name = (
        getattr(user, "display_name", None)
        or getattr(user, "global_name", None)
        or getattr(user, "name", None)
        or fallback
    )
    cleaned = str(raw_name or fallback).strip() or fallback
    return discord.utils.escape_markdown(cleaned)
