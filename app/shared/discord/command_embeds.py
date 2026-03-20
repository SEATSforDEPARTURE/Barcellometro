from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
import json
from typing import Any, Literal

import discord

from app.services.footer import attach_footer_meta, attach_minimal_footer, FooterService

CommandKind = Literal["info", "success", "warning", "error"]
FooterMode = Literal["minimal", "meta", "none"]

TOP_LEVEL_EMOJIS: dict[str, str] = {
    "admin": "🫛",
    "bm": "🫛",
    "status": "📊",
    "ai": "🧠",
    "retention": "🗂️",
    "backfill": "♻️",
    "events": "📡",
    "triggers": "⚡",
    "audio_notes": "🎙️",
    "audionotes": "🎙️",
    "voice_ingest": "🎧",
    "privacy": "🔒",
    "roles": "👥",
    "settings": "⚙️",
    "attivita": "📈",
    "aura": "✨",
    "barcello": "❤️",
    "resoconto": "📓",
    "riassunto": "🗒️",
    "moderazione": "🛠️",
    "moderazione_utenti": "🛠️",
    "inattivi": "🛠️",
    "commandguard": "👥",
    "footer": "🧾",
    "ask": "❓",
    "domanda": "❓",
}

SECTION_EMOJIS: dict[str, str] = {
    "info": "🛠️",
    "status": "🛠️",
    "show": "🛠️",
    "config": "⚙️",
    "success": "✅",
    "result": "✅",
    "error": "❌",
    "warning": "⚠️",
    "metrics": "📊",
    "primary": "🧠",
    "fallback": "🛟",
    "last usage": "📊",
    "last run": "📊",
    "templates": "🧩",
    "channel": "📣",
    "details": "📋",
}

KIND_EMOJIS: dict[CommandKind, str] = {
    "info": "🛠️",
    "success": "✅",
    "warning": "⚠️",
    "error": "❌",
}

KIND_COLORS: dict[CommandKind, int] = {
    "info": 0x5865F2,
    "success": 0x57F287,
    "warning": 0xFEE75C,
    "error": 0xED4245,
}


@dataclass(slots=True)
class CommandEmbedSection:
    title: str
    lines: list[tuple[str, Any]]
    emoji: str | None = None


_MAX_DESCRIPTION = 3800


def humanize_key(key: str) -> str:
    parts = str(key).replace(".", " ").replace("_", " ").replace("-", " ").split()
    if not parts:
        return "Value"
    human = " ".join(parts)
    for source, target in {
        "db": "DB",
        "id": "ID",
        "ids": "IDs",
        "ai": "AI",
        "qna": "QnA",
        "dm": "DM",
        "url": "URL",
        "ts": "TS",
    }.items():
        human = human.replace(source.title(), target)
    return human.title().replace("Qna", "QnA")


def normalize_command_path(*parts: str | None) -> str:
    values = [str(part).strip() for part in parts if part and str(part).strip()]
    return " ".join(values).upper()


def get_command_emoji(command: str | None) -> str:
    key = str(command or "").strip().lower()
    return TOP_LEVEL_EMOJIS.get(key, "🫛")


def get_section_emoji(title: str | None, *, kind: CommandKind = "info") -> str:
    key = str(title or "").strip().lower()
    return SECTION_EMOJIS.get(key, KIND_EMOJIS[kind])


def get_semantic_color(kind: CommandKind) -> int:
    return KIND_COLORS[kind]


def stringify_value(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    if isinstance(value, (list, dict, tuple, set)):
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except TypeError:
            return str(value)
    return str(value)


def format_bullet(label: str, value: Any) -> str:
    return f"• {humanize_key(label)}: **{stringify_value(value)}**"


def build_section(
    title: str,
    lines: Sequence[tuple[str, Any]] | Sequence[str],
    emoji: str | None = None,
    *,
    kind: CommandKind = "info",
    line_formatter: Callable[[str, Any], str] | None = None,
) -> str:
    header_emoji = emoji or get_section_emoji(title, kind=kind)
    rendered = [f"**{header_emoji} {title.upper()}**"]
    for line in lines:
        if isinstance(line, str):
            rendered.append(line)
        else:
            rendered.append((line_formatter or format_bullet)(line[0], line[1]))
    return "\n".join(rendered)


async def _resolve_brand_text(footer_service: FooterService | None) -> str:
    if footer_service is None:
        return "Barcellometro"
    version = await footer_service.get_version()
    return f"Barcellometro {version}" if version else "Barcellometro"


async def build_command_embeds(
    *,
    top_level: str,
    subcommand_path: str,
    lines: Sequence[tuple[str, Any]] | None = None,
    sections: Sequence[CommandEmbedSection | dict[str, Any]] | None = None,
    kind: CommandKind = "info",
    top_level_emoji: str | None = None,
    subcommand_emoji: str | None = None,
    footer_service: FooterService | None = None,
    footer_mode: FooterMode = "minimal",
    footer_service_name: str | None = None,
    compact_lines: bool = False,
    line_formatter: Callable[[str, Any], str] | None = None,
    section_title_formatter: Callable[[str], str] | None = None,
) -> list[discord.Embed]:
    title = f"{top_level_emoji or get_command_emoji(top_level)} {str(top_level).upper()}"
    sub_emoji = subcommand_emoji or get_section_emoji(subcommand_path.split()[-1] if subcommand_path else None, kind=kind)
    blocks: list[str] = []
    header = f"**{sub_emoji} {normalize_command_path(subcommand_path)}**"
    rendered_lines = [(line_formatter or format_bullet)(label, value) for label, value in lines or []]
    if compact_lines and rendered_lines:
        blocks.append("\n".join([header, *rendered_lines]))
    else:
        blocks.append(header)
        blocks.extend(rendered_lines)
    for section in sections or []:
        if isinstance(section, dict):
            item = CommandEmbedSection(
                title=str(section.get("title") or "Section"),
                lines=list(section.get("lines") or []),
                emoji=section.get("emoji"),
            )
        else:
            item = section
        section_title = (section_title_formatter or str)(item.title)
        blocks.append(build_section(section_title, item.lines, item.emoji, kind=kind, line_formatter=line_formatter))

    chunks: list[str] = []
    current = ""
    for block in blocks:
        candidate = block if not current else f"{current}\n\n{block}"
        if len(candidate) <= _MAX_DESCRIPTION:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(block) <= _MAX_DESCRIPTION:
            current = block
            continue
        lines_split = block.splitlines()
        current = ""
        for line in lines_split:
            candidate_line = line if not current else f"{current}\n{line}"
            if len(candidate_line) <= _MAX_DESCRIPTION:
                current = candidate_line
            else:
                if current:
                    chunks.append(current)
                current = line[:_MAX_DESCRIPTION]
        
    if current:
        chunks.append(current)

    brand_text = await _resolve_brand_text(footer_service)
    embeds: list[discord.Embed] = []
    color = get_semantic_color(kind)
    for chunk in chunks or [blocks[0]]:
        embed = discord.Embed(title=title, description=chunk, color=color)
        if footer_mode == "minimal":
            attach_minimal_footer(embed, text=brand_text)
        elif footer_mode == "meta":
            attach_footer_meta(
                embed,
                service_name=footer_service_name or "status",
                used_local_processing=True,
                minimal=True,
            )
        embeds.append(embed)
    return embeds


async def build_command_embed(**kwargs: Any) -> discord.Embed:
    embeds = await build_command_embeds(**kwargs)
    return embeds[0]


async def send_command_embed(
    interaction: discord.Interaction,
    *,
    embed: discord.Embed,
    ephemeral: bool = True,
    content: str | None = None,
) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(content=content, embed=embed, ephemeral=ephemeral)


async def send_command_embeds(
    interaction: discord.Interaction,
    *,
    embeds: Iterable[discord.Embed],
    ephemeral: bool = True,
    content: str | None = None,
    files: list[discord.File] | None = None,
) -> None:
    embed_list = list(embeds)
    if not embed_list:
        return
    first = embed_list[0]
    extras = embed_list[1:]
    kwargs: dict[str, Any] = {
        "content": content,
        "embed": first,
        "ephemeral": ephemeral,
    }
    if files:
        kwargs["files"] = files
    if interaction.response.is_done():
        await interaction.followup.send(**kwargs)
    else:
        await interaction.response.send_message(**kwargs)
    for extra in extras:
        await interaction.followup.send(embed=extra, ephemeral=ephemeral)


async def send_standard_response(
    interaction: discord.Interaction,
    *,
    top_level: str,
    subcommand_path: str,
    lines: Sequence[tuple[str, Any]] | None = None,
    sections: Sequence[CommandEmbedSection | dict[str, Any]] | None = None,
    kind: CommandKind = "info",
    footer_service: FooterService | None = None,
    ephemeral: bool = True,
    files: list[discord.File] | None = None,
    footer_mode: FooterMode = "minimal",
    footer_service_name: str | None = None,
    compact_lines: bool = False,
    line_formatter: Callable[[str, Any], str] | None = None,
    section_title_formatter: Callable[[str], str] | None = None,
    top_level_emoji: str | None = None,
    subcommand_emoji: str | None = None,
) -> None:
    embeds = await build_command_embeds(
        top_level=top_level,
        subcommand_path=subcommand_path,
        lines=lines,
        sections=sections,
        kind=kind,
        footer_service=footer_service,
        footer_mode=footer_mode,
        footer_service_name=footer_service_name,
        compact_lines=compact_lines,
        line_formatter=line_formatter,
        section_title_formatter=section_title_formatter,
        top_level_emoji=top_level_emoji,
        subcommand_emoji=subcommand_emoji,
    )
    await send_command_embeds(interaction, embeds=embeds, ephemeral=ephemeral, files=files)


_LEGACY_TOP_LEVEL_EMOJIS: dict[str, str] = {
    "admin": "🧭",
    "bm": "🧭",
}

_LEGACY_CONTEXT_EMOJIS: dict[str, str] = {
    "status": "📊",
    "events": "📡",
    "retention": "🗃️",
    "backfill": "♻️",
    "ai": "🧠",
    "audionotes": "🎙️",
    "voice_ingest": "🎤",
    "footer": "🧩",
    "config": "⚙️",
    "run": "▶️",
    "error": "❌",
    "warning": "⚠️",
    "success": "✅",
    "info": "ℹ️",
}


def _legacy_display_value(value: object) -> str:
    if isinstance(value, bool):
        return "On" if value else "Off"
    if value is None:
        return "(n/a)"
    text = str(value).strip()
    return text or "(empty)"


def _legacy_format_bullet(label: str, value: Any) -> str:
    normalized = str(label).replace("_", " ").replace("-", " ").strip().title()
    return f"• {normalized}: **{_legacy_display_value(value)}**"


def _legacy_section_title(section_key: str) -> str:
    return str(section_key).replace("_", " ").replace("-", " ").upper()


def _legacy_context_emoji(path_parts: Sequence[str], tone: CommandKind) -> str:
    for key in reversed(path_parts):
        if key in _LEGACY_CONTEXT_EMOJIS:
            return _LEGACY_CONTEXT_EMOJIS[key]
    return _LEGACY_CONTEXT_EMOJIS.get(tone, "ℹ️")


async def send_legacy_standard_response(
    interaction: discord.Interaction,
    *,
    top_level: str,
    path_parts: Sequence[str],
    entries: Iterable[tuple[str, object]],
    tone: CommandKind = "info",
    sections: Sequence[tuple[str, Sequence[tuple[str, object]]]] | None = None,
    service_name: str = "status",
    ephemeral: bool = True,
) -> None:
    normalized_path = [part.strip().lower() for part in path_parts if part and part.strip()]
    subcommand_path = " ".join(part.replace("-", " ").upper() for part in normalized_path) or top_level.strip().upper()
    context_emoji = _legacy_context_emoji(normalized_path, tone)
    legacy_sections = [
        CommandEmbedSection(
            title=_legacy_section_title(section_name),
            lines=list(section_entries),
            emoji=context_emoji,
        )
        for section_name, section_entries in sections or ()
        if section_entries
    ]
    await send_standard_response(
        interaction,
        top_level=top_level,
        subcommand_path=subcommand_path,
        lines=list(entries),
        sections=legacy_sections,
        kind=tone,
        ephemeral=ephemeral,
        compact_lines=True,
        line_formatter=_legacy_format_bullet,
        footer_mode="meta",
        footer_service_name=service_name,
        top_level_emoji=_LEGACY_TOP_LEVEL_EMOJIS.get(top_level.strip().lower(), "🧭"),
        subcommand_emoji=context_emoji,
    )
