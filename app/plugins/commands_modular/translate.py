from __future__ import annotations

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.settings import get_setting, reset_setting, set_setting
from app.shared.discord.command_embeds import send_standard_response

BACKEND_CHOICES = [
    app_commands.Choice(name="local", value="local"),
    app_commands.Choice(name="ai", value="ai"),
]
TARGET_CHOICES = [app_commands.Choice(name="it", value="it")]


async def _translate_config_lines(ctx: CommandContext) -> list[str]:
    return [
        f"backend: {await get_setting(ctx, 'translate.backend', 'local')}",
        f"target: {await get_setting(ctx, 'translate.target_lang', 'it')}",
    ]


def register_translate(translate_group: app_commands.Group, ctx: CommandContext, *, root_top_level: str = "audio") -> None:
    @translate_group.command(name="translate_set", description="Update the clip translation configuration.")
    @app_commands.describe(
        backend="Translation backend.",
        target="Default target language.",
    )
    @app_commands.choices(backend=BACKEND_CHOICES, target=TARGET_CHOICES)
    async def translate_set_command(
        interaction: discord.Interaction,
        backend: app_commands.Choice[str] | None = None,
        target: app_commands.Choice[str] | None = None,
    ) -> None:
        if not await check_permission(interaction, "audio.clips.translate_set", ctx):
            return
        if backend is None and target is None:
            await send_standard_response(
                interaction,
                top_level=root_top_level,
                subcommand_path="audio clips translate_set",
                visual_top_level="audio",
                lines=[("error", "No changes provided. Use /audio clips translate_show to inspect the current configuration.")],
                kind="error",
                footer_service=ctx.footer,
            )
            return
        if backend is not None:
            await set_setting(ctx, "translate.backend", backend.value)
        if target is not None:
            await set_setting(ctx, "translate.target_lang", target.value)
        await send_standard_response(
            interaction,
            top_level=root_top_level,
            subcommand_path="audio clips translate_set",
            visual_top_level="audio",
            lines=[("result", "updated")],
            sections=[{"title": "Configuration", "lines": await _translate_config_lines(ctx)}],
            kind="success",
            footer_service=ctx.footer,
        )

    @translate_group.command(name="translate_show", description="Show the clip translation configuration.")
    async def translate_show_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "audio.clips.translate_show", ctx):
            return
        await send_standard_response(
            interaction,
            top_level=root_top_level,
            subcommand_path="audio clips translate_show",
            visual_top_level="audio",
            sections=[{"title": "Configuration", "lines": await _translate_config_lines(ctx)}],
            footer_service=ctx.footer,
        )

    @translate_group.command(name="translate_reset", description="Reset the clip translation configuration to domain defaults.")
    async def translate_reset_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "audio.clips.translate_reset", ctx):
            return
        for key in ("translate.backend", "translate.target_lang"):
            await reset_setting(ctx, key)
        await send_standard_response(
            interaction,
            top_level=root_top_level,
            subcommand_path="audio clips translate_reset",
            visual_top_level="audio",
            lines=[("result", "reset")],
            sections=[{"title": "Configuration", "lines": await _translate_config_lines(ctx)}],
            kind="success",
            footer_service=ctx.footer,
        )
