from __future__ import annotations

import os

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.settings import get_setting, reset_setting, set_setting
from app.shared.discord.command_embeds import send_legacy_standard_response


async def _send_legacy(interaction: discord.Interaction, ctx: CommandContext, **kwargs) -> None:
    kwargs.setdefault("command_description", getattr(getattr(interaction, "command", None), "description", None))
    await send_legacy_standard_response(interaction, footer_service=ctx.footer, **kwargs)


async def _limits_config_entries(ctx: CommandContext) -> list[tuple[str, object]]:
    max_mb = await get_setting(ctx, "audio_notes.max_mb", os.getenv("AUDIO_NOTES_MAX_MB", "25"))
    max_duration = await get_setting(ctx, "audio_notes.max_duration_s", os.getenv("AUDIO_NOTES_MAX_DURATION_S", "180"))
    max_chars = await get_setting(ctx, "audio_notes.discord_max_chars", os.getenv("AUDIO_NOTES_DISCORD_MAX_CHARS", "1900"))
    queue_max = await get_setting(ctx, "audio_notes.queue_max", os.getenv("AUDIO_NOTES_QUEUE_MAX", "50"))
    chars_summary = await get_setting(ctx, "audio_notes.chars_summary", "")
    chars_summary_value = chars_summary if chars_summary and chars_summary.strip() else "off"
    return [
        ("Max Mb", max_mb),
        ("Max Duration S", max_duration),
        ("Discord Max Chars", max_chars),
        ("Queue Max", queue_max),
        ("Chars Summary", chars_summary_value),
    ]


async def _stt_config_entries(ctx: CommandContext) -> list[tuple[str, object]]:
    return [
        ("Backend", await get_setting(ctx, "stt.backend", "local")),
        ("Model", await get_setting(ctx, "stt.local.model", "small")),
        ("Compute", await get_setting(ctx, "stt.local.compute_type", "int8")),
        ("Beam", await get_setting(ctx, "stt.local.beam_size", "1")),
        ("Language", await get_setting(ctx, "stt.local.language_hint", "auto")),
    ]


async def _translate_config_entries(ctx: CommandContext) -> list[tuple[str, object]]:
    return [
        ("Backend", await get_setting(ctx, "translate.backend", "local")),
        ("Target", await get_setting(ctx, "translate.target_lang", "it")),
    ]


def register_audio_notes(
    audio_group: app_commands.Group,
    ctx: CommandContext,
    *,
    root_top_level: str = "audio",
    clips_group: app_commands.Group | None = None,
) -> None:
    clips_commands_group = clips_group or audio_group

    @audio_group.command(name="on", description="Enable audio notes.")
    async def audio_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "audio.on", ctx):
            return
        await set_setting(ctx, "audio_notes.enabled", "true")
        await _send_legacy(
            interaction,
            ctx,
            top_level=root_top_level,
            path_parts=["audio", "on"],
            entries=[("Status", "enabled")],
            tone="success",
            service_name="audio_notes",
        )

    @audio_group.command(name="off", description="Disable audio notes.")
    async def audio_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "audio.off", ctx):
            return
        await set_setting(ctx, "audio_notes.enabled", "false")
        await _send_legacy(
            interaction,
            ctx,
            top_level=root_top_level,
            path_parts=["audio", "off"],
            entries=[("Status", "disabled")],
            tone="success",
            service_name="audio_notes",
        )

    @audio_group.command(name="status", description="Show the audio status.")
    async def audio_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "audio.status", ctx):
            return
        enabled = (await get_setting(ctx, "audio_notes.enabled", "false")).lower() in {"1", "true", "yes", "y"}
        await _send_legacy(
            interaction,
            ctx,
            top_level=root_top_level,
            path_parts=["audio", "status"],
            entries=[("Enabled", enabled)],
            sections=[
                ("Clips Limits", await _limits_config_entries(ctx)),
                ("Speech To Text", await _stt_config_entries(ctx)),
                ("Translation", await _translate_config_entries(ctx)),
            ],
            service_name="audio_notes",
        )

    @clips_commands_group.command(name="limits_set", description="Update the audio clip limits.")
    @app_commands.describe(
        max_mb="Maximum allowed upload size in MB.",
        max_duration_s="Maximum audio duration in seconds.",
        discord_max_chars="Maximum characters per Discord message.",
        queue_max="Maximum queued jobs.",
        chars_summary="Character threshold for AI summary generation. Use 0 to disable.",
    )
    async def audio_limits_set_command(
        interaction: discord.Interaction,
        max_mb: int | None = None,
        max_duration_s: int | None = None,
        discord_max_chars: int | None = None,
        queue_max: int | None = None,
        chars_summary: int | None = None,
    ) -> None:
        if not await check_permission(interaction, "audio.clips.limits_set", ctx):
            return
        if all(value is None for value in [max_mb, max_duration_s, discord_max_chars, queue_max, chars_summary]):
            await _send_legacy(
                interaction,
                ctx,
                top_level=root_top_level,
                path_parts=["audio", "clips", "limits_set"],
                entries=[("Reason", "No changes provided")],
                tone="warning",
                sections=[("Next Step", [("Command", "/audio clips limits_show")])],
                service_name="audio_notes",
            )
            return
        positive_limits = {
            "max_mb": max_mb,
            "max_duration_s": max_duration_s,
            "discord_max_chars": discord_max_chars,
            "queue_max": queue_max,
        }
        if any(value is not None and value <= 0 for value in positive_limits.values()):
            await _send_legacy(
                interaction,
                ctx,
                top_level=root_top_level,
                path_parts=["audio", "clips", "limits_set"],
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

        await _send_legacy(
            interaction,
            ctx,
            top_level=root_top_level,
            path_parts=["audio", "clips", "limits_set"],
            entries=[("Status", "updated")],
            tone="success",
            sections=[("Config", await _limits_config_entries(ctx))],
            service_name="audio_notes",
        )

    @clips_commands_group.command(name="limits_show", description="Show the audio clip limits.")
    async def audio_limits_show_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "audio.clips.limits_show", ctx):
            return
        await _send_legacy(
            interaction,
            ctx,
            top_level=root_top_level,
            path_parts=["audio", "clips", "limits_show"],
            entries=await _limits_config_entries(ctx),
            service_name="audio_notes",
        )

    @clips_commands_group.command(name="limits_reset", description="Reset the audio clip limits to domain defaults.")
    async def audio_limits_reset_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "audio.clips.limits_reset", ctx):
            return
        for key in ("audio_notes.max_mb", "audio_notes.max_duration_s", "audio_notes.discord_max_chars", "audio_notes.queue_max", "audio_notes.chars_summary"):
            await reset_setting(ctx, key)
        await _send_legacy(
            interaction,
            ctx,
            top_level=root_top_level,
            path_parts=["audio", "clips", "limits_reset"],
            entries=[("Status", "reset")],
            tone="success",
            sections=[("Config", await _limits_config_entries(ctx))],
            service_name="audio_notes",
        )
