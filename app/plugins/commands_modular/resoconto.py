from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from io import BytesIO

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.time_windows import (
    build_period_label,
    parse_italian_datetime,
    resolve_ieri_window,
    resolve_oggi_window,
    resolve_range_window,
    resolve_ultimi_window,
)
from app.services.aura import aura_reason_to_human
from app.services.footer import attach_footer_meta

logger = logging.getLogger(__name__)
EVERY_RE = re.compile(r"^(\d+)\s*(min|hours|days)$")
SCHEDULE_KIND_TO_INTERNAL = {
    "today": "oggi",
    "yesterday": "ieri",
    "last": "ultimi",
    "range": "range",
}
LAST_UNIT_TO_INTERNAL = {
    "minutes": "minuti",
    "hours": "ore",
    "days": "giorni",
    "weeks": "settimane",
}


def register_resoconto(
    resocontocanale_group: app_commands.Group,
    resocontoserver_group: app_commands.Group,
    ctx: CommandContext,
) -> None:
    async def send_ephemeral(interaction: discord.Interaction, message: str) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    def _parse_every(raw: str | None) -> tuple[int | None, str | None]:
        value = str(raw or "").strip().lower()
        if not value:
            return None, None
        match = EVERY_RE.fullmatch(value)
        if not match:
            return None, None
        return int(match.group(1)), match.group(2)

    def _fmt_schedule_ts(ts: str | None) -> str:
        if not ts:
            return "—"
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            return str(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ctx.timezone).strftime("%d/%m/%Y %H:%M")

    def _resolve_window_from_inputs(
        *,
        schedule_kind: str,
        quantity: int | None,
        unit: str | None,
        start_at: str | None,
        end_at: str | None,
    ):
        internal_kind = SCHEDULE_KIND_TO_INTERNAL.get(schedule_kind)
        if internal_kind is None:
            return None, "❌ Invalid schedule_kind. Use today, yesterday, last, or range.", None
        if internal_kind == "oggi":
            return resolve_oggi_window(), None, internal_kind
        if internal_kind == "ieri":
            return resolve_ieri_window(), None, internal_kind
        if internal_kind == "ultimi":
            if quantity is None or unit is None:
                return None, "❌ `quantity` and `unit` are required when schedule_kind is `last`.", None
            internal_unit = LAST_UNIT_TO_INTERNAL.get(unit)
            if internal_unit is None:
                return None, "❌ Invalid `unit`. Use minutes, hours, days, or weeks.", None
            window, error = resolve_ultimi_window(quantity, internal_unit, ctx.config)
            return window, error, internal_kind
        if start_at is None or end_at is None:
            return None, "❌ `start_at` and `end_at` are required when schedule_kind is `range`.", None
        window, error = resolve_range_window(start_at, end_at, ctx.config)
        return window, error, internal_kind

    def _format_window_details(row: dict[str, object], key: str = "type") -> str:
        schedule_type = str(row.get(key) or "oggi")
        if schedule_type == "range":
            return f"{_fmt_schedule_ts(str(row.get('start_ts') or ''))} → {_fmt_schedule_ts(str(row.get('end_ts') or ''))}"
        return schedule_type

    def _format_schedule_line(row: dict[str, object], *, key: str) -> str:
        recurrence = (
            f"every {row['repeat_every_value']}{row['repeat_every_unit']}"
            if row.get("repeat_every_value")
            else "one-shot"
        )
        return (
            f"id={row['id']} | status={str(row.get('status') or 'active')} | window={_format_window_details(row, key)} | "
            f"publish_at={_fmt_schedule_ts(str(row.get('publish_at') or ''))} | next_run_at={_fmt_schedule_ts(str(row.get('next_run_at') or ''))} | "
            f"every={recurrence}"
        )

    async def _send_channel_aura(interaction: discord.Interaction, *, window) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "This command is only available in a guild text channel.")
            return
        if not await check_permission(interaction, "aura", ctx):
            return
        if ctx.channel_summary is None:
            await send_ephemeral(interaction, "❌ Summary service is not available.")
            return
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)
        embed = await ctx.channel_summary.generate_channel_aura_embed(
            guild_id=str(interaction.guild_id),
            channel_id=str(interaction.channel_id),
            start_local=window.start_dt,
            end_local=window.end_dt,
            title="🗒️ DETTAGLI PUNTI AURA",
        )
        if embed is None:
            await interaction.followup.send("⚠️ No relevant aura data was found for this period.", ephemeral=True)
            return
        await interaction.followup.send(embed=embed)

    async def _run_server_aura_report(interaction: discord.Interaction, *, start_dt, end_dt, period_label: str) -> None:
        if interaction.guild_id is None:
            await send_ephemeral(interaction, "This command is only available in a server.")
            return
        if not await check_permission(interaction, "aura", ctx):
            return
        profile, _ = await ctx.entitlements.resolve_profile_with_role_id(interaction.user)
        if profile != "mod":
            await send_ephemeral(interaction, "This command is only available to moderators.")
            return
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)

        guild_id = str(interaction.guild_id)
        start_ts = start_dt.isoformat()
        end_ts = end_dt.isoformat()
        report = await ctx.database.fetch_aura_ledger_report(guild_id, start_ts, end_ts)
        period_text = build_period_label(period_label, start_dt=start_dt, end_dt=end_dt, start_ts=start_ts, end_ts=end_ts)
        period_line = f"{period_text} {start_dt.strftime('%d/%m/%Y %H:%M')} → {end_dt.strftime('%d/%m/%Y %H:%M')}"
        channel_map = await ctx.database.get_channel_name_map(guild_id)

        async def _user_reasons(user_id: str, *, positive: bool) -> str:
            items = await ctx.database.fetch_aura_user_reason_totals(guild_id, user_id, start_ts, end_ts)
            filtered = [item for item in items if (item["total"] > 0 if positive else item["total"] < 0)]
            labels = [aura_reason_to_human(str(item["reason_code"])) for item in filtered[:3]]
            return ", ".join(labels) if labels else "nessun motivo principale"

        top_pos = "\n".join(
            [f"• +{row['total']} → <@{row['user_id']}> — {await _user_reasons(str(row['user_id']), positive=True)}" for row in report["top_positive"]]
        ) or "• Nessun dato rilevante nel periodo."
        top_neg = "\n".join(
            [f"• {row['total']} → <@{row['user_id']}> — {await _user_reasons(str(row['user_id']), positive=False)}" for row in report["top_negative"]]
        ) or "• Nessun dato rilevante nel periodo."
        reasons = "\n".join(
            f"• {item['total']:+d} per {aura_reason_to_human(item['reason_code'])}" for item in report["by_reason"][:6]
        ) or "• Nessun dato rilevante nel periodo."
        channels = "\n".join(
            f"• {channel_map.get(str(item['channel_id']), '#canale')}" for item in report["by_channel"][:5] if item.get("channel_id")
        ) or "• Nessun dato rilevante nel periodo."

        embed = discord.Embed(title="🗒️ DETTAGLI PUNTI AURA", description=f"**🕒 {period_line}**", color=0x5865F2)
        embed.add_field(name="📈 PANORAMICA", value=f"• Punti assegnati: +{int(report['totals']['positive'])}\n• Punti rimossi: {int(report['totals']['negative'])}\n• Utenti coinvolti: {int(report['totals']['users_count'])}", inline=False)
        embed.add_field(name="🏆 TOP AURA POSITIVA", value=top_pos, inline=False)
        embed.add_field(name="📉 TOP AURA NEGATIVA", value=top_neg, inline=False)
        embed.add_field(name="🧾 CAUSE PRINCIPALI", value=reasons, inline=False)
        embed.add_field(name="🏷️ CANALI PIÙ COINVOLTI", value=channels, inline=False)
        mission_stats = await ctx.database.fetch_aura_mission_stats(guild_id, start_ts, end_ts)
        embed.add_field(name="📜 MISSIONI NEL PERIODO", value=f"• Ricevute da {mission_stats['users_count']} utenti\n• Completate: {mission_stats['completed_count']}\n• Incomplete: {mission_stats['pending_count']}", inline=False)
        attach_footer_meta(embed, service_name="resoconto", used_local_processing=True)

        txt_lines = ["=== RESOCONTO AURA MOD ===", f"guild_id: {guild_id}", f"period_start: {start_ts}", f"period_end: {end_ts}", "", "=== BY REASON ==="]
        txt_lines.extend([f"{item['reason_code']} => {item['total']:+d} ({item['count']})" for item in report["by_reason"]])
        file = discord.File(BytesIO("\n".join(txt_lines).encode("utf-8")), filename=f"resoconto_aura_{guild_id}.txt")
        await interaction.followup.send(embed=embed, file=file)

    async def _create_server_schedule(
        interaction: discord.Interaction,
        *,
        schedule_kind: str,
        publish_at: str,
        every: str | None,
        quantity: int | None,
        unit: str | None,
        start_at: str | None,
        end_at: str | None,
    ) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "This command is only available in a guild text channel.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        if ctx.daily_activity_report is None:
            await send_ephemeral(interaction, "❌ Server summary service is not available.")
            return
        window, error, internal_kind = _resolve_window_from_inputs(
            schedule_kind=schedule_kind,
            quantity=quantity,
            unit=unit,
            start_at=start_at,
            end_at=end_at,
        )
        if error:
            await send_ephemeral(interaction, error)
            return
        every_value, every_unit = _parse_every(every)
        if every and every_value is None:
            await send_ephemeral(interaction, "❌ Invalid `every` format. Use values like 1440min, 24hours, or 1days.")
            return
        if internal_kind == "range" and every_value is not None:
            await send_ephemeral(interaction, "❌ Range schedules only support one-shot publishing.")
            return
        publish_at_dt = parse_italian_datetime(publish_at)
        if publish_at_dt is None:
            await send_ephemeral(interaction, "❌ Invalid `publish_at` format. Use DD/MM/YYYY HH:MM.")
            return
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)
        guild_id = str(interaction.guild_id)
        channel_id = str(interaction.channel_id)
        await ctx.database.set_server_summary_auto_enabled(guild_id, True)
        await ctx.database.set_server_summary_target_channel(guild_id, channel_id)
        schedule_id = await ctx.database.create_server_summary_schedule(
            guild_id=guild_id,
            schedule_type=str(internal_kind),
            start_ts=window.start_dt.astimezone(timezone.utc).isoformat(),
            end_ts=window.end_dt.astimezone(timezone.utc).isoformat(),
            publish_at=publish_at_dt.astimezone(timezone.utc).isoformat(),
            repeat_every_value=every_value,
            repeat_every_unit=every_unit,
            created_by=str(interaction.user.id),
        )
        suffix = f" every {every_value}{every_unit}" if every_value and every_unit else ""
        await interaction.followup.send(f"✅ Server summary schedule {schedule_id} created for {publish_at}{suffix}.", ephemeral=True)

    async def _create_channel_schedule(
        interaction: discord.Interaction,
        *,
        schedule_kind: str,
        publish_at: str,
        every: str | None,
        quantity: int | None,
        unit: str | None,
        start_at: str | None,
        end_at: str | None,
    ) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "This command is only available in a guild text channel.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        if ctx.channel_summary is None:
            await send_ephemeral(interaction, "❌ Channel summary service is not available.")
            return
        window, error, internal_kind = _resolve_window_from_inputs(
            schedule_kind=schedule_kind,
            quantity=quantity,
            unit=unit,
            start_at=start_at,
            end_at=end_at,
        )
        if error:
            await send_ephemeral(interaction, error)
            return
        every_value, every_unit = _parse_every(every)
        if every and every_value is None:
            await send_ephemeral(interaction, "❌ Invalid `every` format. Use values like 1440min, 24hours, or 1days.")
            return
        if internal_kind == "range" and every_value is not None:
            await send_ephemeral(interaction, "❌ Range schedules only support one-shot publishing.")
            return
        publish_at_dt = parse_italian_datetime(publish_at)
        if publish_at_dt is None:
            await send_ephemeral(interaction, "❌ Invalid `publish_at` format. Use DD/MM/YYYY HH:MM.")
            return
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)
        guild_id = str(interaction.guild_id)
        channel_id = str(interaction.channel_id)
        await ctx.database.set_channel_summary_auto_enabled(guild_id, channel_id, True)
        schedule_id = await ctx.database.create_channel_summary_schedule(
            guild_id=guild_id,
            channel_id=channel_id,
            schedule_type=str(internal_kind),
            start_ts=window.start_dt.astimezone(timezone.utc).isoformat(),
            end_ts=window.end_dt.astimezone(timezone.utc).isoformat(),
            publish_at=publish_at_dt.astimezone(timezone.utc).isoformat(),
            repeat_every_value=every_value,
            repeat_every_unit=every_unit,
            created_by=str(interaction.user.id),
        )
        suffix = f" every {every_value}{every_unit}" if every_value and every_unit else ""
        await interaction.followup.send(f"✅ Channel summary schedule {schedule_id} created for {publish_at}{suffix}.", ephemeral=True)

    @resocontocanale_group.command(name="on", description="Enable automatic channel summaries for the current channel.")
    async def canale_on(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "This command is only available in a guild text channel.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        await ctx.database.set_channel_summary_auto_enabled(str(interaction.guild_id), str(interaction.channel_id), True)
        await send_ephemeral(interaction, "✅ Automatic channel summaries enabled for this channel.")

    @resocontocanale_group.command(name="off", description="Disable automatic channel summaries for the current channel.")
    async def canale_off(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "This command is only available in a guild text channel.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        await ctx.database.set_channel_summary_auto_enabled(str(interaction.guild_id), str(interaction.channel_id), False)
        await send_ephemeral(interaction, "✅ Automatic channel summaries disabled for this channel.")

    @resocontocanale_group.command(name="status", description="Show the channel summary schedule status.")
    async def canale_status(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "This command is only available in a guild text channel.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        gid = str(interaction.guild_id)
        cid = str(interaction.channel_id)
        enabled = await ctx.database.get_channel_summary_auto_enabled(gid, cid)
        rows = await ctx.database.list_channel_summary_schedules(gid, cid)
        lines = [f"auto={'on' if enabled else 'off'}"]
        lines.extend(_format_schedule_line(dict(row), key="type") for row in rows)
        await send_ephemeral(interaction, "\n".join(lines if rows else [lines[0], "no schedules"]))

    @resocontocanale_group.command(name="schedule_add", description="Add a channel summary schedule.")
    @app_commands.describe(
        schedule_kind="Schedule window type: today, yesterday, last, or range.",
        publish_at="First publish date and time in DD/MM/YYYY HH:MM.",
        every="Optional repeat interval like 1440min, 24hours, or 1days.",
        quantity="Required when schedule_kind is `last`.",
        unit="Required when schedule_kind is `last`.",
        start_at="Required when schedule_kind is `range`. Use DD/MM/YYYY HH:MM.",
        end_at="Required when schedule_kind is `range`. Use DD/MM/YYYY HH:MM.",
    )
    @app_commands.choices(
        schedule_kind=[
            app_commands.Choice(name="today", value="today"),
            app_commands.Choice(name="yesterday", value="yesterday"),
            app_commands.Choice(name="last", value="last"),
            app_commands.Choice(name="range", value="range"),
        ],
        unit=[
            app_commands.Choice(name="minutes", value="minutes"),
            app_commands.Choice(name="hours", value="hours"),
            app_commands.Choice(name="days", value="days"),
            app_commands.Choice(name="weeks", value="weeks"),
        ],
    )
    async def canale_schedule_add(
        interaction: discord.Interaction,
        schedule_kind: app_commands.Choice[str],
        publish_at: str,
        every: str | None = None,
        quantity: int | None = None,
        unit: app_commands.Choice[str] | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
    ) -> None:
        await _create_channel_schedule(
            interaction,
            schedule_kind=schedule_kind.value,
            publish_at=publish_at,
            every=every,
            quantity=quantity,
            unit=unit.value if unit else None,
            start_at=start_at,
            end_at=end_at,
        )

    @resocontocanale_group.command(name="schedule_edit", description="Edit a channel summary schedule.")
    @app_commands.describe(
        schedule_id="Schedule ID to update.",
        publish_at="Optional new publish date and time in DD/MM/YYYY HH:MM.",
        every="Optional repeat interval like 1440min, 24hours, 1days, off, or none.",
        enabled="Optional enabled state for the schedule.",
    )
    async def canale_schedule_edit(
        interaction: discord.Interaction,
        schedule_id: int,
        publish_at: str | None = None,
        every: str | None = None,
        enabled: bool | None = None,
    ) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "This command is only available in a guild text channel.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        row = await ctx.database.get_channel_summary_schedule(
            schedule_id=schedule_id,
            guild_id=str(interaction.guild_id),
            channel_id=str(interaction.channel_id),
        )
        if row is None:
            await send_ephemeral(interaction, "❌ Schedule not found in this channel.")
            return
        publish_dt = parse_italian_datetime(publish_at) if publish_at else None
        normalized_every = (every or "").strip().lower()
        every_value, every_unit = _parse_every(every)
        if every and every_value is None and normalized_every not in {"off", "none"}:
            await send_ephemeral(interaction, "❌ Invalid `every` format.")
            return
        if normalized_every in {"off", "none"}:
            every_value, every_unit = None, None
        if every is None:
            every_value = int(row["repeat_every_value"]) if row["repeat_every_value"] is not None else None
            every_unit = str(row["repeat_every_unit"] or "") or None
        status_value = "active" if enabled else "disabled" if enabled is not None else None
        ok = await ctx.database.update_channel_summary_schedule(
            schedule_id=schedule_id,
            guild_id=str(interaction.guild_id),
            channel_id=str(interaction.channel_id),
            publish_at=publish_dt.astimezone(timezone.utc).isoformat() if publish_dt else None,
            repeat_every_value=every_value,
            repeat_every_unit=every_unit,
            status=status_value,
        )
        await send_ephemeral(interaction, f"✅ Channel summary schedule {schedule_id} updated." if ok else "❌ Schedule not found in this channel.")

    @resocontocanale_group.command(name="schedule_remove", description="Remove a channel summary schedule.")
    @app_commands.describe(schedule_id="Schedule ID to remove.")
    async def canale_schedule_remove(interaction: discord.Interaction, schedule_id: int) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "This command is only available in a guild text channel.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        deleted = await ctx.database.delete_channel_summary_schedule(
            schedule_id=schedule_id,
            guild_id=str(interaction.guild_id),
            channel_id=str(interaction.channel_id),
        )
        await send_ephemeral(interaction, f"✅ Channel summary schedule {schedule_id} removed." if deleted else "❌ Schedule not found in this channel.")

    @resocontocanale_group.command(name="schedule_show", description="Show one channel summary schedule.")
    @app_commands.describe(schedule_id="Schedule ID to inspect.")
    async def canale_schedule_show(interaction: discord.Interaction, schedule_id: int) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "This command is only available in a guild text channel.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        row = await ctx.database.get_channel_summary_schedule(
            schedule_id=schedule_id,
            guild_id=str(interaction.guild_id),
            channel_id=str(interaction.channel_id),
        )
        if row is None:
            await send_ephemeral(interaction, "❌ Schedule not found in this channel.")
            return
        await send_ephemeral(interaction, _format_schedule_line(dict(row), key="type"))

    @resocontocanale_group.command(name="schedule_list", description="List channel summary schedules for the current channel.")
    async def canale_schedule_list(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "This command is only available in a guild text channel.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        rows = await ctx.database.list_channel_summary_schedules(str(interaction.guild_id), str(interaction.channel_id))
        if not rows:
            await send_ephemeral(interaction, "No channel summary schedules found.")
            return
        await send_ephemeral(interaction, "\n".join(_format_schedule_line(dict(row), key="type") for row in rows))

    canale_aura_group = app_commands.Group(name="aura", description="Manual channel aura detail")

    @canale_aura_group.command(name="oggi", description="Show manual channel aura details for today.")
    async def canale_aura_oggi(interaction: discord.Interaction) -> None:
        await _send_channel_aura(interaction, window=resolve_oggi_window())

    @canale_aura_group.command(name="ieri", description="Show manual channel aura details for yesterday.")
    async def canale_aura_ieri(interaction: discord.Interaction) -> None:
        await _send_channel_aura(interaction, window=resolve_ieri_window())

    @canale_aura_group.command(name="ultimi", description="Show manual channel aura details for the last window.")
    @app_commands.choices(
        unita=[
            app_commands.Choice(name="minuti", value="minuti"),
            app_commands.Choice(name="ore", value="ore"),
            app_commands.Choice(name="giorni", value="giorni"),
            app_commands.Choice(name="settimane", value="settimane"),
        ]
    )
    async def canale_aura_ultimi(interaction: discord.Interaction, quantita: int, unita: app_commands.Choice[str]) -> None:
        window, error = resolve_ultimi_window(quantita, unita.value, ctx.config)
        if error:
            await send_ephemeral(interaction, error)
            return
        await _send_channel_aura(interaction, window=window)

    @canale_aura_group.command(name="range", description="Show manual channel aura details for a range.")
    async def canale_aura_range(interaction: discord.Interaction, da: str, a: str) -> None:
        window, error = resolve_range_window(da, a, ctx.config)
        if error:
            await send_ephemeral(interaction, error)
            return
        await _send_channel_aura(interaction, window=window)

    resocontocanale_group.add_command(canale_aura_group)

    @resocontoserver_group.command(name="on", description="Enable automatic server summaries.")
    async def server_on(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "This command is only available in a guild text channel.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        await ctx.database.set_server_summary_auto_enabled(str(interaction.guild_id), True)
        await ctx.database.set_server_summary_target_channel(str(interaction.guild_id), str(interaction.channel_id))
        await send_ephemeral(interaction, "✅ Automatic server summaries enabled for this server.")

    @resocontoserver_group.command(name="off", description="Disable automatic server summaries.")
    async def server_off(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await send_ephemeral(interaction, "This command is only available in a server.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        await ctx.database.set_server_summary_auto_enabled(str(interaction.guild_id), False)
        await send_ephemeral(interaction, "✅ Automatic server summaries disabled.")

    @resocontoserver_group.command(name="status", description="Show the server summary schedule status.")
    async def server_status(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await send_ephemeral(interaction, "This command is only available in a server.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        gid = str(interaction.guild_id)
        enabled = await ctx.database.get_server_summary_auto_enabled(gid)
        target = await ctx.database.get_server_summary_target_channel(gid)
        rows = await ctx.database.list_server_summary_schedules(gid)
        lines = [f"auto={'on' if enabled else 'off'}", f"target_channel={f'<#{target}>' if target else 'not set'}"]
        lines.extend(_format_schedule_line(dict(row), key="schedule_type") for row in rows)
        await send_ephemeral(interaction, "\n".join(lines if rows else lines + ["no schedules"]))

    @resocontoserver_group.command(name="schedule_add", description="Add a server summary schedule.")
    @app_commands.describe(
        schedule_kind="Schedule window type: today, yesterday, last, or range.",
        publish_at="First publish date and time in DD/MM/YYYY HH:MM.",
        every="Optional repeat interval like 1440min, 24hours, or 1days.",
        quantity="Required when schedule_kind is `last`.",
        unit="Required when schedule_kind is `last`.",
        start_at="Required when schedule_kind is `range`. Use DD/MM/YYYY HH:MM.",
        end_at="Required when schedule_kind is `range`. Use DD/MM/YYYY HH:MM.",
    )
    @app_commands.choices(
        schedule_kind=[
            app_commands.Choice(name="today", value="today"),
            app_commands.Choice(name="yesterday", value="yesterday"),
            app_commands.Choice(name="last", value="last"),
            app_commands.Choice(name="range", value="range"),
        ],
        unit=[
            app_commands.Choice(name="minutes", value="minutes"),
            app_commands.Choice(name="hours", value="hours"),
            app_commands.Choice(name="days", value="days"),
            app_commands.Choice(name="weeks", value="weeks"),
        ],
    )
    async def server_schedule_add(
        interaction: discord.Interaction,
        schedule_kind: app_commands.Choice[str],
        publish_at: str,
        every: str | None = None,
        quantity: int | None = None,
        unit: app_commands.Choice[str] | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
    ) -> None:
        await _create_server_schedule(
            interaction,
            schedule_kind=schedule_kind.value,
            publish_at=publish_at,
            every=every,
            quantity=quantity,
            unit=unit.value if unit else None,
            start_at=start_at,
            end_at=end_at,
        )

    @resocontoserver_group.command(name="schedule_edit", description="Edit a server summary schedule.")
    @app_commands.describe(
        schedule_id="Schedule ID to update.",
        publish_at="Optional new publish date and time in DD/MM/YYYY HH:MM.",
        every="Optional repeat interval like 1440min, 24hours, 1days, off, or none.",
        enabled="Optional enabled state for the schedule.",
    )
    async def server_schedule_edit(
        interaction: discord.Interaction,
        schedule_id: int,
        publish_at: str | None = None,
        every: str | None = None,
        enabled: bool | None = None,
    ) -> None:
        if interaction.guild_id is None:
            await send_ephemeral(interaction, "This command is only available in a server.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        row = await ctx.database.get_server_summary_schedule(schedule_id=schedule_id, guild_id=str(interaction.guild_id))
        if row is None:
            await send_ephemeral(interaction, "❌ Server schedule not found.")
            return
        publish_dt = parse_italian_datetime(publish_at) if publish_at else None
        normalized_every = (every or "").strip().lower()
        every_value, every_unit = _parse_every(every)
        if every and every_value is None and normalized_every not in {"off", "none"}:
            await send_ephemeral(interaction, "❌ Invalid `every` format.")
            return
        if normalized_every in {"off", "none"}:
            every_value, every_unit = None, None
        if every is None:
            every_value = int(row["repeat_every_value"]) if row["repeat_every_value"] is not None else None
            every_unit = str(row["repeat_every_unit"] or "") or None
        ok = await ctx.database.update_server_summary_schedule(
            schedule_id=schedule_id,
            guild_id=str(interaction.guild_id),
            publish_at=publish_dt.astimezone(timezone.utc).isoformat() if publish_dt else None,
            repeat_every_value=every_value,
            repeat_every_unit=every_unit,
            enabled=enabled,
            status=("active" if enabled else "disabled") if enabled is not None else None,
        )
        await send_ephemeral(interaction, f"✅ Server summary schedule {schedule_id} updated." if ok else "❌ Server schedule not found.")

    @resocontoserver_group.command(name="schedule_remove", description="Remove a server summary schedule.")
    @app_commands.describe(schedule_id="Schedule ID to remove.")
    async def server_schedule_remove(interaction: discord.Interaction, schedule_id: int) -> None:
        if interaction.guild_id is None:
            await send_ephemeral(interaction, "This command is only available in a server.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        deleted = await ctx.database.delete_server_summary_schedule(schedule_id=schedule_id, guild_id=str(interaction.guild_id))
        await send_ephemeral(interaction, f"✅ Server summary schedule {schedule_id} removed." if deleted else "❌ Server schedule not found.")

    @resocontoserver_group.command(name="schedule_show", description="Show one server summary schedule.")
    @app_commands.describe(schedule_id="Schedule ID to inspect.")
    async def server_schedule_show(interaction: discord.Interaction, schedule_id: int) -> None:
        if interaction.guild_id is None:
            await send_ephemeral(interaction, "This command is only available in a server.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        row = await ctx.database.get_server_summary_schedule(schedule_id=schedule_id, guild_id=str(interaction.guild_id))
        if row is None:
            await send_ephemeral(interaction, "❌ Server schedule not found.")
            return
        await send_ephemeral(interaction, _format_schedule_line(dict(row), key="schedule_type"))

    @resocontoserver_group.command(name="schedule_list", description="List server summary schedules.")
    async def server_schedule_list(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await send_ephemeral(interaction, "This command is only available in a server.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        rows = await ctx.database.list_server_summary_schedules(str(interaction.guild_id))
        if not rows:
            await send_ephemeral(interaction, "No server summary schedules found.")
            return
        await send_ephemeral(interaction, "\n".join(_format_schedule_line(dict(row), key="schedule_type") for row in rows))

    server_aura_group = app_commands.Group(name="aura", description="Manual server aura detail")

    @server_aura_group.command(name="oggi", description="Show manual server aura details for today.")
    async def server_aura_oggi(interaction: discord.Interaction) -> None:
        window = resolve_oggi_window()
        await _run_server_aura_report(interaction, start_dt=window.start_dt, end_dt=window.end_dt, period_label="oggi")

    @server_aura_group.command(name="ieri", description="Show manual server aura details for yesterday.")
    async def server_aura_ieri(interaction: discord.Interaction) -> None:
        window = resolve_ieri_window()
        await _run_server_aura_report(interaction, start_dt=window.start_dt, end_dt=window.end_dt, period_label="ieri")

    @server_aura_group.command(name="ultimi", description="Show manual server aura details for the last window.")
    @app_commands.choices(
        unita=[
            app_commands.Choice(name="minuti", value="minuti"),
            app_commands.Choice(name="ore", value="ore"),
            app_commands.Choice(name="giorni", value="giorni"),
            app_commands.Choice(name="settimane", value="settimane"),
        ]
    )
    async def server_aura_ultimi(interaction: discord.Interaction, quantita: int, unita: app_commands.Choice[str]) -> None:
        window, error = resolve_ultimi_window(quantita, unita.value, ctx.config)
        if error:
            await send_ephemeral(interaction, error)
            return
        await _run_server_aura_report(interaction, start_dt=window.start_dt, end_dt=window.end_dt, period_label="ultimi")

    @server_aura_group.command(name="range", description="Show manual server aura details for a range.")
    async def server_aura_range(interaction: discord.Interaction, da: str, a: str) -> None:
        window, error = resolve_range_window(da, a, ctx.config)
        if error:
            await send_ephemeral(interaction, error)
            return
        await _run_server_aura_report(interaction, start_dt=window.start_dt, end_dt=window.end_dt, period_label="range")

    resocontoserver_group.add_command(server_aura_group)
