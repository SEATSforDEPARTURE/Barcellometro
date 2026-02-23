from __future__ import annotations

import logging

import discord
from discord import app_commands

from app.core.service_registry import ServiceRegistry
from app.plugins.commands_modular import (
    CommandContext,
    register_admin,
    register_audio_notes,
    register_attivita,
    register_ask,
    register_barcello,
    register_barcellometro_attivita,
    register_inattivi,
    register_messaggi,
    register_privacy,
    register_riassunto,
    register_resoconto,
    register_roles,
    register_status,
    register_stt,
    register_translate,
    register_triggers,
    register_voice_ingest,
)

logger = logging.getLogger(__name__)


def setup(registry: ServiceRegistry) -> None:
    logged_tree_once = False
    ctx = CommandContext.from_registry(registry)
    bot = ctx.bot
    config = ctx.config
    guild_id = int(config.guild_id or 0)
    use_guild = guild_id > 0
    guild = discord.Object(id=guild_id) if use_guild else None

    if not use_guild:
        logger.warning("GUILD_ID missing/invalid; registering GLOBAL commands")

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
    attivita_group = app_commands.Group(name="attivita", description="Report attività canale (staff)")
    activity_config_group = app_commands.Group(name="attivita", description="Monitorazione attività")
    inattivi_group = app_commands.Group(name="inattivi", description="Gestione inattivi server-wide")
    resoconto_group = app_commands.Group(name="resoconto", description="Resoconto giornaliero")

    barcellometro_group.add_command(role_group)
    barcellometro_group.add_command(stt_group)
    barcellometro_group.add_command(translate_group)
    barcellometro_group.add_command(audio_notes_group)
    barcellometro_group.add_command(messaggi_group)
    barcellometro_group.add_command(voice_ingest_group)
    barcellometro_group.add_command(activity_config_group)
    barcellometro_group.add_command(inattivi_group)

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
    register_attivita(attivita_group, ctx)
    register_barcellometro_attivita(activity_config_group, ctx)

    inattivi_registered = True
    try:
        register_inattivi(inattivi_group, ctx)
        inattivi_subcommands = [cmd.qualified_name for cmd in inattivi_group.walk_commands()]
        logger.info("register_inattivi ok: subcommands=%s", inattivi_subcommands)
    except Exception:
        inattivi_registered = False
        partial = [cmd.qualified_name for cmd in inattivi_group.walk_commands()]
        logger.exception("Failed to register inattivi commands; disabling /barcellometro inattivi only")
        logger.error("Partial inattivi subcommands before failure: %s", partial)
        logger.warning("/barcellometro inattivi disabled due to registration failure")
    if inattivi_registered:
        barcellometro_group.add_command(inattivi_group)

    register_resoconto(resoconto_group, ctx)
    register_triggers(barcellometro_group, ctx)
    register_barcello(bot.tree, guild, ctx)
    register_ask(bot.tree, guild, ctx)

    root_commands: list[app_commands.Command | app_commands.Group] = [
        barcellometro_group,
        riassunto_group,
        attivita_group,
        status_group,
        resoconto_group,
        privacy_group,
    ]

    def add_tree_command(command: app_commands.Command | app_commands.Group) -> None:
        if use_guild:
            bot.tree.add_command(command, guild=guild)
        else:
            bot.tree.add_command(command)

    def register_root_commands() -> None:
        for command in root_commands:
            add_tree_command(command)

    register_root_commands()

    @bot.tree.error
    async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        nonlocal logged_tree_once
        if isinstance(error, app_commands.errors.CommandNotFound):
            name = (interaction.data or {}).get("name")
            logger.warning(
                "CommandNotFound for /%s (interaction.guild_id=%s config.guild_id=%s). Likely stale/mismatched sync.",
                name,
                getattr(interaction, "guild_id", None),
                config.guild_id,
            )
            if not logged_tree_once:
                guild_commands = bot.tree.get_commands(guild=guild) if use_guild else bot.tree.get_commands()
                known = ",".join(cmd.name for cmd in guild_commands) or "(none)"
                logger.warning("Known commands in tree: %s", known)
                logged_tree_once = True
            return
        logger.exception("App command error")
        raise error

    async def handle_ready() -> None:
        try:
            command_scope = "guild" if use_guild else "global"
            if use_guild:
                bot.tree.clear_commands(guild=guild)
                register_root_commands()
            commands = bot.tree.get_commands(guild=guild) if use_guild else bot.tree.get_commands()
            names = [command.qualified_name for command in commands]
            logger.info(
                "App commands pre-sync: mode=%s guild_id=%s use_guild=%s",
                command_scope,
                guild_id,
                use_guild,
            )
            logger.info("Command tree pre-sync count=%d names=%s", len(names), names)
            if use_guild:
                bot.tree.clear_commands(guild=None)
                logger.info("Cleared global app commands from local tree before guild sync to avoid scope mismatch")
                synced = await bot.tree.sync(guild=guild)
                logger.info("Synced %s commands for guild %s", len(synced), config.guild_id)
            else:
                logger.warning(
                    "Global command sync selected (GUILD_ID not set). Global propagation can take time; set GUILD_ID for immediate testing."
                )
                synced = await bot.tree.sync()
                logger.info("Synced %s global commands", len(synced))
        except Exception:  # noqa: BLE001
            logger.exception("Failed to sync commands")

    bot.add_listener(handle_ready, "on_ready")
