from __future__ import annotations

import discord

from app.shared.discord.command_embeds import send_standard_response
from app.plugins.commands_modular.ctx import CommandContext


def canonical_permission_key(command_name: str) -> str:
    return str(command_name or "").strip().lower()


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
        top_level="admin",
        subcommand_path=subcommand_path,
        visual_top_level=visual_top_level,
        lines=[("reason", message)],
        kind="warning",
        footer_service=ctx.footer,
        ephemeral=ephemeral,
    )
    return False
