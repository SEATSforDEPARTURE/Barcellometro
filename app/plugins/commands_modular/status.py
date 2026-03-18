from __future__ import annotations

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.utils.command_embeds import send_standard_response


def register_status(bm_group: app_commands.Group, ctx: CommandContext) -> None:
    @bm_group.command(name="status", description="Show the Barcellometro status.")
    @app_commands.describe(service="Optional service or plugin name.")
    async def bm_status_command(interaction: discord.Interaction, service: str | None = None) -> None:
        if not await check_permission(interaction, "bm.status", ctx, legacy_aliases=["status.bm"]):
            return
        if service:
            status = ctx.status.component_status(service)
            await send_standard_response(
                interaction,
                top_level="bm",
                subcommand_path=f"bm status {service}",
                lines=[
                    ("active", status.get("active")),
                    ("state", status.get("state")),
                    ("metrics", status.get("metrics")),
                ],
                footer_service=ctx.footer,
                ephemeral=True,
            )
            return
        general = await ctx.status.general_status()
        await send_standard_response(
            interaction,
            top_level="bm",
            subcommand_path="bm status",
            lines=[
                ("bot", "online"),
                ("db_path", general.get("db_path")),
                ("retention_days", general.get("retention_days")),
                ("enabled_channels", general.get("enabled_channels")),
                ("users", general.get("users_count")),
                ("messages", general.get("messages_count")),
                ("events", general.get("events_count")),
                ("last_event", general.get("last_event_ts")),
            ],
            footer_service=ctx.footer,
            ephemeral=True,
        )
