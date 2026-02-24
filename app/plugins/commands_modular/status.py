from __future__ import annotations

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission


def register_status(status_group: app_commands.Group, ctx: CommandContext) -> None:
    @status_group.command(name="barcellometro", description="Stato servizi")
    @app_commands.describe(service="Servizio/plugin")
    async def status_barcellometro(interaction: discord.Interaction, service: str | None = None) -> None:
        if not await check_permission(interaction, "status.barcellometro", ctx):
            return
        if service:
            status = ctx.status.component_status(service)
            message = (
                f"**{service}**\n"
                f"Active: {status['active']}\n"
                f"State: {status['state']}\n"
                f"Metrics: {status['metrics']}"
            )
            await interaction.response.send_message(message, ephemeral=True)
            return
        general = await ctx.status.general_status()
        message = (
            "**Barcellometro Status**\n"
            f"Bot: online\n"
            f"DB Path: {general['db_path']}\n"
            f"Retention Days: {general['retention_days']}\n"
            f"Enabled Channels: {general['enabled_channels']}\n"
            f"Users: {general['users_count']}\n"
            f"Messages: {general['messages_count']}\n"
            f"Events: {general['events_count']}\n"
            f"Last Event: {general['last_event_ts']}"
        )
        await interaction.response.send_message(message, ephemeral=True)
