from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence

import discord
from discord import app_commands

from app.services.footer import attach_footer_meta


TOP_LEVEL_EMOJI: dict[str, str] = {
    "bm": "🧭",
}

CONTEXT_EMOJI: dict[str, str] = {
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

STATUS_COLOR_MAP: dict[str, discord.Colour] = {
    "info": discord.Colour.blurple(),
    "success": discord.Colour.green(),
    "warning": discord.Colour.orange(),
    "error": discord.Colour.red(),
}


def _humanize_token(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").strip().title()


def _display_value(value: object) -> str:
    if isinstance(value, bool):
        return "On" if value else "Off"
    if value is None:
        return "(n/a)"
    text = str(value).strip()
    return text or "(empty)"


def _normalize_label(label: str) -> str:
    return _humanize_token(label)


def _section_title(section_key: str) -> str:
    return section_key.replace("_", " ").replace("-", " ").upper()


def _context_emoji(path_parts: Sequence[str], tone: str) -> str:
    for key in reversed(path_parts):
        if key in CONTEXT_EMOJI:
            return CONTEXT_EMOJI[key]
    return CONTEXT_EMOJI.get(tone, "ℹ️")


def build_standard_command_embed(
    *,
    top_level: str,
    path_parts: Sequence[str],
    entries: Iterable[tuple[str, object]],
    tone: str = "info",
    sections: Sequence[tuple[str, Sequence[tuple[str, object]]]] | None = None,
    service_name: str = "status",
) -> discord.Embed:
    top_level_key = top_level.strip().lower()
    normalized_path = [part.strip().lower() for part in path_parts if part and part.strip()]
    top_level_label = top_level.strip().upper()
    path_label = " ".join(part.replace("-", " ").upper() for part in normalized_path) or top_level_label
    top_emoji = TOP_LEVEL_EMOJI.get(top_level_key, "🧭")
    context_emoji = _context_emoji(normalized_path, tone)

    body_lines = [f"• {_normalize_label(label)}: **{_display_value(value)}**" for label, value in entries]
    description_parts = [f"**{context_emoji} {path_label}**"]
    if body_lines:
        description_parts.append("\n".join(body_lines))

    for section_name, section_entries in sections or ():
        rendered = [f"• {_normalize_label(label)}: **{_display_value(value)}**" for label, value in section_entries]
        if not rendered:
            continue
        description_parts.append(f"**{context_emoji} {_section_title(section_name)}**")
        description_parts.append("\n".join(rendered))

    embed = discord.Embed(
        title=f"{top_emoji} {top_level_label}",
        description="\n\n".join(part for part in description_parts if part),
        colour=STATUS_COLOR_MAP.get(tone, discord.Colour.blurple()),
    )
    attach_footer_meta(embed, service_name=service_name, used_local_processing=True, minimal=True)
    return embed


async def send_standard_command_embed(
    interaction: discord.Interaction,
    *,
    top_level: str,
    path_parts: Sequence[str],
    entries: Iterable[tuple[str, object]],
    tone: str = "info",
    sections: Sequence[tuple[str, Sequence[tuple[str, object]]]] | None = None,
    service_name: str = "status",
    ephemeral: bool = True,
) -> None:
    embed = build_standard_command_embed(
        top_level=top_level,
        path_parts=path_parts,
        entries=entries,
        tone=tone,
        sections=sections,
        service_name=service_name,
    )
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        return
    await interaction.response.send_message(embed=embed, ephemeral=ephemeral)


def count_child_commands(parent: app_commands.Group) -> int:
    return len(parent.commands)


def _group_label(group: app_commands.Group) -> str:
    return group.qualified_name or group.name


def add_group_once(parent: app_commands.Group, child: app_commands.Group, logger: logging.Logger) -> bool:
    parent_label = _group_label(parent)
    current_children = count_child_commands(parent)
    logger.debug(
        "Attempting to register subgroup /%s under /%s (existing_children=%d)",
        child.name,
        parent_label,
        current_children,
    )
    existing_names = {cmd.name for cmd in parent.commands}
    if child.name in existing_names:
        logger.warning("Skipping duplicate subgroup %r under /%s", child.name, parent_label)
        return False
    try:
        parent.add_command(child)
    except ValueError:
        logger.exception(
            "Failed to register subgroup /%s under /%s (existing_children=%d).",
            child.name,
            parent_label,
            current_children,
        )
        raise
    return True


def add_command_once(group: app_commands.Group, command_obj: app_commands.Command, logger: logging.Logger) -> bool:
    group_label = _group_label(group)
    current_children = count_child_commands(group)
    logger.debug(
        "Attempting to register command /%s %s (existing_children=%d)",
        group_label,
        command_obj.name,
        current_children,
    )
    existing_names = {cmd.name for cmd in group.commands}
    if command_obj.name in existing_names:
        logger.warning("Skipping duplicate command %r under /%s", command_obj.name, group_label)
        return False
    try:
        group.add_command(command_obj)
    except ValueError:
        logger.exception(
            "Failed to register command %r under /%s (existing_children=%d).",
            command_obj.name,
            group_label,
            current_children,
        )
        raise
    return True


def describe_placeholders() -> str:
    return (
        "Placeholder: {user}, {username}, {display_name}, {mention}, {user_id}, {server}, {guild_id}, {days_inactive}, "
        "{window_days}, {min_messages}, {message_count}, {grace_days}, {reminder_count}, {ban_days}, {rejoin_link}, {reason}, "
        "{moderator}, {moderator_mention}, {duration}, {duration_days}, {expires_at}, {inactivity_text}."
    )
