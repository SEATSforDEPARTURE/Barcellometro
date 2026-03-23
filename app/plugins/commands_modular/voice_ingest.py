from __future__ import annotations

import discord
from discord import app_commands

from app.shared.discord.command_embeds import send_legacy_standard_response
from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.settings import set_setting


async def _send_legacy(interaction: discord.Interaction, ctx: CommandContext, **kwargs) -> None:
    await send_legacy_standard_response(interaction, footer_service=ctx.footer, **kwargs)


def voice_ingest_key(bot_id: int, key: str) -> str:
    return f"voice_ingest.{bot_id}.{key}"


def register_voice_ingest(voice_ingest_group: app_commands.Group, ctx: CommandContext, *, root_top_level: str = "audio") -> None:
    @voice_ingest_group.command(name="join", description="Join a voice channel manually.")
    @app_commands.describe(voice_channel="Voice channel.")
    async def voice_ingest_join(interaction: discord.Interaction, voice_channel: discord.VoiceChannel) -> None:
        if not await check_permission(interaction, "admin.voice_ingest.join", ctx):
            return
        if not ctx.bot.user:
            await _send_legacy(interaction, ctx,
                top_level=root_top_level,
                path_parts=["voice_ingest", "join"],
                entries=[("Reason", "Bot non pronto")],
                tone="error",
                service_name="voice_ingest",
            )
            return
        await set_setting(ctx, voice_ingest_key(ctx.bot.user.id, "target_voice_channel_id"), str(voice_channel.id))
        await _send_legacy(interaction, ctx,
            top_level=root_top_level,
            path_parts=["voice_ingest", "join"],
            entries=[("Voice Channel", voice_channel.name), ("Status", "join requested")],
            tone="success",
            service_name="voice_ingest",
        )
        if ctx.voice_ingest:
            await ctx.voice_ingest.join(voice_channel)

    @voice_ingest_group.command(name="leave", description="Leave the current voice channel manually.")
    async def voice_ingest_leave(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.voice_ingest.leave", ctx):
            return
        await _send_legacy(interaction, ctx,
            top_level=root_top_level,
            path_parts=["voice_ingest", "leave"],
            entries=[("Status", "leave requested")],
            tone="success",
            service_name="voice_ingest",
        )
        if ctx.voice_ingest:
            await ctx.voice_ingest.leave()
