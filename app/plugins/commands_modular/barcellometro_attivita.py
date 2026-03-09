from __future__ import annotations

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.barcellometro_attivita_logic import send_activity_now, set_activity_send_time, validate_hhmm


def register_attivita_settings(attivita_group: app_commands.Group, ctx: CommandContext) -> None:
    async def _ensure(interaction: discord.Interaction) -> bool:
        return await check_permission(interaction, "bm.attivita.config", ctx)

    @attivita_group.command(name="on", description="Enable daily activity scheduler")
    async def attivita_on(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction):
            return
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("❌ Gilda o canale non validi.", ephemeral=True)
            return
        await ctx.database.set_activity_channel_enabled(str(interaction.guild_id), str(interaction.channel_id), True)
        await interaction.response.send_message("✅ Canale aggiunto alla monitorazione attività.", ephemeral=True)

    @attivita_group.command(name="off", description="Disable daily activity scheduler")
    async def attivita_off(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction):
            return
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("❌ Gilda o canale non validi.", ephemeral=True)
            return
        await ctx.database.set_activity_channel_enabled(str(interaction.guild_id), str(interaction.channel_id), False)
        await interaction.response.send_message("🛑 Canale rimosso dalla monitorazione attività.", ephemeral=True)

    @attivita_group.command(name="status", description="Show scheduler status")
    async def attivita_status(interaction: discord.Interaction) -> None:
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

    @attivita_group.command(name="run", description="Run daily report now")
    async def attivita_run(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("❌ Gilda non valida.", ephemeral=True)
            return
        guild_id = str(interaction.guild_id)
        if ctx.daily_activity_report is None:
            await interaction.response.send_message("❌ Servizio daily_activity_report non disponibile.", ephemeral=True)
            return
        mod_channel_id = await send_activity_now(ctx.database, ctx.daily_activity_report, guild_id=guild_id)
        if not mod_channel_id:
            await interaction.response.send_message("Imposta prima il canale mod con /attivita set channel …", ephemeral=True)
            return
        await interaction.response.send_message(f"📨 Resoconto inviato in <#{mod_channel_id}>.", ephemeral=True)

    set_group = app_commands.Group(name="set", description="Configure activity scheduler")

    @set_group.command(name="hour", description="Set scheduler hour")
    @app_commands.describe(hhmm="Orario HH:MM")
    async def attivita_set_hour(interaction: discord.Interaction, hhmm: str) -> None:
        if not await _ensure(interaction):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("❌ Gilda non valida.", ephemeral=True)
            return
        if validate_hhmm(hhmm) is not None:
            await interaction.response.send_message("❌ Orario non valido. Usa HH:MM (es. 20:30).", ephemeral=True)
            return

        guild_id = str(interaction.guild_id)
        mod_channel_id = await set_activity_send_time(ctx.database, guild_id=guild_id, hhmm=hhmm)
        if mod_channel_id:
            await interaction.response.send_message(
                f"✅ Orario aggiornato: **{hhmm}**. Il resoconto verrà pubblicato in <#{mod_channel_id}>.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(f"✅ Orario aggiornato: **{hhmm}**.", ephemeral=True)

    @set_group.command(name="channel", description="Set mod report channel")
    @app_commands.describe(channel="Canale report")
    async def attivita_set_channel(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
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
            mod_channel_id=str(channel.id),
            send_time_local=send_time,
        )
        await interaction.response.send_message(f"✅ Canale mod impostato su {channel.mention}.", ephemeral=True)

    attivita_group.add_command(set_group)
