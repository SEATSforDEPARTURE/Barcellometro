from __future__ import annotations

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.settings import get_setting, reset_setting, set_setting
from app.utils.command_embeds import send_standard_response

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


def register_translate(translate_group: app_commands.Group, ctx: CommandContext) -> None:
    @translate_group.command(name="config_set", description="Update the translation configuration.")
    @app_commands.describe(
        backend="Translation backend.",
        target="Default target language.",
    )
    @app_commands.choices(backend=BACKEND_CHOICES, target=TARGET_CHOICES)
    async def translate_config_set_command(
        interaction: discord.Interaction,
        backend: app_commands.Choice[str] | None = None,
        target: app_commands.Choice[str] | None = None,
    ) -> None:
        if not await check_permission(
            interaction,
            "bm.translate.config_set",
            ctx,
            legacy_aliases=["bm.translate.backend", "bm.translate.target"],
        ):
            return
        if backend is None and target is None:
            await send_standard_response(
                interaction,
                top_level="bm",
                subcommand_path="translate config_set",
                lines=[("error", "No changes provided. Use /bm translate config_show to inspect the current configuration.")],
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
            top_level="bm",
            subcommand_path="translate config_set",
            lines=[("result", "updated")],
            sections=[{"title": "Configuration", "lines": await _translate_config_lines(ctx)}],
            kind="success",
            footer_service=ctx.footer,
        )

    @translate_group.command(name="config_show", description="Show the translation configuration.")
    async def translate_config_show_command(interaction: discord.Interaction) -> None:
        if not await check_permission(
            interaction,
            "bm.translate.config_show",
            ctx,
            legacy_aliases=["bm.translate.backend", "bm.translate.target"],
        ):
            return
        await send_standard_response(
            interaction,
            top_level="bm",
            subcommand_path="translate config_show",
            sections=[{"title": "Configuration", "lines": await _translate_config_lines(ctx)}],
            footer_service=ctx.footer,
        )

    @translate_group.command(name="config_reset", description="Reset the translation configuration to defaults.")
    async def translate_config_reset_command(interaction: discord.Interaction) -> None:
        if not await check_permission(
            interaction,
            "bm.translate.config_reset",
            ctx,
            legacy_aliases=["bm.translate.backend", "bm.translate.target"],
        ):
            return
        for key in ("translate.backend", "translate.target_lang"):
            await reset_setting(ctx, key)
        await send_standard_response(
            interaction,
            top_level="bm",
            subcommand_path="translate config_reset",
            lines=[("result", "reset")],
            sections=[{"title": "Configuration", "lines": await _translate_config_lines(ctx)}],
            kind="success",
            footer_service=ctx.footer,
        )
