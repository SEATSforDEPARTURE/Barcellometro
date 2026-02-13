from __future__ import annotations

import logging
import re

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission

logger = logging.getLogger(__name__)
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def register_resoconto(resoconto_group: app_commands.Group, ctx: CommandContext) -> None:
    async def send_ephemeral(interaction: discord.Interaction, message: str) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @resoconto_group.command(name="giornaliero", description="Gestisci il resoconto giornaliero")
    @app_commands.describe(opzione="on/off/stato/HH:MM o vuoto per invio manuale")
    async def giornaliero(interaction: discord.Interaction, opzione: str | None = None) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in un canale guild.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return

        db = ctx.database
        guild_id = str(interaction.guild_id)
        channel_id = str(interaction.channel_id)
        value = (opzione or "").strip().lower()

        if value == "on":
            await db.set_daily_report_enabled(guild_id, channel_id, True)
            await send_ephemeral(interaction, "✅ Resoconto giornaliero attivato per questo canale.")
            return
        if value == "off":
            await db.set_daily_report_enabled(guild_id, channel_id, False)
            await send_ephemeral(interaction, "✅ Resoconto giornaliero disattivato per questo canale.")
            return
        if value == "stato":
            row = await db.get_daily_report_config(guild_id, channel_id)
            if not row:
                await send_ephemeral(interaction, "ℹ️ Nessuna configurazione: OFF, orario 00:00.")
                return
            enabled = "ON" if bool(row["enabled"]) else "OFF"
            await send_ephemeral(interaction, f"ℹ️ Stato: {enabled} — orario: {row['send_time_local']} (Europe/Rome)")
            return
        if value and TIME_RE.fullmatch(value):
            await db.set_daily_report_time(guild_id, channel_id, value)
            await send_ephemeral(interaction, f"✅ Orario resoconto impostato alle {value} (Europe/Rome).")
            return
        if value:
            await send_ephemeral(interaction, "❌ Opzione non valida. Usa on/off/stato/HH:MM oppure niente per invio manuale.")
            return

        daily_service = ctx.daily_resoconto
        if daily_service is None:
            await send_ephemeral(interaction, "❌ Servizio resoconto non disponibile.")
            return
        sent = await daily_service.generate_and_send_for_channel(guild_id, channel_id, manual=True)
        if sent:
            await send_ephemeral(interaction, "✅ Resoconto inviato ora. Aggiornata la data odierna per evitare doppio invio automatico.")
        else:
            await send_ephemeral(interaction, "⚠️ Non sono riuscito a inviare il resoconto in questo canale.")
