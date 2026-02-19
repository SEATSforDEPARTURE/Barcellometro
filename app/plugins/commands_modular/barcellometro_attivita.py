from __future__ import annotations

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission


def register_barcellometro_attivita(activity_group: app_commands.Group, ctx: CommandContext) -> None:
    async def _ensure(interaction: discord.Interaction) -> bool:
        return await check_permission(interaction, "barcellometro.attivita.config", ctx)

    @activity_group.command(name="on", description="Abilita monitorazione attività giornaliera")
    async def attivita_on(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction):
            return
        await ctx.database.upsert_activity_monitoring_config(
            str(interaction.guild_id),
            enabled=True,
            mod_channel_id=str(interaction.channel_id) if interaction.channel_id else None,
            send_time_local="09:00",
        )
        await interaction.response.send_message("✅ Monitorazione attività attivata.", ephemeral=True)

    @activity_group.command(name="off", description="Disabilita monitorazione attività giornaliera")
    async def attivita_off(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction):
            return
        current = await ctx.database.get_activity_monitoring_config(str(interaction.guild_id))
        await ctx.database.upsert_activity_monitoring_config(
            str(interaction.guild_id),
            enabled=False,
            mod_channel_id=str(current["mod_channel_id"]) if current and current["mod_channel_id"] else None,
            send_time_local=str(current["send_time_local"]) if current else "09:00",
        )
        await interaction.response.send_message("🛑 Monitorazione attività disattivata.", ephemeral=True)

    @activity_group.command(name="stato", description="Stato monitorazione attività")
    async def attivita_stato(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction):
            return
        cfg = await ctx.database.get_activity_monitoring_config(str(interaction.guild_id))
        channel_count = len(await ctx.database.list_enabled_message_channels(str(interaction.guild_id)))
        if not cfg:
            await interaction.response.send_message("Monitorazione non configurata.", ephemeral=True)
            return
        enabled = "ON" if bool(cfg["enabled"]) else "OFF"
        mod_channel = f"<#{cfg['mod_channel_id']}>" if cfg["mod_channel_id"] else "n/d"
        send_time = str(cfg["send_time_local"] or "09:00")
        await interaction.response.send_message(
            f"Stato: **{enabled}**\nCanale mod: {mod_channel}\nOrario: **{send_time}**\nCanali monitorati: **{channel_count}**",
            ephemeral=True,
        )
