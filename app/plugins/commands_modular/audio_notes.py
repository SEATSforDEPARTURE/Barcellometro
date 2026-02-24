from __future__ import annotations

import os

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.settings import get_setting, set_setting


def register_audio_notes(audio_notes_group: app_commands.Group, ctx: CommandContext) -> None:
    @audio_notes_group.command(name="on", description="Abilita le note vocali")
    async def audio_notes_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.audio_notes.on", ctx):
            return
        await set_setting(ctx, "audio_notes.enabled", "true")
        await interaction.response.send_message("Note vocali abilitate.", ephemeral=True)

    @audio_notes_group.command(name="off", description="Disabilita le note vocali")
    async def audio_notes_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.audio_notes.off", ctx):
            return
        await set_setting(ctx, "audio_notes.enabled", "false")
        await interaction.response.send_message("Note vocali disabilitate.", ephemeral=True)

    @audio_notes_group.command(name="status", description="Mostra lo stato note vocali")
    async def audio_notes_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.audio_notes.status", ctx):
            return
        enabled = (await get_setting(ctx, "audio_notes.enabled", "false")).lower() in {"1", "true", "yes", "y"}
        max_mb = await get_setting(ctx, "audio_notes.max_mb", os.getenv("AUDIO_NOTES_MAX_MB", "25"))
        max_duration = await get_setting(
            ctx,
            "audio_notes.max_duration_s",
            os.getenv("AUDIO_NOTES_MAX_DURATION_S", "180"),
        )
        max_chars = await get_setting(
            ctx,
            "audio_notes.discord_max_chars",
            os.getenv("AUDIO_NOTES_DISCORD_MAX_CHARS", "1900"),
        )
        queue_max = await get_setting(ctx, "audio_notes.queue_max", os.getenv("AUDIO_NOTES_QUEUE_MAX", "50"))
        await interaction.response.send_message(
            "Audio notes "
            f"{'attivo' if enabled else 'disattivo'} | "
            f"max_mb={max_mb}, max_duration_s={max_duration}, max_chars={max_chars}, queue_max={queue_max}",
            ephemeral=True,
        )

    @audio_notes_group.command(name="limits", description="Imposta i limiti note vocali")
    @app_commands.describe(
        max_mb="Massimo MB",
        max_duration_s="Durata massima in secondi",
        discord_max_chars="Max caratteri msg",
        queue_max="Dimensione coda",
    )
    async def audio_notes_limits_command(
        interaction: discord.Interaction,
        max_mb: int,
        max_duration_s: int,
        discord_max_chars: int,
        queue_max: int,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.audio_notes.limits", ctx):
            return
        if max_mb <= 0 or max_duration_s <= 0 or discord_max_chars <= 0 or queue_max <= 0:
            await interaction.response.send_message("Specifica limiti validi (> 0).", ephemeral=True)
            return
        await set_setting(ctx, "audio_notes.max_mb", str(max_mb))
        await set_setting(ctx, "audio_notes.max_duration_s", str(max_duration_s))
        await set_setting(ctx, "audio_notes.discord_max_chars", str(discord_max_chars))
        await set_setting(ctx, "audio_notes.queue_max", str(queue_max))
        await interaction.response.send_message("Limiti note vocali aggiornati.", ephemeral=True)
