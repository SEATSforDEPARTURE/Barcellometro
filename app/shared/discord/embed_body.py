from __future__ import annotations

from dataclasses import dataclass

import discord

DISCORD_TITLE_MAX = 256
DISCORD_DESCRIPTION_MAX = 4096
DISCORD_FIELD_NAME_MAX = 256


def _truncate(value: str, max_len: int) -> str:
    text = value or ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def format_standard_title(text: str, *, emoji: str | None = None, uppercase: bool = True) -> str:
    base = (text or "").strip()
    rendered = base.upper()
    if emoji:
        rendered = f"{emoji} __**{rendered}**__"
    else:
        rendered = f"__**{rendered}**__"
    return _truncate(rendered, DISCORD_TITLE_MAX)


def format_standard_description(text: str, *, italic: bool = True, blank_line_before_fields: bool = False) -> str:
    base = (text or "").strip()
    rendered = f"*{base}*" if italic and base else base
    if blank_line_before_fields and rendered and not rendered.endswith("\n\n"):
        rendered = f"{rendered}\n\n"
    return _truncate(rendered, DISCORD_DESCRIPTION_MAX)


def format_standard_field_name(text: str, *, emoji: str | None = None) -> str:
    base = (text or "").strip()
    normalized = base.upper()
    if emoji:
        rendered = f"{emoji} __**{normalized}**__"
    else:
        rendered = f"__**{normalized}**__"
    return _truncate(rendered, DISCORD_FIELD_NAME_MAX)


@dataclass(slots=True)
class BodyFormatOptions:
    title_emoji: str | None = None
    title_uppercase: bool = True
    description_italic: bool = False
    blank_line_before_fields: bool = False
    format_field_names: bool = False


def apply_standard_body_helpers(embed: discord.Embed, *, options: BodyFormatOptions) -> discord.Embed:
    if embed.title:
        embed.title = format_standard_title(embed.title, emoji=options.title_emoji, uppercase=options.title_uppercase)
    if embed.description:
        embed.description = format_standard_description(
            embed.description,
            italic=options.description_italic,
            blank_line_before_fields=options.blank_line_before_fields and bool(embed.fields),
        )
    if options.format_field_names and embed.fields:
        for index, field in enumerate(list(embed.fields)):
            embed.set_field_at(
                index,
                name=format_standard_field_name(str(field.name)),
                value=str(field.value),
                inline=bool(field.inline),
            )
    return embed
