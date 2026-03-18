from __future__ import annotations

from collections.abc import Iterable

import discord

from app.plugins.commands_modular.ctx import CommandContext


async def check_permission(
    interaction: discord.Interaction,
    command_name: str,
    ctx: CommandContext,
    *,
    legacy_aliases: Iterable[str] = (),
) -> bool:
    guild = interaction.guild
    is_admin = bool(guild and interaction.user.guild_permissions.administrator)
    role_ids = [role.id for role in getattr(interaction.user, "roles", [])]
    command_candidates = [command_name, *[alias for alias in legacy_aliases if alias and alias != command_name]]
    result = None
    for candidate in command_candidates:
        result = await ctx.guard.check_command(
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
            role_ids=role_ids,
            command=candidate,
            is_admin=is_admin,
        )
        if result.allowed:
            return True
        if result.reason != "Solo admin o policy configurata.":
            break

    assert result is not None
    message = result.reason
    if result.remaining is not None:
        message += f" Utilizzi rimanenti: {result.remaining}."
    if result.cooldown_remaining is not None:
        message += f" Cooldown: {result.cooldown_remaining}s."
    ephemeral = interaction.guild_id is not None
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(message, ephemeral=ephemeral)
    return False
