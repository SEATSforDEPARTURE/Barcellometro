from __future__ import annotations

from datetime import datetime

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext


async def _handle_ask_like(interaction: discord.Interaction, ctx: CommandContext, domanda: str | None, azione: app_commands.Choice[str] | None) -> None:
    if ctx.trigger_engine is None:
        await interaction.response.send_message("Servizio trigger non disponibile.", ephemeral=True)
        return
    command_mode = (azione.value if azione else "").strip().lower()
    question_text = (domanda or "").strip()
    if command_mode == "stato" or question_text.lower() == "stato":
        if interaction.guild_id is None:
            await interaction.response.send_message("Usa questo comando in un server.", ephemeral=True)
            return
        quota = await ctx.trigger_engine.get_qna_quota_for_member(interaction.user, str(interaction.guild_id), str(interaction.channel_id) if interaction.channel_id else None)
        reset_text = quota["resets_at_iso"]
        try:
            reset_text = datetime.fromisoformat(str(quota["resets_at_iso"])).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass
        await interaction.response.send_message(
            "\n".join(
                [
                    f"Tier: {quota['tier']}",
                    f"Limite giornaliero: {quota['limit']}",
                    f"Usate oggi: {quota['used']}",
                    f"Rimanenti oggi: {quota['remaining']}",
                    f"Reset: {reset_text}",
                ]
            ),
            ephemeral=True,
        )
        return
    if not question_text:
        await interaction.response.send_message("Inserisci una domanda oppure usa azione=stato.", ephemeral=True)
        return
    await ctx.trigger_engine.handle_qna_question(interaction, question_text)


def register_ask(tree: app_commands.CommandTree, guild: discord.Object, ctx: CommandContext) -> None:
    @tree.command(name="ask", description="Fai una domanda al Q&A", guild=guild)
    @app_commands.describe(domanda="Testo domanda", azione="Azione rapida")
    @app_commands.choices(azione=[app_commands.Choice(name="stato", value="stato")])
    async def ask(interaction: discord.Interaction, domanda: str | None = None, azione: app_commands.Choice[str] | None = None) -> None:
        await _handle_ask_like(interaction, ctx, domanda, azione)

    @tree.command(name="domanda", description="Alias di /ask", guild=guild)
    @app_commands.describe(domanda="Testo domanda", azione="Azione rapida")
    @app_commands.choices(azione=[app_commands.Choice(name="stato", value="stato")])
    async def domanda(interaction: discord.Interaction, domanda: str | None = None, azione: app_commands.Choice[str] | None = None) -> None:
        await _handle_ask_like(interaction, ctx, domanda, azione)
