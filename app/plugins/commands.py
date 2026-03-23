from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.errors import NotFound

from app.core.service_registry import ServiceRegistry
from app.plugins.commands_modular import (
    CommandContext,
    register_ai,
    register_ask,
    register_attivita,
    register_aura,
    register_audio_notes,
    register_barcello,
    register_database,
    register_embed,
    register_greetings,
    register_inattivi,
    register_messaggi,
    register_moderazione_utenti,
    register_privacy,
    register_resoconto,
    register_riassunto,
    register_roles,
    register_status,
    register_stt,
    register_translate,
    register_triggers,
    register_voice_ingest,
)
from app.plugins.commands_modular.registration import add_group_once
from app.shared.discord.author_pipeline import install_author_auto_finalize
from app.shared.discord.command_embeds import send_standard_response
from app.shared.discord.footer_pipeline import install_footer_auto_finalize

logger = logging.getLogger(__name__)


def setup(registry: ServiceRegistry) -> None:
    logged_tree_once = False
    ctx = CommandContext.from_registry(registry)
    if ctx.footer is not None:
        install_footer_auto_finalize(ctx.footer)
    author_service = getattr(ctx, "author", None)
    if author_service is not None:
        install_author_auto_finalize(author_service)
    bot = ctx.bot
    config = ctx.config
    guild_id = int(config.guild_id or 0)
    use_guild = guild_id > 0
    guild_obj = discord.Object(id=guild_id) if use_guild else None

    if not use_guild:
        logger.warning("GUILD_ID missing/invalid; registering GLOBAL commands")

    status_group = app_commands.Group(name="status", description="Status controls")
    database_group = app_commands.Group(name="database", description="Database and ingestion controls")
    ai_group = app_commands.Group(name="ai", description="AI controls")
    commandguard_group = app_commands.Group(name="commandguard", description="Command guard policies")
    audio_group = app_commands.Group(name="audio", description="Audio controls")
    campaigns_group = app_commands.Group(name="campaigns", description="Campaign controls")
    qna_group = app_commands.Group(name="qna", description="QnA controls")
    triggers_group = app_commands.Group(name="triggers", description="Trigger controls")
    embed_group = app_commands.Group(name="embed", description="Embed controls")
    privacy_group = app_commands.Group(name="privacy", description="Voice privacy controls")
    users_group = app_commands.Group(name="users", description="User management controls")
    greetings_group = app_commands.Group(name="greetings", description="Greetings controls")
    inactivity_group = app_commands.Group(name="inactivity", description="Inactive member moderation")
    channelsummary_group = app_commands.Group(name="channelsummary", description="Channel summary schedules")
    serversummary_group = app_commands.Group(name="serversummary", description="Server summary schedules")
    dmsummary_group = app_commands.Group(name="dmsummary", description="Direct message summaries")
    aurasummary_group = app_commands.Group(name="aurasummary", description="Aura summaries")
    barcellosummary_group = app_commands.Group(name="barcellosummary", description="Barcello summaries")

    riassunto_alias_group = app_commands.Group(name="riassunto", description="Riassunti")
    aura_alias_group = app_commands.Group(name="aura", description="Aura reports")
    resocontocanale_alias_group = app_commands.Group(name="resocontocanale", description="Channel summary schedules")
    resocontoserver_alias_group = app_commands.Group(name="resocontoserver", description="Server summary schedules")
    attivita_group = app_commands.Group(name="attivita", description="User activity commands")

    stt_group = app_commands.Group(name="stt", description="Speech-to-text configuration")
    translate_group = app_commands.Group(name="translate", description="Translation configuration")
    voice_ingest_group = app_commands.Group(name="voice_ingest", description="Voice ingest")
    insights_group = app_commands.Group(name="insights", description="Insights controls")

    add_group_once(audio_group, stt_group, logger)
    add_group_once(audio_group, translate_group, logger)
    add_group_once(audio_group, voice_ingest_group, logger)
    add_group_once(ai_group, insights_group, logger)

    register_status(status_group, ctx)
    register_database(database_group, ctx)
    register_ai(ai_group, ctx)
    register_embed(embed_group, ctx)
    register_roles(commandguard_group, ctx, top_level="commandguard", visual_top_level="commandguard")
    register_stt(stt_group, ctx, root_top_level="audio")
    register_translate(translate_group, ctx, root_top_level="audio")
    register_audio_notes(audio_group, ctx, root_top_level="audio")
    register_messaggi(campaigns_group, ctx, top_level="campaigns", visual_top_level="campaigns")
    register_voice_ingest(voice_ingest_group, ctx, root_top_level="audio")
    register_privacy(privacy_group, ctx, top_level="privacy", visual_top_level="privacy")
    register_barcello(barcellosummary_group, bot.tree, guild_obj, ctx, root_top_level="barcellosummary")
    register_riassunto(dmsummary_group, ctx, root_top_level="dmsummary")
    register_riassunto(riassunto_alias_group, ctx, root_top_level="riassunto")
    register_aura(aurasummary_group, ctx, root_top_level="aurasummary")
    register_aura(aura_alias_group, ctx, root_top_level="aura")
    register_attivita(attivita_group, ctx, root_top_level="attivita")

    register_inattivi(inactivity_group, ctx, top_level="inactivity", visual_top_level="inactivity")
    register_greetings(greetings_group, ctx, top_level="greetings", visual_top_level="greetings")
    register_moderazione_utenti(users_group, ctx, top_level="users", visual_top_level="users")

    register_resoconto(channelsummary_group, serversummary_group, ctx, channel_root="channelsummary", server_root="serversummary")
    register_resoconto(
        resocontocanale_alias_group,
        resocontoserver_alias_group,
        ctx,
        channel_root="resocontocanale",
        server_root="resocontoserver",
    )
    register_triggers(triggers_group, campaigns_group, qna_group, insights_group, ctx, triggers_root="triggers")
    register_ask(bot.tree, guild_obj, ctx, command_name="domanda", root_top_level="qna", visual_top_level="domanda")

    logger.info(
        "Group children summary database=%d campaigns=%d qna=%d triggers=%d ai=%d",
        len(database_group.commands),
        len(campaigns_group.commands),
        len(qna_group.commands),
        len(triggers_group.commands),
        len(ai_group.commands),
    )

    root_commands: list[app_commands.Command | app_commands.Group] = [
        status_group,
        database_group,
        ai_group,
        commandguard_group,
        audio_group,
        campaigns_group,
        qna_group,
        triggers_group,
        embed_group,
        privacy_group,
        users_group,
        greetings_group,
        inactivity_group,
        channelsummary_group,
        serversummary_group,
        dmsummary_group,
        aurasummary_group,
        barcellosummary_group,
        riassunto_alias_group,
        aura_alias_group,
        resocontocanale_alias_group,
        resocontoserver_alias_group,
        attivita_group,
    ]

    def add_tree_command(command: app_commands.Command | app_commands.Group) -> None:
        if use_guild:
            bot.tree.add_command(command, guild=guild_obj)
        else:
            bot.tree.add_command(command)

    for command in root_commands:
        add_tree_command(command)

    scope_label = "guild" if guild_obj else "global"
    top_level = bot.tree.get_commands(guild=guild_obj) if guild_obj else bot.tree.get_commands()
    logger.info("Registered commands scope=%s top_level=%s", scope_label, [c.qualified_name for c in top_level])

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
