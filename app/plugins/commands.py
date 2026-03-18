from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.errors import NotFound

from app.core.service_registry import ServiceRegistry
from app.plugins.commands_modular import (
    CommandContext,
    register_admin,
    register_ask,
    register_audio_notes,
    register_attivita,
    register_aura,
    register_barcello,
    register_attivita_settings,
    register_inattivi,
    register_messaggi,
    register_moderazione_utenti,
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
from app.utils.command_embeds import send_standard_response
from app.utils.footer_pipeline import install_footer_auto_finalize

logger = logging.getLogger(__name__)


def setup(registry: ServiceRegistry) -> None:
    logged_tree_once = False
    ctx = CommandContext.from_registry(registry)
    if ctx.footer is not None:
        install_footer_auto_finalize(ctx.footer)
    bot = ctx.bot
    config = ctx.config
    guild_id = int(config.guild_id or 0)
    use_guild = guild_id > 0
    guild_obj = discord.Object(id=guild_id) if use_guild else None

    if not use_guild:
        logger.warning("GUILD_ID missing/invalid; registering GLOBAL commands")

    bm_group = app_commands.Group(name="bm", description="Barcellometro control commands")
    commandguard_group = app_commands.Group(name="commandguard", description="Command guard policies")
    stt_group = app_commands.Group(name="stt", description="Speech-to-text configuration")
    translate_group = app_commands.Group(name="translate", description="Translation configuration")
    audionotes_group = app_commands.Group(name="audionotes", description="Audio notes controls")
    campagne_group = app_commands.Group(name="campagne", description="Campaign controls")
    qna_group = app_commands.Group(name="qna", description="QnA controls")
    insights_group = app_commands.Group(name="insights", description="Insights controls")
    voice_ingest_group = app_commands.Group(name="voice_ingest", description="Voice ingest")
    privacy_group = app_commands.Group(name="privacy", description="Voice privacy controls")
    riassunto_group = app_commands.Group(name="riassunto", description="Summaries")
    aura_group = app_commands.Group(name="aura", description="Aura reports")
    attivita_group = app_commands.Group(name="attivita", description="User activity commands")
    mod_group = app_commands.Group(name="mod", description="Moderation controls")
    inactivity_group = app_commands.Group(name="inactivity", description="Inactive member moderation")
    resocontocanale_group = app_commands.Group(name="resocontocanale", description="Channel summary schedules")
    resocontoserver_group = app_commands.Group(name="resocontoserver", description="Server summary schedules")

    add_group_once(bm_group, commandguard_group, logger)
    add_group_once(bm_group, stt_group, logger)
    add_group_once(bm_group, translate_group, logger)
    add_group_once(bm_group, audionotes_group, logger)
    add_group_once(bm_group, voice_ingest_group, logger)

    register_admin(bm_group, ctx)
    register_roles(commandguard_group, ctx)
    register_stt(stt_group, ctx)
    register_translate(translate_group, ctx)
    register_audio_notes(audionotes_group, ctx)
    register_messaggi(campagne_group, ctx)
    register_voice_ingest(voice_ingest_group, ctx)
    register_privacy(privacy_group, ctx)
    register_status(bm_group, ctx)
    register_barcello(bm_group, ctx)
    register_riassunto(riassunto_group, ctx)
    register_aura(aura_group, ctx)
    register_attivita(attivita_group, ctx)
    register_attivita_settings(attivita_group, ctx)

    register_inattivi(inactivity_group, ctx)
    register_moderazione_utenti(mod_group, ctx)

    register_resoconto(resocontocanale_group, resocontoserver_group, ctx)
    frasi_group = register_triggers(bm_group, campagne_group, qna_group, insights_group, ctx)

    logger.info(
        "Group children summary bm=%d campagne=%d qna=%d insights=%d",
        len(bm_group.commands),
        len(campagne_group.commands),
        len(qna_group.commands),
        len(insights_group.commands),
    )
    register_ask(bot.tree, guild_obj, ctx)
    scope_label = "guild" if guild_obj else "global"
    top_level = bot.tree.get_commands(guild=guild_obj) if guild_obj else bot.tree.get_commands()
    logger.info("Registered commands scope=%s top_level=%s", scope_label, [c.qualified_name for c in top_level])

    root_commands: list[app_commands.Command | app_commands.Group] = [
        bm_group,
        qna_group,
        insights_group,
        campagne_group,
        riassunto_group,
        aura_group,
        attivita_group,
        mod_group,
        inactivity_group,
        resocontocanale_group,
        resocontoserver_group,
        privacy_group,
        frasi_group,
    ]

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
        root_error: Exception | app_commands.AppCommandError = error
        if isinstance(error, app_commands.CommandInvokeError) and error.original:
            root_error = error.original
        detail = str(root_error).lower()
        looks_like_embed_error = any(token in detail for token in ["embed", "field", "6000", "1024", "invalid form body"])
        if looks_like_embed_error:
            message = "Ho avuto un problema a costruire l’embed (limite Discord). Riprova o riduci la finestra."
            kind = "warning"
        else:
            message = "Si è verificato un errore interno durante l'esecuzione del comando. Riprova tra poco."
            kind = "error"
        try:
            command_name = str(getattr(getattr(interaction, "command", None), "qualified_name", "") or "").strip()
            interaction_name = str((interaction.data or {}).get("name") or "").strip()
            subcommand_path = "system app_command_error"
            if command_name:
                subcommand_path = f"{command_name} error"
            elif interaction_name:
                subcommand_path = f"{interaction_name} error"
            await send_standard_response(
                interaction,
                top_level="status",
                subcommand_path=subcommand_path,
                lines=[("detail", message)],
                kind=kind,
                footer_service=ctx.footer,
                ephemeral=True,
            )
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
