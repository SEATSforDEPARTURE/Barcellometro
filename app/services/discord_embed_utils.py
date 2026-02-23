from __future__ import annotations

import discord

FIELD_MAX = 1024
DESC_MAX = 4096


def truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def safe_add_field(embed: discord.Embed, *, name: str, value: str, inline: bool = False) -> None:
    embed.add_field(name=name, value=truncate(value, FIELD_MAX), inline=inline)


def safe_set_description(embed: discord.Embed, desc: str) -> None:
    embed.description = truncate(desc, DESC_MAX)
