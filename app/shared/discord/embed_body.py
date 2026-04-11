from __future__ import annotations

from dataclasses import dataclass
import re

import discord

from app.shared.discord.user_display import clean_embed_display_name

DISCORD_TITLE_MAX = 256
DISCORD_DESCRIPTION_MAX = 4096
DISCORD_FIELD_NAME_MAX = 256
DISCORD_FIELD_VALUE_MAX = 1024


_CANONICAL_EMBED_HEADING_RE = re.compile(r"^(?:(?P<emoji>\S+)\s+)?__\*\*(?P<body>.+?)\*\*__$")


def _extract_canonical_heading(value: str) -> tuple[str, str | None]:
    raw = str(value or "").strip()
    if not raw:
        return "", None
    match = _CANONICAL_EMBED_HEADING_RE.fullmatch(raw)
    if not match:
        return raw, None
    return match.group("body").strip(), match.group("emoji")


def _extract_single_italic(value: str) -> str:
    raw = str(value or "").strip()
    match = re.fullmatch(r"\*(?!\*)(.+?)(?<!\*)\*", raw, flags=re.DOTALL)
    if not match:
        return raw
    return match.group(1).strip()


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
    base, detected_emoji = _extract_canonical_heading(text)
    rendered = base.upper()
    active_emoji = emoji or detected_emoji
    if active_emoji:
        rendered = f"{active_emoji} __**{rendered}**__"
    else:
        rendered = f"__**{rendered}**__"
    return _truncate(rendered, DISCORD_TITLE_MAX)


def build_server_summary_title(section: str) -> str:
    normalized_section = str(section or "").strip().upper()
    return format_standard_title(f"RESOCONTO SERVER · {normalized_section}", emoji="🗣️")


def build_user_event_title(*, event_text: str, display_name: str, emoji: str) -> str:
    cleaned_name = clean_embed_display_name(display_name)
    return format_standard_title(f'"{cleaned_name}" {event_text}', emoji=emoji)


def format_standard_description(text: str, *, italic: bool = True, blank_line_before_fields: bool = False) -> str:
    """Render the canonical intro-only embed description.

    Definitive contract: description is a short italic introduction, never the
    structural container for key sections (which must be Discord fields).
    """
    base = _extract_single_italic(text) if italic else (text or "").strip()
    rendered = f"*{base}*" if italic and base else base
    if blank_line_before_fields and rendered and not rendered.endswith("\n\n"):
        rendered = f"{rendered}\n\n"
    return _truncate(rendered, DISCORD_DESCRIPTION_MAX)


def format_standard_field_name(text: str, *, emoji: str | None = None) -> str:
    """Render canonical embed field names as `(emoji) __**UPPERCASE**__`."""
    base, detected_emoji = _extract_canonical_heading(text)
    normalized = base.upper()
    active_emoji = emoji or detected_emoji
    if active_emoji:
        rendered = f"{active_emoji} __**{normalized}**__"
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
