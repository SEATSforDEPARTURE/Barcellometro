from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import json
from typing import Any, Literal

import discord

from app.services.footer import attach_minimal_footer, FooterService

CommandKind = Literal["info", "success", "warning", "error"]

TOP_LEVEL_EMOJIS: dict[str, str] = {
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


def build_section(title: str, lines: Sequence[tuple[str, Any]] | Sequence[str], emoji: str | None = None, *, kind: CommandKind = "info") -> str:
    header_emoji = emoji or get_section_emoji(title, kind=kind)
    rendered = [f"**{header_emoji} {title.upper()}**"]
    for line in lines:
        if isinstance(line, str):
            rendered.append(line)
        else:
            rendered.append(format_bullet(line[0], line[1]))
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
) -> list[discord.Embed]:
    title = f"{top_level_emoji or get_command_emoji(top_level)} {str(top_level).upper()}"
    sub_emoji = subcommand_emoji or get_section_emoji(subcommand_path.split()[-1] if subcommand_path else None, kind=kind)
    blocks: list[str] = [f"**{sub_emoji} {normalize_command_path(subcommand_path)}**"]
    for label, value in lines or []:
        blocks.append(format_bullet(label, value))
    for section in sections or []:
        if isinstance(section, dict):
            item = CommandEmbedSection(
                title=str(section.get("title") or "Section"),
                lines=list(section.get("lines") or []),
                emoji=section.get("emoji"),
            )
        else:
            item = section
        blocks.append(build_section(item.title, item.lines, item.emoji, kind=kind))

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
        attach_minimal_footer(embed, text=brand_text)
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
    if interaction.response.is_done():
        await interaction.followup.send(content=content, embed=first, ephemeral=ephemeral, files=files)
    else:
        await interaction.response.send_message(content=content, embed=first, ephemeral=ephemeral, files=files)
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
) -> None:
    embeds = await build_command_embeds(
        top_level=top_level,
        subcommand_path=subcommand_path,
        lines=lines,
        sections=sections,
        kind=kind,
        footer_service=footer_service,
    )
    await send_command_embeds(interaction, embeds=embeds, ephemeral=ephemeral, files=files)
