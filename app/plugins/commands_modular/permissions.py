from __future__ import annotations

import discord

from app.plugins.commands_modular.ctx import CommandContext


async def check_permission(interaction: discord.Interaction, command_name: str, ctx: CommandContext) -> bool:
    guild = interaction.guild
    is_admin = bool(guild and interaction.user.guild_permissions.administrator)
    role_ids = [role.id for role in getattr(interaction.user, "roles", [])]
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
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(message, ephemeral=ephemeral)
    return False


async def ensure_admin(interaction: discord.Interaction) -> bool:
    guild = interaction.guild
    is_admin = bool(guild and interaction.user.guild_permissions.administrator)
    if is_admin:
        return True
    ephemeral = interaction.guild_id is not None
    if interaction.response.is_done():
        await interaction.followup.send("Solo admin.", ephemeral=ephemeral)
    else:
        await interaction.response.send_message("Solo admin.", ephemeral=ephemeral)
    return False
