from __future__ import annotations

import re
import unicodedata
from typing import Any

import discord


_EMOJI_BLOCKS: tuple[tuple[int, int], ...] = (
    (0x1F1E6, 0x1F1FF),
    (0x1F300, 0x1FAFF),
    (0x2600, 0x27BF),
    (0xFE00, 0xFE0F),
)


def _is_emoji_char(ch: str) -> bool:
    codepoint = ord(ch)
    if any(start <= codepoint <= end for start, end in _EMOJI_BLOCKS):
        return True
    return unicodedata.category(ch) in {"So", "Sk"}


def clean_embed_display_name(raw_name: Any, *, fallback: str = "utente") -> str:
    raw = str(raw_name or "").strip()
    if not raw:
        return fallback

    no_emoji = "".join(ch for ch in raw if not _is_emoji_char(ch))
    no_markdown_tokens = no_emoji.replace("*", "").replace("`", "")
    collapsed = re.sub(r"\s+", " ", no_markdown_tokens).strip()
    cleaned = re.sub(r"^[\W_]+", "", collapsed, flags=re.UNICODE)
    cleaned = re.sub(r"[\W_]+$", "", cleaned, flags=re.UNICODE).strip()

    candidate = cleaned or raw.strip() or fallback
    return discord.utils.escape_markdown(candidate)


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
