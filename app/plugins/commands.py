from __future__ import annotations

import logging

import discord
from discord import app_commands

from app.core.service_registry import ServiceRegistry

logger = logging.getLogger(__name__)


def setup(registry: ServiceRegistry) -> None:
    bot: discord.Client = registry.get("bot")
    database = registry.get("database")
    retention = registry.get("retention")
    backfill = registry.get("backfill")
    status_service = registry.get("status")
    config = registry.get("config")

    guild = discord.Object(id=config.guild_id)

    barcellometro_group = app_commands.Group(name="barcellometro", description="Controlli Barcellometro")
    status_group = app_commands.Group(name="status", description="Stato servizi")

    @barcellometro_group.command(name="check", description="Abilita o disabilita la raccolta eventi nel canale")
    @app_commands.describe(state="on/off")
    @app_commands.choices(state=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
    async def check_command(interaction: discord.Interaction, state: app_commands.Choice[str]) -> None:
        if not interaction.channel or not isinstance(interaction.channel, discord.abc.GuildChannel):
            await interaction.response.send_message("Questo comando funziona solo nei canali della guild.", ephemeral=True)
            return
        enabled = 1 if state.value == "on" else 0
        await database.upsert_channel(
            channel_id=str(interaction.channel.id),
            guild_id=str(interaction.guild_id),
            name=interaction.channel.name,
            enabled=enabled,
            channel_type=str(interaction.channel.type),
            category_id=str(interaction.channel.category_id) if interaction.channel.category_id else None,
            is_nsfw=1 if interaction.channel.is_nsfw() else 0,
            slowmode_delay=interaction.channel.slowmode_delay,
        )
        await interaction.response.send_message(
            f"Canale {'abilitato' if enabled else 'disabilitato'} per la raccolta eventi.",
            ephemeral=True,
        )

    @barcellometro_group.command(name="retention", description="Gestisci la retention dei dati")
    @app_commands.describe(action="get/set", days="Numero di giorni di retention")
    @app_commands.choices(action=[app_commands.Choice(name="get", value="get"), app_commands.Choice(name="set", value="set")])
    async def retention_command(
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        days: int | None = None,
    ) -> None:
        if action.value == "get":
            current = await retention.get_retention_days()
            await interaction.response.send_message(f"Retention attuale: {current} giorni.", ephemeral=True)
            return
        if days is None or days <= 0:
            await interaction.response.send_message("Specifica un numero di giorni valido.", ephemeral=True)
            return
        await retention.set_retention_days(days)
        await interaction.response.send_message(f"Retention aggiornata a {days} giorni.", ephemeral=True)

    @barcellometro_group.command(name="backfill", description="Gestisci il backfill dei dati")
    @app_commands.describe(state="on/off", days="Numero di giorni di backfill")
    @app_commands.choices(state=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
    async def backfill_command(
        interaction: discord.Interaction,
        state: app_commands.Choice[str] | None = None,
        days: int | None = None,
    ) -> None:
        if state is None and days is None:
            current_days = await backfill.get_backfill_days()
            enabled = await backfill.is_enabled()
            await interaction.response.send_message(
                f"Backfill {'attivo' if enabled else 'disattivato'} ({current_days} giorni).",
                ephemeral=True,
            )
            return

        if days is not None:
            if days <= 0:
                await interaction.response.send_message("Specifica un numero di giorni valido.", ephemeral=True)
                return
            await backfill.set_backfill_days(days)

        if state is not None:
            await backfill.set_enabled(state.value == "on")

        if await backfill.is_enabled():
            result = await backfill.run_once()
            await interaction.response.send_message(
                "Backfill completato. "
                f"Messaggi: {result.messages}, Eventi: {result.events}, Canali: {result.channels}, Errori: {result.errors}.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message("Backfill disattivato.", ephemeral=True)

    @status_group.command(name="barcellometro", description="Stato generale o di un servizio/plugin")
    @app_commands.describe(service="Nome servizio o plugin")
    async def status_barcellometro(interaction: discord.Interaction, service: str | None = None) -> None:
        if service:
            status = status_service.component_status(service)
            message = (
                f"**{service}**\n"
                f"Active: {status['active']}\n"
                f"State: {status['state']}\n"
                f"Metrics: {status['metrics']}"
            )
            await interaction.response.send_message(message, ephemeral=True)
            return
        general = await status_service.general_status()
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

    bot.tree.add_command(barcellometro_group, guild=guild)
    bot.tree.add_command(status_group, guild=guild)

    async def handle_ready() -> None:
        try:
            synced = await bot.tree.sync(guild=guild)
            logger.info("Synced %s commands for guild %s", len(synced), config.guild_id)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to sync commands")

    bot.add_listener(handle_ready, "on_ready")
