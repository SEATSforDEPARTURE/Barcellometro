from __future__ import annotations

import os

import discord
from discord import app_commands

from app.shared.discord.command_embeds import send_legacy_standard_response
from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.settings import get_setting, reset_setting, set_setting


async def _send_legacy(interaction: discord.Interaction, ctx: CommandContext, **kwargs) -> None:
    await send_legacy_standard_response(interaction, footer_service=ctx.footer, **kwargs)


def register_audio_notes(audio_notes_group: app_commands.Group, ctx: CommandContext, *, root_top_level: str = "audio") -> None:
    async def _config_lines() -> list[tuple[str, object]]:
        enabled = (await get_setting(ctx, "audio_notes.enabled", "false")).lower() in {"1", "true", "yes", "y"}
        max_mb = await get_setting(ctx, "audio_notes.max_mb", os.getenv("AUDIO_NOTES_MAX_MB", "25"))
        max_duration = await get_setting(ctx, "audio_notes.max_duration_s", os.getenv("AUDIO_NOTES_MAX_DURATION_S", "180"))
        max_chars = await get_setting(ctx, "audio_notes.discord_max_chars", os.getenv("AUDIO_NOTES_DISCORD_MAX_CHARS", "1900"))
        queue_max = await get_setting(ctx, "audio_notes.queue_max", os.getenv("AUDIO_NOTES_QUEUE_MAX", "50"))
        chars_summary = await get_setting(ctx, "audio_notes.chars_summary", "")
        chars_summary_value = chars_summary if chars_summary and chars_summary.strip() else "off"
        return max_mb, max_duration, max_chars, queue_max, chars_summary_value

    @audio_notes_group.command(name="on", description="Enable audio notes.")
    async def audio_notes_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.audionotes.on", ctx):
            return
        await set_setting(ctx, "audio_notes.enabled", "true")
        await _send_legacy(interaction, ctx,
            top_level=root_top_level,
            path_parts=["audionotes", "on"],
            entries=[("Status", "enabled")],
            tone="success",
            service_name="audio_notes",
        )

    @audio_notes_group.command(name="off", description="Disable audio notes.")
    async def audio_notes_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.audionotes.off", ctx):
            return
        await set_setting(ctx, "audio_notes.enabled", "false")
        await _send_legacy(interaction, ctx,
            top_level=root_top_level,
            path_parts=["audionotes", "off"],
            entries=[("Status", "disabled")],
            tone="success",
            service_name="audio_notes",
        )

    @audio_notes_group.command(name="status", description="Show the audio notes status.")
    async def audio_notes_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.audionotes.status", ctx):
            return
        max_mb, max_duration, max_chars, queue_max, chars_summary = await _config_lines()
        enabled = (await get_setting(ctx, "audio_notes.enabled", "false")).lower() in {"1", "true", "yes", "y"}
        await _send_legacy(interaction, ctx,
            top_level=root_top_level,
            path_parts=["audionotes", "status"],
            entries=[
                ("Enabled", enabled),
                ("Max Mb", max_mb),
                ("Max Duration S", max_duration),
                ("Discord Max Chars", max_chars),
                ("Queue Max", queue_max),
                ("Chars Summary", chars_summary),
            ],
            service_name="audio_notes",
        )

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
        if not await check_permission(interaction, "admin.audionotes.config_set", ctx):
            return
        if all(value is None for value in [max_mb, max_duration_s, discord_max_chars, queue_max, chars_summary]):
            await _send_legacy(interaction, ctx,
                top_level=root_top_level,
                path_parts=["audionotes", "config_set"],
                entries=[("Reason", "No changes provided")],
                tone="warning",
                sections=[("Next Step", [("Command", "/admin audionotes config_show")])],
                service_name="audio_notes",
            )
            return
        positive_limits = {"max_mb": max_mb, "max_duration_s": max_duration_s, "discord_max_chars": discord_max_chars, "queue_max": queue_max}
        if any(value is not None and value <= 0 for value in positive_limits.values()):
            await _send_legacy(interaction, ctx,
                top_level=root_top_level,
                path_parts=["audionotes", "config_set"],
                entries=[("Reason", "Provide valid limits greater than 0")],
                tone="error",
                service_name="audio_notes",
            )
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

        max_mb_value, max_duration_value, max_chars_value, queue_max_value, chars_summary_value = await _config_lines()
        await _send_legacy(interaction, ctx,
            top_level=root_top_level,
            path_parts=["audionotes", "config_set"],
            entries=[("Status", "updated")],
            tone="success",
            sections=[
                (
                    "Config",
                    [
                        ("Max Mb", max_mb_value),
                        ("Max Duration S", max_duration_value),
                        ("Discord Max Chars", max_chars_value),
                        ("Queue Max", queue_max_value),
                        ("Chars Summary", chars_summary_value),
                    ],
                )
            ],
            service_name="audio_notes",
        )

    @audio_notes_group.command(name="config_show", description="Show the audio notes configuration.")
    async def audio_notes_config_show_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.audionotes.config_show", ctx):
            return
        max_mb, max_duration, max_chars, queue_max, chars_summary = await _config_lines()
        await _send_legacy(interaction, ctx,
            top_level=root_top_level,
            path_parts=["audionotes", "config_show"],
            entries=[
                ("Max Mb", max_mb),
                ("Max Duration S", max_duration),
                ("Discord Max Chars", max_chars),
                ("Queue Max", queue_max),
                ("Chars Summary", chars_summary),
            ],
            service_name="audio_notes",
        )

    @audio_notes_group.command(name="config_reset", description="Reset the audio notes configuration to defaults.")
    async def audio_notes_config_reset_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.audionotes.config_reset", ctx):
            return
        for key in ("audio_notes.max_mb", "audio_notes.max_duration_s", "audio_notes.discord_max_chars", "audio_notes.queue_max", "audio_notes.chars_summary"):
            await reset_setting(ctx, key)
        max_mb, max_duration, max_chars, queue_max, chars_summary = await _config_lines()
        await _send_legacy(interaction, ctx,
            top_level=root_top_level,
            path_parts=["audionotes", "config_reset"],
            entries=[("Status", "reset")],
            tone="success",
            sections=[
                (
                    "Config",
                    [
                        ("Max Mb", max_mb),
                        ("Max Duration S", max_duration),
                        ("Discord Max Chars", max_chars),
                        ("Queue Max", queue_max),
                        ("Chars Summary", chars_summary),
                    ],
                )
            ],
            service_name="audio_notes",
        )
