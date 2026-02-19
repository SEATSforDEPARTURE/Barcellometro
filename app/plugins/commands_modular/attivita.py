from __future__ import annotations

from datetime import timezone

import discord
from discord import Forbidden, app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.time_windows import resolve_ieri_window, resolve_oggi_window, resolve_range_window, resolve_ultimi_window
from app.renderers.activity_dm_renderer import build_activity_dm_embeds


def register_attivita(attivita_group: app_commands.Group, ctx: CommandContext) -> None:
    async def _send_activity_report(interaction: discord.Interaction, window, granularity: str | None = None) -> None:
        if not await check_permission(interaction, "attivita.dm", ctx):
            return
        if not interaction.guild_id or not interaction.channel_id:
            await interaction.response.send_message("Comando disponibile solo nei server.", ephemeral=True)
            return
        start_ts = window.start_dt.astimezone(timezone.utc).isoformat()
        end_ts = window.end_dt.astimezone(timezone.utc).isoformat()
        details = await ctx.activity_insights.compute_activity_for_channel(
            str(interaction.guild_id),
            str(interaction.channel_id),
            start_ts,
            end_ts,
        )
        channel_name = getattr(interaction.channel, "name", str(interaction.channel_id))
        embeds = build_activity_dm_embeds(channel_name, window.label_periodo, details)
        try:
            await interaction.user.send(embeds=embeds)
            await interaction.response.send_message("Ti ho inviato il resoconto attività in DM ✅", ephemeral=True)
        except Forbidden:
            await interaction.response.send_message("DM chiusi, non posso inviarti il report.", ephemeral=True)

    @attivita_group.command(name="oggi", description="Report attività di oggi (DM staff)")
    async def attivita_oggi(interaction: discord.Interaction) -> None:
        await _send_activity_report(interaction, resolve_oggi_window())

    @attivita_group.command(name="ieri", description="Report attività di ieri (DM staff)")
    async def attivita_ieri(interaction: discord.Interaction) -> None:
        await _send_activity_report(interaction, resolve_ieri_window())

    @attivita_group.command(name="ultimi", description="Report attività ultimi N minuti/ore/giorni/settimane")
    @app_commands.describe(quantita="Numero di unità", unita="Unità di tempo")
    @app_commands.choices(
        unita=[
            app_commands.Choice(name="minuti", value="minuti"),
            app_commands.Choice(name="ore", value="ore"),
            app_commands.Choice(name="giorni", value="giorni"),
            app_commands.Choice(name="settimane", value="settimane"),
        ]
    )
    async def attivita_ultimi(interaction: discord.Interaction, quantita: int, unita: app_commands.Choice[str]) -> None:
        window, error = resolve_ultimi_window(quantita, unita.value, ctx.config)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        assert window is not None
        await _send_activity_report(interaction, window)

    @attivita_group.command(name="range", description="Report attività per range custom")
    @app_commands.describe(da="Da (DD/MM/YYYY HH:MM)", a="A (DD/MM/YYYY HH:MM)")
    async def attivita_range(interaction: discord.Interaction, da: str, a: str) -> None:
        window, error = resolve_range_window(da, a, ctx.config)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        assert window is not None
        await _send_activity_report(interaction, window)
