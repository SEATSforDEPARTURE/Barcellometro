from __future__ import annotations

from typing import Any

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.shared.discord.command_embeds import send_standard_response

PERM = "mod"


async def _ensure_cfg(ctx: CommandContext, guild_id: str) -> dict[str, Any]:
    if await ctx.database.get_inactivity_config(guild_id) is None:
        await ctx.database.upsert_inactivity_config(guild_id)
    cfg = await ctx.database.get_inactivity_config(guild_id)
    return dict(cfg) if cfg else {}


def register_greetings(greetings_group: app_commands.Group, ctx: CommandContext, *, top_level: str = "greetings", visual_top_level: str = "greetings") -> None:
    backfill_group = app_commands.Group(name="backfill", description="Greetings timeline backfill controls")
    greetings_group.add_command(backfill_group)

    async def _ensure(interaction: discord.Interaction) -> bool:
        return await check_permission(interaction, PERM, ctx)

    def _backfill_service() -> Any | None:
        return getattr(ctx, "greetings_backfill", None)

    async def _send(
        interaction: discord.Interaction,
        *,
        subcommand_path: str,
        subtitle_args: list[object] | None = None,
        lines: list[tuple[str, object]] | None = None,
        sections: list[CommandEmbedSection] | None = None,
        kind: str = "info",
        footer_service: object | None = None,
    ) -> None:
        await send_standard_response(
            interaction,
            top_level=top_level,
            subcommand_path=subcommand_path,
            visual_top_level=visual_top_level,
            subtitle_args=subtitle_args,
            lines=lines,
            sections=sections,
            kind=kind,
            footer_service=ctx.footer if footer_service is None else footer_service,
        )

    async def _send_status(interaction: discord.Interaction) -> None:
        cfg = await _ensure_cfg(ctx, str(interaction.guild_id))
        notify_channel_id = cfg.get("notify_channel_id") or cfg.get("atrio_channel_id")
        await _send(
            interaction,
            subcommand_path="greetings status",
            lines=[
                ("enabled", "on" if bool(notify_channel_id) else "off"),
                ("notify_channel", f"<#{notify_channel_id}>" if notify_channel_id else "not set"),
                ("user_card", "on" if bool(int(cfg.get("notify_card_enabled") or 0)) else "off"),
            ],
        )

    async def _send_backfill_status(interaction: discord.Interaction) -> None:
        service = _backfill_service()
        if service is None:
            await _send(
                interaction,
                subcommand_path="greetings backfill status",
                lines=[("error", "service unavailable")],
                kind="error",
            )
            return
        status = await service.status(str(interaction.guild_id) if interaction.guild_id is not None else None)
        await _send(
            interaction,
            subcommand_path="greetings backfill status",
            lines=[
                ("enabled", "on" if status["enabled"] else "off"),
                ("last_run_at", status.get("last_run_at") or "never"),
                ("canonical_records", status.get("canonical_count", 0)),
                ("last_run_imported", status.get("last_run_imported_count") if status.get("last_run_imported_count") is not None else "n/a"),
                ("last_run_skipped", status.get("last_run_skipped_count") if status.get("last_run_skipped_count") is not None else "n/a"),
            ],
        )

    @backfill_group.command(name="on", description="Enable greetings timeline backfill.")
    async def greetings_backfill_on(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction):
            return
        service = _backfill_service()
        if service is None:
            await _send(interaction, subcommand_path="greetings backfill on", lines=[("error", "service unavailable")], kind="error")
            return
        await service.set_enabled(True)
        await _send(interaction, subcommand_path="greetings backfill on", lines=[("enabled", "on")], kind="success")

    @backfill_group.command(name="off", description="Disable greetings timeline backfill.")
    async def greetings_backfill_off(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction):
            return
        service = _backfill_service()
        if service is None:
            await _send(interaction, subcommand_path="greetings backfill off", lines=[("error", "service unavailable")], kind="error")
            return
        await service.set_enabled(False)
        await _send(interaction, subcommand_path="greetings backfill off", lines=[("enabled", "off")], kind="success")

    @backfill_group.command(name="status", description="Show greetings timeline backfill status.")
    async def greetings_backfill_status(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _send_backfill_status(interaction)

    @backfill_group.command(name="run", description="Run greetings timeline backfill now.")
    async def greetings_backfill_run(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        service = _backfill_service()
        if service is None:
            await _send(interaction, subcommand_path="greetings backfill run", lines=[("error", "service unavailable")], kind="error")
            return
        if not await service.is_enabled():
            await _send(
                interaction,
                subcommand_path="greetings backfill run",
                lines=[("error", "backfill disabled"), ("action", "enable it first")],
                kind="warning",
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await service.run_once(guild_id=str(interaction.guild_id))
        await _send(
            interaction,
            subcommand_path="greetings backfill run",
            lines=[
                ("imported", result.imported_count),
                ("skipped", result.skipped_count),
                ("canonical_records", result.canonical_count),
                ("last_run_at", result.last_run_at or "n/a"),
            ],
            kind="success",
        )

    @greetings_group.command(name="on", description="Enable greetings notifications for a channel.")
    @app_commands.describe(channel="Optional text channel. Defaults to the current channel.")
    async def greetings_on(interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        target_channel = channel
        if target_channel is None and isinstance(interaction.channel, discord.TextChannel):
            target_channel = interaction.channel
        if target_channel is None:
            await _send(interaction, subcommand_path="greetings on", lines=[("error", "Select a text channel first.")], kind="error", footer_service=ctx.footer)
            return
        await ctx.database.set_notify_channel(str(interaction.guild_id), str(target_channel.id))
        await _send(
            interaction,
            subcommand_path="greetings on",
            subtitle_args=[target_channel],
            lines=[("channel", target_channel.mention), ("result", "enabled")],
            kind="success",
            footer_service=ctx.footer,
        )

    @greetings_group.command(name="off", description="Disable greetings notifications.")
    async def greetings_off(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), notify_channel_id=None)
        await _send(interaction, subcommand_path="greetings off", lines=[("result", "disabled")], kind="success", footer_service=ctx.footer)

    @greetings_group.command(name="status", description="Show the greetings configuration status.")
    async def greetings_status(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _send_status(interaction)

    @greetings_group.command(name="notify_set", description="Set the greetings notification channel.")
    @app_commands.describe(channel="Text channel used for greetings notifications.")
    async def greetings_notify_set(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.set_notify_channel(str(interaction.guild_id), str(channel.id))
        await _send(
            interaction,
            subcommand_path="greetings notify_set",
            subtitle_args=[channel],
            lines=[("channel", channel.mention), ("result", "updated")],
            kind="success",
            footer_service=ctx.footer,
        )

    @greetings_group.command(name="notify_show", description="Show the greetings notification channel.")
    async def greetings_notify_show(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await _ensure_cfg(ctx, str(interaction.guild_id))
        notify_channel_id = cfg.get("notify_channel_id") or cfg.get("atrio_channel_id")
        await _send(interaction, subcommand_path="greetings notify_show", lines=[("notify_channel", f"<#{notify_channel_id}>" if notify_channel_id else "not set")], footer_service=ctx.footer)

    @greetings_group.command(name="notify_reset", description="Reset the greetings notification channel.")
    async def greetings_notify_reset(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), notify_channel_id=None)
        await _send(interaction, subcommand_path="greetings notify_reset", lines=[("result", "reset")], kind="success", footer_service=ctx.footer)

    @greetings_group.command(name="user_card_set", description="Set whether greetings notifications include the user card.")
    @app_commands.describe(enabled="Whether the greetings notification user card is enabled.")
    async def greetings_user_card_set(interaction: discord.Interaction, enabled: bool) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.set_notify_card_enabled(str(interaction.guild_id), enabled)
        await _send(interaction, subcommand_path="greetings user_card_set", lines=[("user_card", "enabled" if enabled else "disabled")], kind="success", footer_service=ctx.footer)

    @greetings_group.command(name="user_card_show", description="Show whether the greetings notification user card is enabled.")
    async def greetings_user_card_show(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await _ensure_cfg(ctx, str(interaction.guild_id))
        enabled = bool(int(cfg.get("notify_card_enabled") or 0))
        await _send(interaction, subcommand_path="greetings user_card_show", lines=[("user_card", "on" if enabled else "off")], footer_service=ctx.footer)

    @greetings_group.command(name="user_card_reset", description="Reset the greetings notification user card setting.")
    async def greetings_user_card_reset(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.set_notify_card_enabled(str(interaction.guild_id), False)
        await _send(interaction, subcommand_path="greetings user_card_reset", lines=[("result", "reset")], kind="success", footer_service=ctx.footer)
