from __future__ import annotations

import re

import discord

from app.shared.discord.command_embeds import send_standard_response
from app.plugins.commands_modular.ctx import CommandContext


_ROOT_ALIASES: dict[str, tuple[str, ...]] = {
    "campagne": ("campaigns",),
    "frasi": ("triggers", "phrases"),
    "roles": ("commandguard",),
    "resocontocanale": ("channelsummary",),
    "resocontoserver": ("serversummary",),
}
_TRIGGER_SUBGROUPS = {"phrases", "qna", "insights", "barcello"}
_LEGACY_ADMIN_ALIASES: dict[tuple[str, ...], tuple[str, ...]] = {
    ("status",): ("status",),
    ("events",): ("database", "events"),
    ("retention",): ("database", "retention"),
    ("backfill",): ("database", "backfill"),
    ("ai",): ("ai",),
    ("barcello", "mood_set"): ("status", "mood_set"),
    ("barcello", "mood_show"): ("status", "mood_show"),
    ("barcello", "mood_reset"): ("status", "mood_reset"),
}

_TRIGGER_PHRASE_ACTIONS = {
    "on",
    "off",
    "status",
    "entry_add",
    "entry_remove",
    "entry_list",
    "entry_show",
    "entry_edit",
    "template_milestone_set",
    "template_milestone_show",
    "template_milestone_reset",
    "template_global_set",
    "template_global_show",
    "template_global_reset",
    "template_user_set",
    "template_user_show",
    "template_user_reset",
}


def _normalize_path_segments(command_name: str) -> list[str]:
    cleaned = re.sub(r"\s+", "", str(command_name or "").strip().lower())
    return [segment for segment in cleaned.split(".") if segment]


def canonical_permission_key(command_name: str) -> str:
    parts = _normalize_path_segments(command_name)
    if not parts:
        return ""

    prefix: list[str] = []
    body = parts
    if body[0] == "admin":
        body = body[1:]
        if not body:
            return ""
        alias_key = tuple(body[:2]) if tuple(body[:2]) in _LEGACY_ADMIN_ALIASES else tuple(body[:1])
        alias = _LEGACY_ADMIN_ALIASES.get(alias_key)
        if alias is not None:
            body = [*alias, *body[len(alias_key):]]
        else:
            prefix = ["admin"]

    if len(body) >= 3 and body[0] == "database" and body[1] in {"retention", "backfill"}:
        config_aliases = {"config_set": "limits_set", "config_show": "limits_show", "config_reset": "limits_reset"}
        body[2] = config_aliases.get(body[2], body[2])

    if not body:
        return ".".join(prefix)

    head, *tail = body
    normalized_body = [*_ROOT_ALIASES.get(head, (head,)), *tail]

    if (
        normalized_body
        and normalized_body[0] == "triggers"
        and len(normalized_body) >= 2
        and normalized_body[1] not in _TRIGGER_SUBGROUPS
        and normalized_body[1] in _TRIGGER_PHRASE_ACTIONS
    ):
        normalized_body = [normalized_body[0], "phrases", *normalized_body[1:]]

    return ".".join([*prefix, *normalized_body])


async def check_permission(
    interaction: discord.Interaction,
    command_name: str,
    ctx: CommandContext,
) -> bool:
    guild = interaction.guild
    is_admin = bool(guild and interaction.user.guild_permissions.administrator)
    role_ids = [role.id for role in getattr(interaction.user, "roles", [])]
    command_name = canonical_permission_key(command_name)
    result = await ctx.guard.check_command(
        guild_id=interaction.guild_id,
        user_id=interaction.user.id,
        role_ids=role_ids,
        command=command_name,
        is_admin=is_admin,
    )
    if result.allowed:
        return True

    message = result.reason
    if result.remaining is not None:
        message += f" Utilizzi rimanenti: {result.remaining}."
    if result.cooldown_remaining is not None:
        message += f" Cooldown: {result.cooldown_remaining}s."
    ephemeral = interaction.guild_id is not None
    qualified_name = str(getattr(getattr(interaction, "command", None), "qualified_name", "") or "").strip()
    subcommand_path = f"{qualified_name} warning" if qualified_name else "warning"
    visual_top_level = qualified_name.split()[0] if qualified_name else None
    await send_standard_response(
        interaction,
        top_level=visual_top_level or "status",
        subcommand_path=subcommand_path,
        visual_top_level=visual_top_level,
        lines=[("reason", message)],
        kind="warning",
        footer_service=ctx.footer,
        ephemeral=ephemeral,
    )
    return False
