from __future__ import annotations

import os

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.settings import get_setting, reset_setting, set_setting


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

    async def _config_message() -> str:
        enabled = (await get_setting(ctx, "audio_notes.enabled", "false")).lower() in {"1", "true", "yes", "y"}
        max_mb, max_duration, max_chars, queue_max, chars_summary = await _limits_values()
        return (
            f"enabled: {'on' if enabled else 'off'}\n"
            f"max_mb: {max_mb}\n"
            f"max_duration_s: {max_duration}\n"
            f"discord_max_chars: {max_chars}\n"
            f"queue_max: {queue_max}\n"
            f"chars_summary: {chars_summary}"
        )

    @audio_notes_group.command(name="on", description="Enable audio notes.")
    async def audio_notes_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.audionotes.on", ctx, legacy_aliases=["bm.audio_notes.on"]):
            return
        await set_setting(ctx, "audio_notes.enabled", "true")
        await interaction.response.send_message("Audio notes enabled.", ephemeral=True)

    @audio_notes_group.command(name="off", description="Disable audio notes.")
    async def audio_notes_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.audionotes.off", ctx, legacy_aliases=["bm.audio_notes.off"]):
            return
        await set_setting(ctx, "audio_notes.enabled", "false")
        await interaction.response.send_message("Audio notes disabled.", ephemeral=True)

    @audio_notes_group.command(name="status", description="Show the audio notes status.")
    async def audio_notes_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.audionotes.status", ctx, legacy_aliases=["bm.audio_notes.status"]):
            return
        await interaction.response.send_message("Audio notes status\n" + await _config_message(), ephemeral=True)

    @audio_notes_group.command(name="config_set", description="Update the audio notes configuration.")
    @app_commands.describe(
        max_mb="Maximum allowed upload size in MB.",
        max_duration_s="Maximum audio duration in seconds.",
        discord_max_chars="Maximum characters per Discord message.",
        queue_max="Maximum queued jobs.",
        chars_summary="Character threshold for AI summary generation. Use 0 to disable.",
    )
    async def audio_notes_config_set_command(
        interaction: discord.Interaction,
        max_mb: int | None = None,
        max_duration_s: int | None = None,
        discord_max_chars: int | None = None,
        queue_max: int | None = None,
        chars_summary: int | None = None,
    ) -> None:
        if not await check_permission(
            interaction,
            "bm.audionotes.config_set",
            ctx,
            legacy_aliases=["bm.audio_notes.limits"],
        ):
            return

        if all(value is None for value in [max_mb, max_duration_s, discord_max_chars, queue_max, chars_summary]):
            await interaction.response.send_message(
                "No changes provided. Use /bm audionotes config_show to inspect the current configuration.",
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
            await interaction.response.send_message("Please provide valid limits greater than 0.", ephemeral=True)
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

        await interaction.response.send_message(
            "Audio notes configuration updated.\n" + await _config_message(),
            ephemeral=True,
        )

    @audio_notes_group.command(name="config_show", description="Show the audio notes configuration.")
    async def audio_notes_config_show_command(interaction: discord.Interaction) -> None:
        if not await check_permission(
            interaction,
            "bm.audionotes.config_show",
            ctx,
            legacy_aliases=["bm.audio_notes.limits"],
        ):
            return
        await interaction.response.send_message("Audio notes configuration\n" + await _config_message(), ephemeral=True)

    @audio_notes_group.command(name="config_reset", description="Reset the audio notes configuration to defaults.")
    async def audio_notes_config_reset_command(interaction: discord.Interaction) -> None:
        if not await check_permission(
            interaction,
            "bm.audionotes.config_reset",
            ctx,
            legacy_aliases=["bm.audio_notes.limits"],
        ):
            return
        for key in (
            "audio_notes.max_mb",
            "audio_notes.max_duration_s",
            "audio_notes.discord_max_chars",
            "audio_notes.queue_max",
            "audio_notes.chars_summary",
        ):
            await reset_setting(ctx, key)
        await interaction.response.send_message(
            "Audio notes configuration reset.\n" + await _config_message(),
            ephemeral=True,
        )
