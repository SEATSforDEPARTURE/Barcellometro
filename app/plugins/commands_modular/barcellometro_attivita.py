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
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("❌ Gilda o canale non validi.", ephemeral=True)
            return
        await ctx.database.set_activity_channel_enabled(str(interaction.guild_id), str(interaction.channel_id), True)
        await interaction.response.send_message("✅ Canale aggiunto alla monitorazione attività.", ephemeral=True)

    @activity_group.command(name="off", description="Disabilita monitorazione attività giornaliera")
    async def attivita_off(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction):
            return
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("❌ Gilda o canale non validi.", ephemeral=True)
            return
        await ctx.database.set_activity_channel_enabled(str(interaction.guild_id), str(interaction.channel_id), False)
        await interaction.response.send_message("🛑 Canale rimosso dalla monitorazione attività.", ephemeral=True)

    @activity_group.command(name="canale", description="Imposta il canale mod per il resoconto attività")
    @app_commands.describe(canale_mod="Canale in cui pubblicare il resoconto giornaliero")
    async def attivita_canale(interaction: discord.Interaction, canale_mod: discord.TextChannel) -> None:
        if not await _ensure(interaction):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("❌ Gilda non valida.", ephemeral=True)
            return

        guild_id = str(interaction.guild_id)
        current = await ctx.database.get_activity_monitoring_config(guild_id)
        send_time = str(current["send_time_local"]) if current and current["send_time_local"] else "09:00"
        enabled = bool(current["enabled"]) if current else True
        await ctx.database.upsert_activity_monitoring_config(
            guild_id,
            enabled=enabled,
            mod_channel_id=str(canale_mod.id),
            send_time_local=send_time,
        )
        await interaction.response.send_message(
            f"✅ Canale mod impostato su {canale_mod.mention}.",
            ephemeral=True,
        )

    @activity_group.command(name="ora", description="Imposta l'orario di pubblicazione del resoconto")
    @app_commands.describe(hhmm="Orario locale Europe/Rome in formato HH:MM (es. 09:00)")
    async def attivita_ora(interaction: discord.Interaction, hhmm: str) -> None:
        if not await _ensure(interaction):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("❌ Gilda non valida.", ephemeral=True)
            return

        try:
            safe_time = ctx.database._validate_hhmm(hhmm)
        except ValueError:
            await interaction.response.send_message("❌ Formato ora non valido. Usa HH:MM (es. 09:00).", ephemeral=True)
            return

        guild_id = str(interaction.guild_id)
        current = await ctx.database.get_activity_monitoring_config(guild_id)
        mod_channel_id = str(current["mod_channel_id"]) if current and current["mod_channel_id"] else None
        enabled = bool(current["enabled"]) if current else True
        await ctx.database.upsert_activity_monitoring_config(
            guild_id,
            enabled=enabled,
            mod_channel_id=mod_channel_id,
            send_time_local=safe_time,
        )
        await interaction.response.send_message(f"✅ Orario impostato a **{safe_time}** (Europe/Rome).", ephemeral=True)

    @activity_group.command(name="stato", description="Stato monitorazione attività")
    async def attivita_stato(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("❌ Gilda non valida.", ephemeral=True)
            return

        guild_id = str(interaction.guild_id)
        cfg = await ctx.database.get_activity_monitoring_config(guild_id)
        channel_count = len(await ctx.database.list_enabled_activity_channels(guild_id))
        if not cfg:
            await interaction.response.send_message(
                f"Stato scheduler: **OFF**\nCanale mod: n/d\nOrario: **09:00**\nCanali monitorati: **{channel_count}**",
                ephemeral=True,
            )
            return
        enabled = "ON" if bool(cfg["enabled"]) else "OFF"
        mod_channel = f"<#{cfg['mod_channel_id']}>" if cfg["mod_channel_id"] else "n/d"
        send_time = str(cfg["send_time_local"] or "09:00")
        await interaction.response.send_message(
            f"Stato scheduler: **{enabled}**\nCanale mod: {mod_channel}\nOrario: **{send_time}**\nCanali monitorati: **{channel_count}**",
            ephemeral=True,
        )
