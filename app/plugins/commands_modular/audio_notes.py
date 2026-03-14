from __future__ import annotations

import os

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.settings import get_setting, set_setting


def register_audio_notes(audio_notes_group: app_commands.Group, ctx: CommandContext) -> None:
    async def _limits_values() -> tuple[str, str, str, str, str]:
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
        chars_summary = await get_setting(ctx, "audio_notes.chars_summary", "")
        chars_summary_value = chars_summary if chars_summary and chars_summary.strip() else "off"
        return max_mb, max_duration, max_chars, queue_max, chars_summary_value

    @audio_notes_group.command(name="on", description="Abilita le note vocali")
    async def audio_notes_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.audio_notes.on", ctx):
            return
        await set_setting(ctx, "audio_notes.enabled", "true")
        await interaction.response.send_message("Note vocali abilitate.", ephemeral=True)

    @audio_notes_group.command(name="off", description="Disabilita le note vocali")
    async def audio_notes_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.audio_notes.off", ctx):
            return
        await set_setting(ctx, "audio_notes.enabled", "false")
        await interaction.response.send_message("Note vocali disabilitate.", ephemeral=True)

    @audio_notes_group.command(name="status", description="Mostra lo stato note vocali")
    async def audio_notes_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.audio_notes.status", ctx):
            return
        enabled = (await get_setting(ctx, "audio_notes.enabled", "false")).lower() in {"1", "true", "yes", "y"}
        max_mb, max_duration, max_chars, queue_max, chars_summary = await _limits_values()
        await interaction.response.send_message(
            "Audio notes "
            f"{'attivo' if enabled else 'disattivo'} | "
            f"max_mb={max_mb}, max_duration_s={max_duration}, max_chars={max_chars}, queue_max={queue_max}, chars_summary={chars_summary}",
            ephemeral=True,
        )

    @audio_notes_group.command(name="limits", description="Imposta i limiti note vocali")
    @app_commands.describe(
        max_mb="Massimo MB",
        max_duration_s="Durata massima in secondi",
        discord_max_chars="Max caratteri msg",
        queue_max="Dimensione coda",
        chars_summary="Soglia caratteri oltre la quale generare il riassunto AI (0 o vuoto = disattivo)",
    )
    async def audio_notes_limits_command(
        interaction: discord.Interaction,
        max_mb: int | None = None,
        max_duration_s: int | None = None,
        discord_max_chars: int | None = None,
        queue_max: int | None = None,
        chars_summary: int | None = None,
    ) -> None:
        if not await check_permission(interaction, "bm.audio_notes.limits", ctx):
            return

        if all(value is None for value in [max_mb, max_duration_s, discord_max_chars, queue_max, chars_summary]):
            current_max_mb, current_max_duration, current_max_chars, current_queue_max, current_chars_summary = await _limits_values()
            await interaction.response.send_message(
                "Valori correnti audio notes | "
                f"max_mb={current_max_mb}, max_duration_s={current_max_duration}, "
                f"max_chars={current_max_chars}, queue_max={current_queue_max}, chars_summary={current_chars_summary}",
                ephemeral=True,
            )
            return

        positive_limits = {
            "max_mb": max_mb,
            "max_duration_s": max_duration_s,
            "discord_max_chars": discord_max_chars,
            "queue_max": queue_max,
        }
        if any(value is not None and value <= 0 for value in positive_limits.values()):
            await interaction.response.send_message("Specifica limiti validi (> 0).", ephemeral=True)
            return

        if max_mb is not None:
            await set_setting(ctx, "audio_notes.max_mb", str(max_mb))
        if max_duration_s is not None:
            await set_setting(ctx, "audio_notes.max_duration_s", str(max_duration_s))
        if discord_max_chars is not None:
            await set_setting(ctx, "audio_notes.discord_max_chars", str(discord_max_chars))
        if queue_max is not None:
            await set_setting(ctx, "audio_notes.queue_max", str(queue_max))
        if chars_summary is not None:
            await set_setting(ctx, "audio_notes.chars_summary", "" if chars_summary <= 0 else str(chars_summary))

        current_max_mb, current_max_duration, current_max_chars, current_queue_max, current_chars_summary = await _limits_values()
        summary_status = "attivo" if current_chars_summary != "off" else "disattivo"
        await interaction.response.send_message(
            "Limiti note vocali aggiornati | "
            f"max_mb={current_max_mb}, max_duration_s={current_max_duration}, "
            f"max_chars={current_max_chars}, queue_max={current_queue_max}, "
            f"chars_summary={current_chars_summary} ({summary_status})",
            ephemeral=True,
        )
