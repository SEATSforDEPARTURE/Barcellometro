from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.errors import NotFound

from app.core.service_registry import ServiceRegistry
from app.plugins.commands_modular import (
    CommandContext,
    register_admin,
    register_audio_notes,
    register_attivita,
    register_ask,
    register_aura,
    register_barcello,
    register_attivita_settings,
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
from app.plugins.commands_modular.command_helpers import add_group_once

logger = logging.getLogger(__name__)


def setup(registry: ServiceRegistry) -> None:
    logged_tree_once = False
    ctx = CommandContext.from_registry(registry)
    bot = ctx.bot
    config = ctx.config
    guild_id = int(config.guild_id or 0)
    use_guild = guild_id > 0
    guild_obj = discord.Object(id=guild_id) if use_guild else None

    if not use_guild:
        logger.warning("GUILD_ID missing/invalid; registering GLOBAL commands")

    bm_group = app_commands.Group(name="bm", description="Comandi bm")
    role_group = app_commands.Group(name="role", description="Permessi e limiti")
    stt_group = app_commands.Group(name="stt", description="Impostazioni STT")
    translate_group = app_commands.Group(name="translate", description="Traduzione")
    audio_notes_group = app_commands.Group(name="audio_notes", description="Note vocali")
    campagne_group = app_commands.Group(name="campagne", description="Campagne auto")
    qna_group = app_commands.Group(name="qna", description="QnA")
    insights_group = app_commands.Group(name="insights", description="Curiosità utenti")
    voice_ingest_group = app_commands.Group(name="voice_ingest", description="Ingest vocale")
    privacy_group = app_commands.Group(name="privacy", description="Privacy vocale")
    status_group = app_commands.Group(name="status", description="Stato servizi")
    riassunto_group = app_commands.Group(name="riassunto", description="Riassunti")
    aura_group = app_commands.Group(name="aura", description="Resoconto aura")
    attivita_group = app_commands.Group(name="attivita", description="Comandi attività (utenti) + gestione report (mod/admin)")
    inattivi_group = app_commands.Group(name="inattivi", description="Utenti inattivi")
    resoconto_group = app_commands.Group(name="resoconto", description="Resoconto giornaliero")

    add_group_once(bm_group, role_group, logger)
    add_group_once(bm_group, stt_group, logger)
    add_group_once(bm_group, translate_group, logger)
    add_group_once(bm_group, audio_notes_group, logger)
    add_group_once(bm_group, voice_ingest_group, logger)

    register_admin(bm_group, ctx)
    register_roles(role_group, ctx)
    register_stt(stt_group, ctx)
    register_translate(translate_group, ctx)
    register_audio_notes(audio_notes_group, ctx)
    register_messaggi(campagne_group, ctx)
    register_voice_ingest(voice_ingest_group, ctx)
    register_privacy(privacy_group, ctx)
    register_status(status_group, ctx)
    register_riassunto(riassunto_group, ctx)
    register_aura(aura_group, ctx)
    register_attivita(attivita_group, ctx)
    register_attivita_settings(attivita_group, ctx)

    inattivi_registered = True
    try:
        register_inattivi(inattivi_group, ctx)
        inattivi_subcommands = [cmd.qualified_name for cmd in inattivi_group.walk_commands()]
        logger.info("register_inattivi ok: subcommands=%s", inattivi_subcommands)
        logger.info("inattivi group commands=%s", [c.qualified_name for c in inattivi_group.walk_commands()])
    except Exception:
        inattivi_registered = False
        partial = [cmd.qualified_name for cmd in inattivi_group.walk_commands()]
        logger.exception("Failed to register inattivi commands; disabling /inattivi only")
        logger.error("Partial inattivi subcommands before failure: %s", partial)
        logger.warning("/inattivi disabled due to registration failure")

    register_resoconto(resoconto_group, ctx)
    frasi_group = register_triggers(bm_group, campagne_group, qna_group, insights_group, ctx)
    logger.info("Registering /barcello with guild scope=%s", "guild" if use_guild else "global")
    register_barcello(bot.tree, guild_obj, ctx)
    register_ask(bot.tree, guild_obj, ctx)
    scope_label = "guild" if guild_obj else "global"
    top_level = bot.tree.get_commands(guild=guild_obj) if guild_obj else bot.tree.get_commands()
    logger.info("Registered commands scope=%s top_level=%s", scope_label, [c.qualified_name for c in top_level])

    root_commands: list[app_commands.Command | app_commands.Group] = [
        bm_group,
        inattivi_group,
        qna_group,
        insights_group,
        campagne_group,
        riassunto_group,
        aura_group,
        attivita_group,
        status_group,
        resoconto_group,
        privacy_group,
        frasi_group,
    ]

    if not inattivi_registered:
        root_commands = [command for command in root_commands if command is not inattivi_group]

    def add_tree_command(command: app_commands.Command | app_commands.Group) -> None:
        if use_guild:
            bot.tree.add_command(command, guild=guild_obj)
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
                guild_commands = bot.tree.get_commands(guild=guild_obj) if use_guild else bot.tree.get_commands()
                known = ",".join(cmd.name for cmd in guild_commands) or "(none)"
                logger.warning("Known commands in tree: %s", known)
                logged_tree_once = True
            return
        logger.exception("App command error", exc_info=error)
        message = (
            "⚠️ Ho avuto un problema a costruire l’embed (limite Discord). "
            "Ho allegato un .txt se disponibile. Riprova o riduci la finestra."
        )
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except NotFound:
            logger.warning("Unable to deliver app command error response: interaction expired")
        except Exception:
            logger.exception("Failed to deliver app command error response")

    async def handle_ready() -> None:
        try:
            command_scope = "guild" if use_guild else "global"
            commands = bot.tree.get_commands(guild=guild_obj) if use_guild else bot.tree.get_commands()
            names = [command.qualified_name for command in commands]
            logger.info("Command tree pre-sync (%s) count=%d names=%s", command_scope, len(names), names)
            logger.info("Pre-sync check /barcello presente=%s scope=%s", "barcello" in names, command_scope)
            logger.info("Pre-sync check /domanda presente=%s scope=%s", "domanda" in names, command_scope)
            if use_guild:
                synced = await bot.tree.sync(guild=guild_obj)
                logger.info("Synced %d commands for %s", len(synced), "guild")
            else:
                logger.warning(
                    "Global command sync selected (GUILD_ID not set). Global propagation can take time; set GUILD_ID for immediate testing."
                )
                synced = await bot.tree.sync()
                logger.info("Synced %d commands for %s", len(synced), "global")
        except Exception:  # noqa: BLE001
            logger.exception("Failed to sync commands")

    bot.add_listener(handle_ready, "on_ready")
