from __future__ import annotations

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.settings import set_setting


def voice_ingest_key(bot_id: int, key: str) -> str:
    return f"voice_ingest.{bot_id}.{key}"


def register_voice_ingest(voice_ingest_group: app_commands.Group, ctx: CommandContext) -> None:
    @voice_ingest_group.command(name="join", description="Join manuale del canale vocale")
    @app_commands.describe(voice_channel="Canale vocale")
    async def voice_ingest_join(
        interaction: discord.Interaction,
        voice_channel: discord.VoiceChannel,
    ) -> None:
        if not await check_permission(interaction, "bm.voice_ingest.join", ctx):
            return
        if not ctx.bot.user:
            await interaction.response.send_message("Bot non pronto.", ephemeral=True)
            return
        await set_setting(ctx, voice_ingest_key(ctx.bot.user.id, "target_voice_channel_id"), str(voice_channel.id))
        await interaction.response.send_message(
            f"Richiesto join su {voice_channel.name}.",
            ephemeral=True,
        )
        if ctx.voice_ingest:
            await ctx.voice_ingest.join(voice_channel)

    @voice_ingest_group.command(name="leave", description="Leave manuale del canale vocale")
    async def voice_ingest_leave(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.voice_ingest.leave", ctx):
            return
        await interaction.response.send_message("Richiesto leave dal canale vocale.", ephemeral=True)
        if ctx.voice_ingest:
            await ctx.voice_ingest.leave()
