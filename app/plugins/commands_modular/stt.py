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
MODEL_CHOICES = [
    app_commands.Choice(name="small", value="small"),
    app_commands.Choice(name="medium", value="medium"),
    app_commands.Choice(name="large-v3", value="large-v3"),
]
COMPUTE_CHOICES = [
    app_commands.Choice(name="int8", value="int8"),
    app_commands.Choice(name="int8_float16", value="int8_float16"),
    app_commands.Choice(name="float16", value="float16"),
]
BEAM_CHOICES = [
    app_commands.Choice(name="1", value="1"),
    app_commands.Choice(name="3", value="3"),
    app_commands.Choice(name="5", value="5"),
]
LANGUAGE_CHOICES = [
    app_commands.Choice(name="auto", value="auto"),
    app_commands.Choice(name="it", value="it"),
]


async def _stt_config_lines(ctx: CommandContext) -> list[str]:
    return [
        f"backend: {await get_setting(ctx, 'stt.backend', 'local')}",
        f"model: {await get_setting(ctx, 'stt.local.model', 'small')}",
        f"compute: {await get_setting(ctx, 'stt.local.compute_type', 'int8')}",
        f"beam: {await get_setting(ctx, 'stt.local.beam_size', '1')}",
        f"language: {await get_setting(ctx, 'stt.local.language_hint', 'auto')}",
    ]


def register_stt(stt_group: app_commands.Group, ctx: CommandContext) -> None:
    @stt_group.command(name="config_set", description="Update the STT configuration.")
    @app_commands.describe(
        backend="STT backend.",
        model="Local STT model.",
        compute="Local STT compute type.",
        beam="Local STT beam size.",
        language="Default language hint.",
    )
    @app_commands.choices(
        backend=BACKEND_CHOICES,
        model=MODEL_CHOICES,
        compute=COMPUTE_CHOICES,
        beam=BEAM_CHOICES,
        language=LANGUAGE_CHOICES,
    )
    async def stt_config_set_command(
        interaction: discord.Interaction,
        backend: app_commands.Choice[str] | None = None,
        model: app_commands.Choice[str] | None = None,
        compute: app_commands.Choice[str] | None = None,
        beam: app_commands.Choice[str] | None = None,
        language: app_commands.Choice[str] | None = None,
    ) -> None:
        if not await check_permission(
            interaction,
            "bm.stt.config_set",
            ctx,
            legacy_aliases=["bm.stt.backend", "bm.stt.model", "bm.stt.compute", "bm.stt.beam", "bm.stt.language"],
        ):
            return
        if all(value is None for value in (backend, model, compute, beam, language)):
            await send_standard_response(
                interaction,
                top_level="bm",
                subcommand_path="stt config_set",
                lines=[("error", "No changes provided. Use /bm stt config_show to inspect the current configuration.")],
                kind="error",
                footer_service=ctx.footer,
            )
            return

        if backend is not None:
            await set_setting(ctx, "stt.backend", backend.value)
        if model is not None:
            await set_setting(ctx, "stt.local.model", model.value)
        if compute is not None:
            await set_setting(ctx, "stt.local.compute_type", compute.value)
        if beam is not None:
            await set_setting(ctx, "stt.local.beam_size", beam.value)
        if language is not None:
            await set_setting(ctx, "stt.local.language_hint", language.value)

        await send_standard_response(
            interaction,
            top_level="bm",
            subcommand_path="stt config_set",
            lines=[("result", "updated")],
            sections=[{"title": "Configuration", "lines": await _stt_config_lines(ctx)}],
            kind="success",
            footer_service=ctx.footer,
        )

    @stt_group.command(name="config_show", description="Show the STT configuration.")
    async def stt_config_show_command(interaction: discord.Interaction) -> None:
        if not await check_permission(
            interaction,
            "bm.stt.config_show",
            ctx,
            legacy_aliases=["bm.stt.backend", "bm.stt.model", "bm.stt.compute", "bm.stt.beam", "bm.stt.language"],
        ):
            return
        await send_standard_response(
            interaction,
            top_level="bm",
            subcommand_path="stt config_show",
            sections=[{"title": "Configuration", "lines": await _stt_config_lines(ctx)}],
            footer_service=ctx.footer,
        )

    @stt_group.command(name="config_reset", description="Reset the STT configuration to defaults.")
    async def stt_config_reset_command(interaction: discord.Interaction) -> None:
        if not await check_permission(
            interaction,
            "bm.stt.config_reset",
            ctx,
            legacy_aliases=["bm.stt.backend", "bm.stt.model", "bm.stt.compute", "bm.stt.beam", "bm.stt.language"],
        ):
            return
        for key in (
            "stt.backend",
            "stt.local.model",
            "stt.local.compute_type",
            "stt.local.beam_size",
            "stt.local.language_hint",
        ):
            await reset_setting(ctx, key)
        await send_standard_response(
            interaction,
            top_level="bm",
            subcommand_path="stt config_reset",
            lines=[("result", "reset")],
            sections=[{"title": "Configuration", "lines": await _stt_config_lines(ctx)}],
            kind="success",
            footer_service=ctx.footer,
        )
