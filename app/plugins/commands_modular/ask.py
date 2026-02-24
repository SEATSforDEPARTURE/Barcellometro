from __future__ import annotations

from datetime import datetime
from typing import Literal

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext


def parse_qna_input(canale: str | None, generale: str | None) -> tuple[str | None, Literal["channel", "global"] | None, str | None]:
    channel_text = (canale or "").strip()
    global_text = (generale or "").strip()
    has_channel = bool(channel_text)
    has_global = bool(global_text)

    if has_channel and has_global:
        return ("Compila un solo campo tra 'canale' e 'generale'.", None, None)
    if not has_channel and not has_global:
        return ("Compila uno dei due campi: 'canale' oppure 'generale'.", None, None)
    if has_channel:
        return (None, "channel", channel_text)
    return (None, "global", global_text)


async def _handle_ask_like(interaction: discord.Interaction, ctx: CommandContext, canale: str | None, generale: str | None) -> None:
    if ctx.trigger_engine is None:
        await interaction.response.send_message("Servizio trigger non disponibile.", ephemeral=True)
        return
    error_text, scope, text_value = parse_qna_input(canale, generale)
    if error_text:
        await interaction.response.send_message(error_text, ephemeral=True)
        return
    assert scope is not None
    assert text_value is not None

    if text_value.lower() == "stato":
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
    await ctx.trigger_engine.handle_qna_question(interaction, text_value, scope_override=scope)


def register_ask(tree: app_commands.CommandTree, guild: discord.abc.Snowflake | None, ctx: CommandContext) -> None:
    @tree.command(name="ask", description="Fai una domanda al Q&A", guild=guild)
    @app_commands.describe(
        canale="Domanda sul canale corrente (usa 'stato' per vedere quota)",
        generale="Domanda generale (usa 'stato' per vedere quota)",
    )
    async def ask(interaction: discord.Interaction, canale: str | None = None, generale: str | None = None) -> None:
        await _handle_ask_like(interaction, ctx, canale, generale)

    @tree.command(name="domanda", description="Alias di /ask", guild=guild)
    @app_commands.describe(
        canale="Domanda sul canale corrente (usa 'stato' per vedere quota)",
        generale="Domanda generale (usa 'stato' per vedere quota)",
    )
    async def domanda(interaction: discord.Interaction, canale: str | None = None, generale: str | None = None) -> None:
        await _handle_ask_like(interaction, ctx, canale, generale)
