from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import discord
from discord import app_commands

from app.services.ingest import EventEnvelope
from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.settings import get_setting, set_setting
from app.plugins.commands_modular.voice_ingest import voice_ingest_key
from app.shared.discord.command_embeds import CommandEmbedSection, send_standard_response

PRIVACY_ALIASES = ("bm.privacy.on", "bm.privacy.off", "bm.privacy.status")


def register_privacy(privacy_group: app_commands.Group, ctx: CommandContext) -> None:
    async def resolve_voice_channel(interaction: discord.Interaction, voice_channel: discord.VoiceChannel | None) -> discord.VoiceChannel | None:
        if voice_channel is not None:
            return voice_channel
        if isinstance(interaction.user, discord.Member) and interaction.user.voice:
            return interaction.user.voice.channel
        return None

    async def resolve_affected_bots(voice_channel: discord.VoiceChannel) -> list[int]:
        bot_ids = {member.id for member in voice_channel.members if member.bot}
        if not bot_ids:
            bot_ids.update(int(bot_id) for bot_id in await ctx.database.find_voice_ingest_bots_for_voice_channel(str(voice_channel.id)) if bot_id.isdigit())
        return sorted(bot_ids)

    async def emit_privacy_event(interaction: discord.Interaction, event_type: str, voice_channel: discord.VoiceChannel, affected_bot_ids: list[int]) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        session_id: str | None = None
        lookup_failed = False
        if interaction.guild_id is not None:
            session = await ctx.database.get_active_voice_session(str(interaction.guild_id), str(voice_channel.id))
            if session is not None:
                session_id = session["voice_session_id"]
            else:
                lookup_failed = True
        else:
            lookup_failed = True
        meta: dict[str, object] = {"voice_channel_id": str(voice_channel.id), "affected_bot_ids": affected_bot_ids}
        if session_id is not None:
            meta["voice_session_id"] = session_id
        if lookup_failed:
            meta["session_lookup_failed"] = True
        await ctx.ingest.emit(
            EventEnvelope(
                event_id=str(uuid4()),
                event_type=event_type,
                platform="discord",
                ts=ts,
                guild_id=str(interaction.guild_id) if interaction.guild_id else None,
                channel_id=str(voice_channel.id),
                thread_id=None,
                author_id=str(interaction.user.id),
                content=None,
                meta=meta,
            )
        )

    async def _send_privacy_error(interaction: discord.Interaction, subcommand: str, message: str) -> None:
        await send_standard_response(interaction, top_level="bm", subcommand_path=f"privacy {subcommand}", lines=[("error", message)], kind="error", footer_service=ctx.footer)

    @privacy_group.command(name="on", description="Enable voice privacy.")
    @app_commands.describe(voice_channel="Optional voice channel. Defaults to your current voice channel.")
    async def privacy_on(interaction: discord.Interaction, voice_channel: discord.VoiceChannel | None = None) -> None:
        if not await check_permission(interaction, "privacy.on", ctx, legacy_aliases=PRIVACY_ALIASES):
            return
        resolved_voice = await resolve_voice_channel(interaction, voice_channel)
        if resolved_voice is None:
            await _send_privacy_error(interaction, "on", "Select a voice channel first.")
            return
        bot_ids = await resolve_affected_bots(resolved_voice)
        if not bot_ids:
            await _send_privacy_error(interaction, "on", "No configured bot was found for this voice channel.")
            return
        for bot_id in bot_ids:
            await set_setting(ctx, voice_ingest_key(bot_id, "privacy_mode"), "true")
            await set_setting(ctx, voice_ingest_key(bot_id, "auto_join"), "false")
            await set_setting(ctx, voice_ingest_key(bot_id, "enabled"), "true")
        await emit_privacy_event(interaction, "voice.privacy_on", resolved_voice, bot_ids)
        if ctx.voice_ingest and ctx.bot.user and ctx.bot.user.id in bot_ids:
            await ctx.voice_ingest.leave()
        await send_standard_response(interaction, top_level="bm", subcommand_path="privacy on", lines=[("voice_channel", resolved_voice.name), ("affected_bots", len(bot_ids)), ("privacy", "enabled")], kind="success", footer_service=ctx.footer)

    @privacy_group.command(name="off", description="Disable voice privacy.")
    @app_commands.describe(voice_channel="Optional voice channel. Defaults to your current voice channel.")
    async def privacy_off(interaction: discord.Interaction, voice_channel: discord.VoiceChannel | None = None) -> None:
        if not await check_permission(interaction, "privacy.off", ctx, legacy_aliases=PRIVACY_ALIASES):
            return
        resolved_voice = await resolve_voice_channel(interaction, voice_channel)
        if resolved_voice is None:
            await _send_privacy_error(interaction, "off", "Select a voice channel first.")
            return
        bot_ids = await resolve_affected_bots(resolved_voice)
        if not bot_ids:
            await _send_privacy_error(interaction, "off", "No configured bot was found for this voice channel.")
            return
        for bot_id in bot_ids:
            await set_setting(ctx, voice_ingest_key(bot_id, "privacy_mode"), "false")
            await set_setting(ctx, voice_ingest_key(bot_id, "auto_join"), "true")
            await set_setting(ctx, voice_ingest_key(bot_id, "enabled"), "true")
        await emit_privacy_event(interaction, "voice.privacy_off", resolved_voice, bot_ids)
        non_bot_members = [member for member in resolved_voice.members if not member.bot]
        if ctx.voice_ingest and ctx.bot.user and ctx.bot.user.id in bot_ids and non_bot_members:
            await ctx.voice_ingest.join(resolved_voice)
        await send_standard_response(interaction, top_level="bm", subcommand_path="privacy off", lines=[("voice_channel", resolved_voice.name), ("affected_bots", len(bot_ids)), ("privacy", "disabled")], kind="success", footer_service=ctx.footer)

    @privacy_group.command(name="status", description="Show the current voice privacy status.")
    @app_commands.describe(voice_channel="Optional voice channel. Defaults to your current voice channel.")
    async def privacy_status(interaction: discord.Interaction, voice_channel: discord.VoiceChannel | None = None) -> None:
        if not await check_permission(interaction, "privacy.status", ctx, legacy_aliases=PRIVACY_ALIASES):
            return
        resolved_voice = await resolve_voice_channel(interaction, voice_channel)
        if resolved_voice is None:
            await _send_privacy_error(interaction, "status", "Select a voice channel first.")
            return
        bot_ids = await resolve_affected_bots(resolved_voice)
        if not bot_ids:
            await _send_privacy_error(interaction, "status", "No configured bot was found for this voice channel.")
            return
        states = []
        for bot_id in bot_ids:
            privacy_mode = (await get_setting(ctx, voice_ingest_key(bot_id, "privacy_mode"), "false")).lower() in {"1", "true", "yes", "y"}
            auto_join = (await get_setting(ctx, voice_ingest_key(bot_id, "auto_join"), "true")).lower() in {"1", "true", "yes", "y"}
            enabled = (await get_setting(ctx, voice_ingest_key(bot_id, "enabled"), "true")).lower() in {"1", "true", "yes", "y"}
            states.append((bot_id, privacy_mode, auto_join, enabled))
        privacy_values = {state[1] for state in states}
        last_event = await ctx.database.get_last_privacy_event(str(resolved_voice.id))
        last_change = "N/A"
        if last_event:
            actor = f"<@{last_event['actor_id']}>" if last_event.get("actor_id") else "unknown"
            last_change = f"{last_event['event_type']} at {last_event['ts']} by {actor}"
        lines = [("voice_channel", resolved_voice.name), ("bots", len(bot_ids)), ("last_change", last_change)]
        sections = [
            CommandEmbedSection(
                title="Details",
                lines=[(f"bot_{bot_id}", f"privacy={'ON' if privacy else 'OFF'}, auto_join={auto_join}, enabled={enabled}") for bot_id, privacy, auto_join, enabled in states],
            )
        ]
        if len(privacy_values) == 1:
            lines.insert(1, ("privacy", "ON" if True in privacy_values else "OFF"))
        else:
            lines.insert(1, ("privacy", "MIXED"))
        await send_standard_response(interaction, top_level="bm", subcommand_path="privacy status", lines=lines, sections=sections, footer_service=ctx.footer)
