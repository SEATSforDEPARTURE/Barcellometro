from __future__ import annotations

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext


def register_ask(tree: app_commands.CommandTree, guild: discord.Object, ctx: CommandContext) -> None:
    @tree.command(name="ask", description="Fai una domanda al Q&A", guild=guild)
    async def ask(interaction: discord.Interaction, domanda: str) -> None:
        if ctx.trigger_engine is None:
            await interaction.response.send_message("Servizio trigger non disponibile.", ephemeral=True)
            return
        await ctx.trigger_engine.handle_qna_question(interaction, domanda)

    @tree.command(name="domanda", description="Alias di /ask", guild=guild)
    async def domanda(interaction: discord.Interaction, domanda: str) -> None:
        if ctx.trigger_engine is None:
            await interaction.response.send_message("Servizio trigger non disponibile.", ephemeral=True)
            return
        await ctx.trigger_engine.handle_qna_question(interaction, domanda)
