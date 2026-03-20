from __future__ import annotations

import discord
from discord import app_commands

from app.shared.discord.command_embeds import send_legacy_standard_response
from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission


def register_status(admin_group: app_commands.Group, ctx: CommandContext) -> None:
    @admin_group.command(name="status", description="Show the Barcellometro status.")
    @app_commands.describe(service="Optional service or plugin name.")
    async def admin_status_command(interaction: discord.Interaction, service: str | None = None) -> None:
        if not await check_permission(interaction, "admin.status", ctx):
            return
        if service:
            status = ctx.status.component_status(service)
            await send_legacy_standard_response(
                interaction,
                top_level="admin",
                path_parts=["status", service],
                entries=[
                    ("Service", service),
                    ("Active", status["active"]),
                    ("State", status["state"]),
                    ("Metrics", status["metrics"]),
                ],
                service_name="status",
                ephemeral=True,
            )
            return
        general = await ctx.status.general_status()
        await send_legacy_standard_response(
            interaction,
            top_level="admin",
            path_parts=["status"],
            entries=[
                ("Bot", "online"),
                ("Db Path", general["db_path"]),
                ("Retention Days", general["retention_days"]),
                ("Enabled Channels", general["enabled_channels"]),
                ("Users", general["users_count"]),
                ("Messages", general["messages_count"]),
                ("Events", general["events_count"]),
                ("Last Event", general["last_event_ts"]),
            ],
            service_name="status",
            ephemeral=True,
        )
