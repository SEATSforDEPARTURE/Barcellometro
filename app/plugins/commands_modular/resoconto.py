from __future__ import annotations

import logging
import re
from io import BytesIO
from datetime import timezone

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

logger = logging.getLogger(__name__)

def register_resoconto(resoconto_group: app_commands.Group, ctx: CommandContext) -> None:
    async def send_ephemeral(interaction: discord.Interaction, message: str) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    def _parse_every(raw: str | None) -> tuple[int | None, str | None]:
        value = str(raw or "").strip().lower()
        if not value:
            return None, None
        m = re.fullmatch(r"(\d+)\s*(min|hours|days)", value)
        if not m:
            return None, None
        return int(m.group(1)), m.group(2)

    async def _run_channel_summary_window(
        interaction: discord.Interaction,
        *,
        schedule_type: str,
        window,
        publish_at: str | None,
        every: str | None,
    ) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in un canale guild.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return

        db = ctx.database
        guild_id = str(interaction.guild_id)
        channel_id = str(interaction.channel_id)
        daily_service = ctx.daily_resoconto
        if daily_service is None:
            await send_ephemeral(interaction, "❌ Servizio resoconto non disponibile.")
            return

        every_value, every_unit = _parse_every(every)
        if every and every_value is None:
            await send_ephemeral(interaction, "❌ Formato `every` non valido. Usa ad esempio 1440min, 24hours, 1days.")
            return

        publish_at_dt = parse_italian_datetime(publish_at) if publish_at else None
        if publish_at and publish_at_dt is None:
            await send_ephemeral(interaction, "❌ Formato `publish_at` non valido. Usa DD/MM/YYYY HH:MM.")
            return

        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)
        if publish_at_dt:
            schedule_id = await db.create_channel_summary_schedule(
                guild_id=guild_id,
                channel_id=channel_id,
                schedule_type=schedule_type,
                start_ts=window.start_dt.astimezone(timezone.utc).isoformat(),
                end_ts=window.end_dt.astimezone(timezone.utc).isoformat(),
                publish_at=publish_at_dt.astimezone(timezone.utc).isoformat(),
                repeat_every_value=every_value,
                repeat_every_unit=every_unit,
                created_by=str(interaction.user.id),
            )
            await interaction.followup.send(f"✅ Schedule creato (id={schedule_id}) per {publish_at}.", ephemeral=True)
            return

        sent = await daily_service.generate_and_send_for_channel(guild_id, channel_id, manual=True, window=window)
        await interaction.followup.send(
            "✅ Resoconto canale inviato ora." if sent else "⚠️ Non sono riuscito a inviare il resoconto in questo canale.",
            ephemeral=True,
        )

    canale_group = app_commands.Group(name="canale", description="Resoconto canale")

    @canale_group.command(name="oggi", description="Resoconto canale di oggi")
    @app_commands.describe(publish_at="Prima pubblicazione (DD/MM/YYYY HH:MM)", every="Intervallo ripetizione: es 1440min")
    async def canale_oggi(interaction: discord.Interaction, publish_at: str | None = None, every: str | None = None) -> None:
        await _run_channel_summary_window(interaction, schedule_type="oggi", window=resolve_oggi_window(), publish_at=publish_at, every=every)

    @canale_group.command(name="ieri", description="Resoconto canale di ieri")
    @app_commands.describe(publish_at="Prima pubblicazione (DD/MM/YYYY HH:MM)", every="Intervallo ripetizione: es 1440min")
    async def canale_ieri(interaction: discord.Interaction, publish_at: str | None = None, every: str | None = None) -> None:
        await _run_channel_summary_window(interaction, schedule_type="ieri", window=resolve_ieri_window(), publish_at=publish_at, every=every)


    @canale_group.command(name="ultimi", description="Resoconto canale ultimi N periodi")
    @app_commands.describe(quantita="Numero di unità", unita="Unità di tempo", publish_at="Prima pubblicazione (DD/MM/YYYY HH:MM)", every="Intervallo ripetizione: es 1440min")
    @app_commands.choices(unita=[
        app_commands.Choice(name="minuti", value="minuti"),
        app_commands.Choice(name="ore", value="ore"),
        app_commands.Choice(name="giorni", value="giorni"),
        app_commands.Choice(name="settimane", value="settimane"),
    ])
    async def canale_ultimi(interaction: discord.Interaction, quantita: int, unita: app_commands.Choice[str], publish_at: str | None = None, every: str | None = None) -> None:
        window, error = resolve_ultimi_window(quantita, unita.value, ctx.config)
        if error:
            await send_ephemeral(interaction, error)
            return
        assert window is not None
        await _run_channel_summary_window(interaction, schedule_type="ultimi", window=window, publish_at=publish_at, every=every)

    @canale_group.command(name="range", description="Resoconto canale per intervallo")
    @app_commands.describe(da="Data inizio DD/MM/YYYY HH:MM", a="Data fine DD/MM/YYYY HH:MM", publish_at="Prima pubblicazione (DD/MM/YYYY HH:MM)", every="Intervallo ripetizione: es 1440min")
    async def canale_range(interaction: discord.Interaction, da: str, a: str, publish_at: str | None = None, every: str | None = None) -> None:
        window, error = resolve_range_window(da, a, ctx.config)
        if error:
            await send_ephemeral(interaction, error)
            return
        assert window is not None
        await _run_channel_summary_window(interaction, schedule_type="range", window=window, publish_at=publish_at, every=every)

    @canale_group.command(name="on", description="Abilita pubblicazioni automatiche per il canale")
    async def canale_on(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in un canale guild.")
            return
        await ctx.database.set_channel_summary_auto_enabled(str(interaction.guild_id), str(interaction.channel_id), True)
        await send_ephemeral(interaction, "✅ Resoconto canale automatico attivato per questo canale.")

    @canale_group.command(name="off", description="Disabilita pubblicazioni automatiche per il canale")
    async def canale_off(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in un canale guild.")
            return
        await ctx.database.set_channel_summary_auto_enabled(str(interaction.guild_id), str(interaction.channel_id), False)
        await ctx.database.disable_channel_summary_schedules(str(interaction.guild_id), str(interaction.channel_id))
        await send_ephemeral(interaction, "✅ Resoconto canale automatico disattivato per questo canale.")

    @canale_group.command(name="status", description="Mostra stato e schedule del resoconto canale")
    async def canale_status(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in un canale guild.")
            return
        guild_id = str(interaction.guild_id)
        channel_id = str(interaction.channel_id)
        enabled = await ctx.database.get_channel_summary_auto_enabled(guild_id, channel_id)
        schedules = await ctx.database.list_channel_summary_schedules(guild_id, channel_id)
        lines = [f"• id={row['id']} tipo={row['type']} publish_at={row['publish_at']} every={row['repeat_every_value'] or '-'}{row['repeat_every_unit'] or ''} stato={row['status']}" for row in schedules]
        text = "\n".join(lines) if lines else "• Nessuno schedule presente"
        await send_ephemeral(interaction, f"ℹ️ Automatico: {'ON' if enabled else 'OFF'}\n{text}")

    resoconto_group.add_command(canale_group)

    aura_group = app_commands.Group(name="aura", description="Resoconto punti Aura (solo mod)")

    async def _run_aura_report(interaction: discord.Interaction, *, start_dt, end_dt, period_label: str) -> None:
        if interaction.guild_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in server.")
            return
        if not await check_permission(interaction, "aura", ctx):
            return
        profile, _ = await ctx.entitlements.resolve_profile_with_role_id(interaction.user)
        if profile != "mod":
            await send_ephemeral(interaction, "Comando disponibile solo ai mod.")
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
            filtered = [x for x in items if (x["total"] > 0 if positive else x["total"] < 0)]
            labels = [aura_reason_to_human(str(x["reason_code"])) for x in filtered[:3]]
            return ", ".join(labels) if labels else "nessun motivo principale"

        top_pos_lines: list[str] = []
        for row in report["top_positive"]:
            why = await _user_reasons(str(row["user_id"]), positive=True)
            top_pos_lines.append(f"• +{row['total']} → <@{row['user_id']}> — {why}")
        top_pos = "\n".join(top_pos_lines) or "• Nessun dato rilevante nel periodo."

        top_neg_lines: list[str] = []
        for row in report["top_negative"]:
            why = await _user_reasons(str(row["user_id"]), positive=False)
            top_neg_lines.append(f"• {row['total']} → <@{row['user_id']}> — {why}")
        top_neg = "\n".join(top_neg_lines) or "• Nessun dato rilevante nel periodo."
        reasons = "\n".join(
            f"• {item['total']:+d} per {aura_reason_to_human(item['reason_code'])}"
            for item in report["by_reason"][:6]
        ) or "• Nessun dato rilevante nel periodo."
        channels = "\n".join(
            f"• {channel_map.get(str(item['channel_id']), '#canale')}"
            for item in report["by_channel"][:5]
            if item.get("channel_id")
        ) or "• Nessun dato rilevante nel periodo."

        embed = discord.Embed(title="✨ RESOCONTO AURA — SERVER", description=f"**🕒 {period_line}**", color=0x5865F2)
        embed.add_field(
            name="📈 PANORAMICA",
            value=(
                f"• Punti assegnati: +{int(report['totals']['positive'])}\n"
                f"• Punti rimossi: {int(report['totals']['negative'])}\n"
                f"• Utenti coinvolti: {int(report['totals']['users_count'])}"
            ),
            inline=False,
        )
        embed.add_field(name="🏆 TOP AURA POSITIVA", value=top_pos, inline=False)
        embed.add_field(name="📉 TOP AURA NEGATIVA", value=top_neg, inline=False)
        embed.add_field(name="🧾 CAUSE PRINCIPALI", value=reasons, inline=False)
        embed.add_field(name="🏷️ CANALI PIÙ COINVOLTI", value=channels, inline=False)
        mission_stats = await ctx.database.fetch_aura_mission_stats(guild_id, start_ts, end_ts)
        embed.add_field(
            name="📜 MISSIONI NEL PERIODO",
            value=(
                f"• Ricevute da {mission_stats['users_count']} utenti\n"
                f"• Completate: {mission_stats['completed_count']}\n"
                f"• Incomplete: {mission_stats['pending_count']}"
            ),
            inline=False,
        )
        embed.set_footer(text="Dati elaborati in loco. Eventuali imprecisioni sono possibili.")

        txt_lines = [
            "=== RESOCONTO AURA MOD ===",
            f"guild_id: {guild_id}",
            f"guild_name: {interaction.guild.name if interaction.guild else guild_id}",
            f"period_start: {start_ts}",
            f"period_end: {end_ts}",
            "",
            "=== TOTALI ===",
            f"positive: {report['totals']['positive']}",
            f"negative: {report['totals']['negative']}",
            f"users_count: {report['totals']['users_count']}",
            "",
            "=== BY REASON ===",
        ]
        txt_lines.extend([f"{item['reason_code']} => {item['total']:+d} ({item['count']})" for item in report["by_reason"]])
        member_names = await ctx.database.get_member_name_map(guild_id)
        events = await ctx.database.fetch_aura_ledger_events_for_guild(guild_id, start_ts, end_ts)
        txt_lines.extend(["", "=== EVENTI CRONOLOGICI ==="])
        for ev in events:
            user_id = str(ev["user_id"])
            display = member_names.get(user_id, user_id)
            ch = channel_map.get(str(ev.get("channel_id")), "#canale") if ev.get("channel_id") else "-"
            delta = int(ev["delta_points"])
            reason = str(ev["reason_code"])
            why = aura_reason_to_human(reason)
            txt_lines.append(
                f"[{ev['ts']}] user={user_id} (@{display}) channel={ch} delta={delta:+d} reason={reason} motivo=\"{why}\""
            )
        txt_lines.extend(
            [
                "",
                "=== MISSIONI ===",
                f"assigned_count: {mission_stats['assigned_count']}",
                f"completed_count: {mission_stats['completed_count']}",
                f"pending_count: {mission_stats['pending_count']}",
                "TODO: dettaglio per mission_id disponibile appena il ciclo di assegnazione/completamento è pienamente integrato runtime.",
            ]
        )
        file = discord.File(BytesIO("\n".join(txt_lines).encode("utf-8")), filename=f"resoconto_aura_{guild_id}.txt")
        await interaction.followup.send(embed=embed, file=file)

    @aura_group.command(name="oggi", description="Resoconto Aura mod di oggi")
    async def aura_oggi(interaction: discord.Interaction) -> None:
        w = resolve_oggi_window()
        await _run_aura_report(interaction, start_dt=w.start_dt, end_dt=w.end_dt, period_label="oggi")

    @aura_group.command(name="ieri", description="Resoconto Aura mod di ieri")
    async def aura_ieri(interaction: discord.Interaction) -> None:
        w = resolve_ieri_window()
        await _run_aura_report(interaction, start_dt=w.start_dt, end_dt=w.end_dt, period_label="ieri")

    @aura_group.command(name="ultimi", description="Resoconto Aura mod ultimi N periodi")
    @app_commands.describe(quantita="Numero di unità", unita="Unità di tempo")
    @app_commands.choices(unita=[
        app_commands.Choice(name="minuti", value="minuti"),
        app_commands.Choice(name="ore", value="ore"),
        app_commands.Choice(name="giorni", value="giorni"),
        app_commands.Choice(name="settimane", value="settimane"),
    ])
    async def aura_ultimi(interaction: discord.Interaction, quantita: int, unita: app_commands.Choice[str]) -> None:
        window, error = resolve_ultimi_window(quantita, unita.value, ctx.config)
        if error:
            await send_ephemeral(interaction, error)
            return
        assert window is not None
        await _run_aura_report(interaction, start_dt=window.start_dt, end_dt=window.end_dt, period_label="ultimi")

    @aura_group.command(name="range", description="Resoconto Aura mod per intervallo")
    async def aura_range(interaction: discord.Interaction, da: str, a: str) -> None:
        window, error = resolve_range_window(da, a, ctx.config)
        if error:
            await send_ephemeral(interaction, error)
            return
        assert window is not None
        await _run_aura_report(interaction, start_dt=window.start_dt, end_dt=window.end_dt, period_label="range")

    resoconto_group.add_command(aura_group)
