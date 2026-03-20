from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.shared.discord.command_embeds import send_standard_response

logger = logging.getLogger(__name__)


def parse_qna_input(canale: str | None, generale: str | None) -> tuple[str | None, Literal["channel_qna", "general_llm"] | None, str | None, bool, bool]:
    channel_text = (canale or "").strip()
    global_text = (generale or "").strip()
    has_channel = bool(channel_text)
    has_global = bool(global_text)
    if has_channel and has_global:
        return ("Compila un solo campo tra 'canale' e 'generale'.", None, None, has_channel, has_global)
    if not has_channel and not has_global:
        return ("Compila uno dei due campi: 'canale' oppure 'generale'.", None, None, has_channel, has_global)
    if has_global:
        return (None, "general_llm", global_text, has_channel, has_global)
    return (None, "channel_qna", channel_text, has_channel, has_global)


async def _handle_ask_like(interaction: discord.Interaction, ctx: CommandContext, canale: str | None, generale: str | None) -> None:
    if ctx.trigger_engine is None:
        await send_standard_response(interaction, top_level="admin", subcommand_path="ask domanda", lines=[("error", "Servizio trigger non disponibile.")], kind="error", footer_service=ctx.footer)
        return
    error_text, scope, text_value, has_channel, has_global = parse_qna_input(canale, generale)
    if error_text:
        await send_standard_response(interaction, top_level="admin", subcommand_path="ask domanda", lines=[("error", error_text)], kind="error", footer_service=ctx.footer)
        return
    assert scope is not None
    assert text_value is not None
    logger.info("qna_dispatch scope=%s has_canale=%s has_generale=%s len_text=%s", scope, has_channel, has_global, len(text_value))
    if text_value.lower() == "stato":
        if interaction.guild_id is None:
            await send_standard_response(interaction, top_level="admin", subcommand_path="ask domanda stato", lines=[("error", "Usa questo comando in un server.")], kind="error", footer_service=ctx.footer)
            return
        quota = await ctx.trigger_engine.get_qna_quota_for_member(interaction.user, str(interaction.guild_id), str(interaction.channel_id) if interaction.channel_id else None)
        reset_text = quota["resets_at_iso"]
        try:
            reset_text = datetime.fromisoformat(str(quota["resets_at_iso"])).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass
        await send_standard_response(interaction, top_level="admin", subcommand_path="ask domanda stato", lines=[("tier", quota["tier"]), ("limite_giornaliero", quota["limit"]), ("usate_oggi", quota["used"]), ("rimanenti_oggi", quota["remaining"]), ("reset", reset_text)], footer_service=ctx.footer)
        return
    await ctx.trigger_engine.route_qna(interaction, text_value, scope=scope)


def register_ask(tree: app_commands.CommandTree, guild: discord.abc.Snowflake | None, ctx: CommandContext) -> None:
    @tree.command(name="domanda", description="Fai una domanda al Q&A", guild=guild)
    @app_commands.describe(canale="Domanda canale", generale="Domanda generale")
    async def domanda(interaction: discord.Interaction, canale: str | None = None, generale: str | None = None) -> None:
        if not await check_permission(interaction, "qna.domanda", ctx):
            return
        await _handle_ask_like(interaction, ctx, canale, generale)
