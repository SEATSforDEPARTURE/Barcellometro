from __future__ import annotations

from dataclasses import dataclass

import discord

DISCORD_TITLE_MAX = 256
DISCORD_DESCRIPTION_MAX = 4096
DISCORD_FIELD_NAME_MAX = 256
DISCORD_FIELD_VALUE_MAX = 1024


def _truncate(value: str, max_len: int) -> str:
    text = value or ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def format_standard_title(text: str, *, emoji: str | None = None, uppercase: bool = True) -> str:
    """Render canonical embed titles as `(emoji) __**UPPERCASE**__`.

    Note: `uppercase` is kept for backward compatibility with legacy call sites,
    but the definitive standard is always uppercase.
    """
    base = (text or "").strip()
    rendered = base.upper()
    if emoji:
        rendered = f"{emoji} __**{rendered}**__"
    else:
        rendered = f"__**{rendered}**__"
    return _truncate(rendered, DISCORD_TITLE_MAX)


def format_standard_description(text: str, *, italic: bool = True, blank_line_before_fields: bool = False) -> str:
    """Render the canonical intro-only embed description.

    Definitive contract: description is a short italic introduction, never the
    structural container for key sections (which must be Discord fields).
    """
    base = (text or "").strip()
    rendered = f"*{base}*" if italic and base else base
    if blank_line_before_fields and rendered and not rendered.endswith("\n\n"):
        rendered = f"{rendered}\n\n"
    return _truncate(rendered, DISCORD_DESCRIPTION_MAX)


def format_standard_field_name(text: str, *, emoji: str | None = None) -> str:
    """Render canonical embed field names as `(emoji) __**UPPERCASE**__`."""
    base = (text or "").strip()
    normalized = base.upper()
    if emoji:
        rendered = f"{emoji} __**{normalized}**__"
    else:
        rendered = f"__**{normalized}**__"
    return _truncate(rendered, DISCORD_FIELD_NAME_MAX)


def format_standard_section_value(text: str) -> str:
    """Render canonical field body text and enforce Discord field limits."""
    return _truncate((text or "").strip() or "—", DISCORD_FIELD_VALUE_MAX)


@dataclass(slots=True)
class BodyFormatOptions:
    title_emoji: str | None = None
    title_uppercase: bool = True
    description_italic: bool = True
    blank_line_before_fields: bool = False
    format_field_names: bool = False


def apply_standard_body_helpers(embed: discord.Embed, *, options: BodyFormatOptions) -> discord.Embed:
    """Apply the definitive body contract.

    Enforces: uppercase title/field names in canonical markdown format and a
    short intro-only description. Structural sections belong to fields.
    """
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
