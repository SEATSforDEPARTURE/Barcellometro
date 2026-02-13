from __future__ import annotations

import logging

import discord
from discord import app_commands

from app.core.service_registry import ServiceRegistry
from app.plugins.commands_modular import (
    CommandContext,
    register_admin,
    register_audio_notes,
    register_barcello,
    register_messaggi,
    register_privacy,
    register_riassunto,
    register_resoconto,
    register_roles,
    register_status,
    register_stt,
    register_translate,
    register_voice_ingest,
)

logger = logging.getLogger(__name__)


def setup(registry: ServiceRegistry) -> None:
    ctx = CommandContext.from_registry(registry)
    bot = ctx.bot
    config = ctx.config

    guild = discord.Object(id=config.guild_id)

    barcellometro_group = app_commands.Group(name="barcellometro", description="Controlli Barcellometro")
    role_group = app_commands.Group(name="role", description="Gestione permessi e limiti")
    stt_group = app_commands.Group(name="stt", description="Impostazioni STT")
    translate_group = app_commands.Group(name="translate", description="Impostazioni traduzione")
    audio_notes_group = app_commands.Group(name="audio_notes", description="Note vocali")
    messaggi_group = app_commands.Group(name="messaggi", description="Messaggi community")
    voice_ingest_group = app_commands.Group(name="voice_ingest", description="Ingest da canale vocale")
    privacy_group = app_commands.Group(name="privacy", description="Privacy per voice ingest")
    status_group = app_commands.Group(name="status", description="Stato servizi")
    riassunto_group = app_commands.Group(name="riassunto", description="Riassunto conversazione")
    resoconto_group = app_commands.Group(name="resoconto", description="Resoconto giornaliero")

    barcellometro_group.add_command(role_group)
    barcellometro_group.add_command(stt_group)
    barcellometro_group.add_command(translate_group)
    barcellometro_group.add_command(audio_notes_group)
    barcellometro_group.add_command(messaggi_group)
    barcellometro_group.add_command(voice_ingest_group)

    register_admin(barcellometro_group, ctx)
    register_roles(role_group, ctx)
    register_stt(stt_group, ctx)
    register_translate(translate_group, ctx)
    register_audio_notes(audio_notes_group, ctx)
    register_messaggi(messaggi_group, ctx)
    register_voice_ingest(voice_ingest_group, ctx)
    register_privacy(privacy_group, ctx)
    register_status(status_group, ctx)
    register_riassunto(riassunto_group, ctx)
    register_resoconto(resoconto_group, ctx)
    register_barcello(bot.tree, guild, ctx)

    bot.tree.add_command(barcellometro_group, guild=guild)
    bot.tree.add_command(riassunto_group, guild=guild)
    bot.tree.add_command(status_group, guild=guild)
    bot.tree.add_command(resoconto_group, guild=guild)
    bot.tree.add_command(privacy_group, guild=guild)

    async def handle_ready() -> None:
        try:
            synced = await bot.tree.sync(guild=guild)
            logger.info("Synced %s commands for guild %s", len(synced), config.guild_id)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to sync commands")

    bot.add_listener(handle_ready, "on_ready")
