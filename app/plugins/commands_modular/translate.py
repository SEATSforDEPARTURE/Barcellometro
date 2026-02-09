from __future__ import annotations

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.settings import set_setting


def register_translate(translate_group: app_commands.Group, ctx: CommandContext) -> None:
    @translate_group.command(name="backend", description="Imposta il backend di traduzione")
    @app_commands.choices(
        backend=[
            app_commands.Choice(name="local", value="local"),
            app_commands.Choice(name="ai", value="ai"),
        ]
    )
    async def translate_backend_command(
        interaction: discord.Interaction,
        backend: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.translate.backend", ctx):
            return
        await set_setting(ctx, "translate.backend", backend.value)
        await interaction.response.send_message(
            f"Backend traduzione impostato su {backend.value}.",
            ephemeral=True,
        )

    @translate_group.command(name="target", description="Imposta la lingua target")
    @app_commands.choices(target=[app_commands.Choice(name="it", value="it")])
    async def translate_target_command(
        interaction: discord.Interaction,
        target: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.translate.target", ctx):
            return
        await set_setting(ctx, "translate.target_lang", target.value)
        await interaction.response.send_message(
            f"Lingua target impostata su {target.value}.",
            ephemeral=True,
        )
