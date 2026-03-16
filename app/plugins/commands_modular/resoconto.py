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
        m = EVERY_RE.fullmatch(value)
        if not m:
            return None, None
        return int(m.group(1)), m.group(2)

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

    async def _send_channel_aura(interaction: discord.Interaction, *, window) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in un canale guild.")
            return
        if not await check_permission(interaction, "aura", ctx):
            return
        if ctx.channel_summary is None:
            await send_ephemeral(interaction, "❌ Servizio resoconto non disponibile.")
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
            await interaction.followup.send("⚠️ Nessun dato aura rilevante nel periodo.", ephemeral=True)
            return
        await interaction.followup.send(embed=embed)

    async def _run_server_aura_report(interaction: discord.Interaction, *, start_dt, end_dt, period_label: str) -> None:
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

        top_pos = "\n".join([f"• +{r['total']} → <@{r['user_id']}> — {await _user_reasons(str(r['user_id']), positive=True)}" for r in report["top_positive"]]) or "• Nessun dato rilevante nel periodo."
        top_neg = "\n".join([f"• {r['total']} → <@{r['user_id']}> — {await _user_reasons(str(r['user_id']), positive=False)}" for r in report["top_negative"]]) or "• Nessun dato rilevante nel periodo."
        reasons = "\n".join(f"• {item['total']:+d} per {aura_reason_to_human(item['reason_code'])}" for item in report["by_reason"][:6]) or "• Nessun dato rilevante nel periodo."
        channels = "\n".join(f"• {channel_map.get(str(item['channel_id']), '#canale')}" for item in report["by_channel"][:5] if item.get("channel_id")) or "• Nessun dato rilevante nel periodo."

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

    async def _run_server_summary_window(interaction: discord.Interaction, *, schedule_type: str, window, publish_at: str | None, every: str | None) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in un canale guild.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        if ctx.daily_activity_report is None:
            await send_ephemeral(interaction, "❌ Servizio report server non disponibile.")
            return

        guild_id = str(interaction.guild_id)
        channel_id = str(interaction.channel_id)
        every_value, every_unit = _parse_every(every)
        if every and every_value is None:
            await send_ephemeral(interaction, "❌ Formato `every` non valido. Usa ad esempio 1440min, 24hours, 1days.")
            return
        if every_value is not None and not publish_at:
            await send_ephemeral(interaction, "❌ Per usare `every` devi indicare anche `publish_at`.")
            return
        if schedule_type == "range" and every_value is not None:
            await send_ephemeral(interaction, "❌ I timer `range` supportano solo invio one-shot (senza `every`).")
            return
        publish_at_dt = parse_italian_datetime(publish_at) if publish_at else None
        if publish_at and publish_at_dt is None:
            await send_ephemeral(interaction, "❌ Formato `publish_at` non valido. Usa DD/MM/YYYY HH:MM.")
            return

        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)

        if publish_at_dt:
            await ctx.database.set_server_summary_auto_enabled(guild_id, True)
            await ctx.database.set_server_summary_target_channel(guild_id, channel_id)
            schedule_id = await ctx.database.create_server_summary_schedule(
                guild_id=guild_id,
                schedule_type=schedule_type,
                start_ts=window.start_dt.astimezone(timezone.utc).isoformat(),
                end_ts=window.end_dt.astimezone(timezone.utc).isoformat(),
                publish_at=publish_at_dt.astimezone(timezone.utc).isoformat(),
                repeat_every_value=every_value,
                repeat_every_unit=every_unit,
                created_by=str(interaction.user.id),
            )
            suffix = f" ogni {every_value}{every_unit}" if every_value and every_unit else ""
            await interaction.followup.send(f"✅ Timer server creato (id={schedule_id}) per {publish_at}{suffix}.", ephemeral=True)
            return

        await ctx.daily_activity_report.send_window(guild_id=guild_id, mod_channel_id=channel_id, window=window)
        await interaction.followup.send("✅ Resoconto server inviato ora.", ephemeral=True)

    async def _run_channel_summary_window(interaction: discord.Interaction, *, schedule_type: str, window, publish_at: str | None, every: str | None) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in un canale guild.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        if ctx.channel_summary is None:
            await send_ephemeral(interaction, "❌ Servizio resoconto non disponibile.")
            return

        guild_id = str(interaction.guild_id)
        channel_id = str(interaction.channel_id)
        every_value, every_unit = _parse_every(every)
        if every and every_value is None:
            await send_ephemeral(interaction, "❌ Formato `every` non valido. Usa ad esempio 1440min, 24hours, 1days.")
            return
        if every_value is not None and not publish_at:
            await send_ephemeral(interaction, "❌ Per usare `every` devi indicare anche `publish_at`.")
            return
        if schedule_type == "range" and every_value is not None:
            await send_ephemeral(interaction, "❌ I timer `range` supportano solo invio one-shot (senza `every`).")
            return
        publish_at_dt = parse_italian_datetime(publish_at) if publish_at else None
        if publish_at and publish_at_dt is None:
            await send_ephemeral(interaction, "❌ Formato `publish_at` non valido. Usa DD/MM/YYYY HH:MM.")
            return

        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)
        if publish_at_dt:
            await ctx.database.set_channel_summary_auto_enabled(guild_id, channel_id, True)
            schedule_id = await ctx.database.create_channel_summary_schedule(
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
            suffix = f" ogni {every_value}{every_unit}" if every_value and every_unit else ""
            await interaction.followup.send(f"✅ Timer creato (id={schedule_id}) per {publish_at}{suffix}.", ephemeral=True)
            return

        sent = await ctx.channel_summary.generate_and_send_for_channel(guild_id, channel_id, manual=True, window=window)
        await interaction.followup.send("✅ Resoconto canale inviato ora." if sent else "⚠️ Non sono riuscito a inviare il resoconto in questo canale.", ephemeral=True)

    def _format_window_details(row: dict[str, object], key: str = "type") -> str:
        schedule_type = str(row.get(key) or "oggi")
        if schedule_type == "range":
            return f"{_fmt_schedule_ts(str(row.get('start_ts') or ''))} → {_fmt_schedule_ts(str(row.get('end_ts') or ''))}"
        return schedule_type

    # /resocontocanale
    @resocontocanale_group.command(name="oggi", description="Resoconto canale di oggi")
    @app_commands.describe(publish_at="Prima pubblicazione (DD/MM/YYYY HH:MM)", every="Intervallo ripetizione: es 1440min")
    async def canale_oggi(interaction: discord.Interaction, publish_at: str | None = None, every: str | None = None) -> None:
        await _run_channel_summary_window(interaction, schedule_type="oggi", window=resolve_oggi_window(), publish_at=publish_at, every=every)

    @resocontocanale_group.command(name="ieri", description="Resoconto canale di ieri")
    @app_commands.describe(publish_at="Prima pubblicazione (DD/MM/YYYY HH:MM)", every="Intervallo ripetizione: es 1440min")
    async def canale_ieri(interaction: discord.Interaction, publish_at: str | None = None, every: str | None = None) -> None:
        await _run_channel_summary_window(interaction, schedule_type="ieri", window=resolve_ieri_window(), publish_at=publish_at, every=every)

    @resocontocanale_group.command(name="ultimi", description="Resoconto canale ultimi N periodi")
    @app_commands.describe(quantita="Numero di unità", unita="Unità di tempo", publish_at="Prima pubblicazione (DD/MM/YYYY HH:MM)", every="Intervallo ripetizione: es 1440min")
    @app_commands.choices(unita=[app_commands.Choice(name="minuti", value="minuti"), app_commands.Choice(name="ore", value="ore"), app_commands.Choice(name="giorni", value="giorni"), app_commands.Choice(name="settimane", value="settimane")])
    async def canale_ultimi(interaction: discord.Interaction, quantita: int, unita: app_commands.Choice[str], publish_at: str | None = None, every: str | None = None) -> None:
        window, error = resolve_ultimi_window(quantita, unita.value, ctx.config)
        if error:
            await send_ephemeral(interaction, error)
            return
        await _run_channel_summary_window(interaction, schedule_type="ultimi", window=window, publish_at=publish_at, every=every)

    @resocontocanale_group.command(name="range", description="Resoconto canale per intervallo")
    async def canale_range(interaction: discord.Interaction, da: str, a: str, publish_at: str | None = None, every: str | None = None) -> None:
        window, error = resolve_range_window(da, a, ctx.config)
        if error:
            await send_ephemeral(interaction, error)
            return
        await _run_channel_summary_window(interaction, schedule_type="range", window=window, publish_at=publish_at, every=every)

    @resocontocanale_group.command(name="on", description="Abilita pubblicazioni automatiche per il canale")
    async def canale_on(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in un canale guild.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        await ctx.database.set_channel_summary_auto_enabled(str(interaction.guild_id), str(interaction.channel_id), True)
        await send_ephemeral(interaction, "✅ Resoconto canale automatico attivato per questo canale.")

    @resocontocanale_group.command(name="off", description="Disabilita pubblicazioni automatiche per il canale")
    async def canale_off(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in un canale guild.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        await ctx.database.set_channel_summary_auto_enabled(str(interaction.guild_id), str(interaction.channel_id), False)
        await send_ephemeral(interaction, "✅ Resoconto canale automatico disattivato per questo canale.")

    @resocontocanale_group.command(name="status", description="Mostra stato e schedule del resoconto canale")
    async def canale_status(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in un canale guild.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        gid, cid = str(interaction.guild_id), str(interaction.channel_id)
        enabled = await ctx.database.get_channel_summary_auto_enabled(gid, cid)
        rows = await ctx.database.list_channel_summary_schedules(gid, cid)
        lines = []
        for row in rows:
            row_map = dict(row)
            recurrence = f"ogni {row_map['repeat_every_value']}{row_map['repeat_every_unit']}" if row_map.get("repeat_every_value") else "one-shot"
            lines.append(f"• ID {row_map['id']} — {str(row_map.get('status') or 'active').upper()}\n  tipo: {row_map['type']} ({_format_window_details(row_map, 'type')})\n  prossimo invio: {_fmt_schedule_ts(str(row_map.get('next_run_at') or row_map.get('publish_at') or ''))}\n  ricorrenza: {recurrence}")
        await send_ephemeral(interaction, f"ℹ️ Automatico canale: {'ON' if enabled else 'OFF'}\n" + ("\n".join(lines) if lines else "• Nessun timer presente per questo canale."))

    @resocontocanale_group.command(name="edit", description="Modifica un timer del resoconto canale")
    async def canale_edit(interaction: discord.Interaction, schedule_id: int, publish_at: str | None = None, every: str | None = None, enabled: bool | None = None) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in un canale guild.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        row = await ctx.database.get_channel_summary_schedule(schedule_id=schedule_id, guild_id=str(interaction.guild_id), channel_id=str(interaction.channel_id))
        if row is None:
            await send_ephemeral(interaction, "❌ Timer non trovato in questo canale.")
            return
        publish_dt = parse_italian_datetime(publish_at) if publish_at else None
        normalized_every = (every or "").strip().lower()
        every_value, every_unit = _parse_every(every)
        if every and every_value is None and normalized_every not in {"off", "none"}:
            await send_ephemeral(interaction, "❌ Formato `every` non valido.")
            return
        if normalized_every in {"off", "none"}:
            every_value, every_unit = None, None
        if every is None:
            every_value = int(row["repeat_every_value"]) if row["repeat_every_value"] is not None else None
            every_unit = str(row["repeat_every_unit"] or "") or None
        status_value = "active" if enabled else "disabled" if enabled is not None else None
        ok = await ctx.database.update_channel_summary_schedule(schedule_id=schedule_id, guild_id=str(interaction.guild_id), channel_id=str(interaction.channel_id), publish_at=publish_dt.astimezone(timezone.utc).isoformat() if publish_dt else None, repeat_every_value=every_value, repeat_every_unit=every_unit, status=status_value)
        await send_ephemeral(interaction, f"✅ Timer {schedule_id} aggiornato." if ok else "❌ Timer non trovato in questo canale.")

    @resocontocanale_group.command(name="delete", description="Elimina un timer del resoconto canale")
    async def canale_delete(interaction: discord.Interaction, schedule_id: int) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in un canale guild.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        deleted = await ctx.database.delete_channel_summary_schedule(schedule_id=schedule_id, guild_id=str(interaction.guild_id), channel_id=str(interaction.channel_id))
        await send_ephemeral(interaction, f"✅ Timer {schedule_id} eliminato." if deleted else "❌ Timer non trovato in questo canale.")

    @resocontocanale_group.command(name="clear", description="Elimina tutti i timer del canale corrente")
    async def canale_clear(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in un canale guild.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        removed = await ctx.database.clear_channel_summary_schedules(guild_id=str(interaction.guild_id), channel_id=str(interaction.channel_id))
        await send_ephemeral(interaction, f"✅ Timer rimossi: {removed}.")

    canale_aura_group = app_commands.Group(name="aura", description="Dettaglio Aura canale (manuale)")
    @canale_aura_group.command(name="oggi", description="Dettaglio Aura canale di oggi")
    async def canale_aura_oggi(interaction: discord.Interaction) -> None:
        await _send_channel_aura(interaction, window=resolve_oggi_window())
    @canale_aura_group.command(name="ieri", description="Dettaglio Aura canale di ieri")
    async def canale_aura_ieri(interaction: discord.Interaction) -> None:
        await _send_channel_aura(interaction, window=resolve_ieri_window())
    @canale_aura_group.command(name="ultimi", description="Dettaglio Aura canale ultimi N periodi")
    @app_commands.choices(unita=[app_commands.Choice(name="minuti", value="minuti"), app_commands.Choice(name="ore", value="ore"), app_commands.Choice(name="giorni", value="giorni"), app_commands.Choice(name="settimane", value="settimane")])
    async def canale_aura_ultimi(interaction: discord.Interaction, quantita: int, unita: app_commands.Choice[str]) -> None:
        window, error = resolve_ultimi_window(quantita, unita.value, ctx.config)
        if error:
            await send_ephemeral(interaction, error)
            return
        await _send_channel_aura(interaction, window=window)
    @canale_aura_group.command(name="range", description="Dettaglio Aura canale intervallo")
    async def canale_aura_range(interaction: discord.Interaction, da: str, a: str) -> None:
        window, error = resolve_range_window(da, a, ctx.config)
        if error:
            await send_ephemeral(interaction, error)
            return
        await _send_channel_aura(interaction, window=window)
    resocontocanale_group.add_command(canale_aura_group)

    # /resocontoserver
    @resocontoserver_group.command(name="oggi", description="Resoconto server di oggi")
    async def server_oggi(interaction: discord.Interaction, publish_at: str | None = None, every: str | None = None) -> None:
        await _run_server_summary_window(interaction, schedule_type="oggi", window=resolve_oggi_window(), publish_at=publish_at, every=every)

    @resocontoserver_group.command(name="ieri", description="Resoconto server di ieri")
    async def server_ieri(interaction: discord.Interaction, publish_at: str | None = None, every: str | None = None) -> None:
        await _run_server_summary_window(interaction, schedule_type="ieri", window=resolve_ieri_window(), publish_at=publish_at, every=every)

    @resocontoserver_group.command(name="ultimi", description="Resoconto server ultimi N periodi")
    @app_commands.choices(unita=[app_commands.Choice(name="minuti", value="minuti"), app_commands.Choice(name="ore", value="ore"), app_commands.Choice(name="giorni", value="giorni"), app_commands.Choice(name="settimane", value="settimane")])
    async def server_ultimi(interaction: discord.Interaction, quantita: int, unita: app_commands.Choice[str], publish_at: str | None = None, every: str | None = None) -> None:
        window, error = resolve_ultimi_window(quantita, unita.value, ctx.config)
        if error:
            await send_ephemeral(interaction, error)
            return
        await _run_server_summary_window(interaction, schedule_type="ultimi", window=window, publish_at=publish_at, every=every)

    @resocontoserver_group.command(name="range", description="Resoconto server intervallo")
    async def server_range(interaction: discord.Interaction, da: str, a: str, publish_at: str | None = None, every: str | None = None) -> None:
        window, error = resolve_range_window(da, a, ctx.config)
        if error:
            await send_ephemeral(interaction, error)
            return
        await _run_server_summary_window(interaction, schedule_type="range", window=window, publish_at=publish_at, every=every)

    @resocontoserver_group.command(name="on", description="Abilita resoconto server automatico")
    async def server_on(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in server.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        await ctx.database.set_server_summary_auto_enabled(str(interaction.guild_id), True)
        await ctx.database.set_server_summary_target_channel(str(interaction.guild_id), str(interaction.channel_id))
        await send_ephemeral(interaction, "✅ Resoconto server automatico attivato per questo server.")

    @resocontoserver_group.command(name="off", description="Disabilita resoconto server automatico")
    async def server_off(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in server.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        await ctx.database.set_server_summary_auto_enabled(str(interaction.guild_id), False)
        await send_ephemeral(interaction, "✅ Resoconto server automatico disattivato.")

    @resocontoserver_group.command(name="status", description="Mostra stato e timer server")
    async def server_status(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in server.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        gid = str(interaction.guild_id)
        enabled = await ctx.database.get_server_summary_auto_enabled(gid)
        target = await ctx.database.get_server_summary_target_channel(gid)
        rows = await ctx.database.list_server_summary_schedules(gid)
        lines = []
        for row in rows:
            row_map = dict(row)
            recurrence = f"ogni {row_map['repeat_every_value']}{row_map['repeat_every_unit']}" if row_map.get("repeat_every_value") else "one-shot"
            lines.append(f"• ID {row_map['id']} — {str(row_map.get('status') or 'active').upper()}\n  tipo: {row_map['schedule_type']} ({_format_window_details(row_map, 'schedule_type')})\n  prossimo invio: {_fmt_schedule_ts(str(row_map.get('next_run_at') or row_map.get('publish_at') or ''))}\n  ricorrenza: {recurrence}")
        await send_ephemeral(interaction, f"ℹ️ Automatico server: {'ON' if enabled else 'OFF'}\nCanale target: {f'<#{target}>' if target else 'n/d'}\n" + ("\n".join(lines) if lines else "• Nessun timer server presente."))

    @resocontoserver_group.command(name="edit", description="Modifica un timer server")
    async def server_edit(interaction: discord.Interaction, schedule_id: int, publish_at: str | None = None, every: str | None = None, enabled: bool | None = None) -> None:
        if interaction.guild_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in server.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        row = await ctx.database.get_server_summary_schedule(schedule_id=schedule_id, guild_id=str(interaction.guild_id))
        if row is None:
            await send_ephemeral(interaction, "❌ Timer server non trovato.")
            return
        publish_dt = parse_italian_datetime(publish_at) if publish_at else None
        normalized_every = (every or "").strip().lower()
        every_value, every_unit = _parse_every(every)
        if every and every_value is None and normalized_every not in {"off", "none"}:
            await send_ephemeral(interaction, "❌ Formato `every` non valido.")
            return
        if normalized_every in {"off", "none"}:
            every_value, every_unit = None, None
        if every is None:
            every_value = int(row["repeat_every_value"]) if row["repeat_every_value"] is not None else None
            every_unit = str(row["repeat_every_unit"] or "") or None
        ok = await ctx.database.update_server_summary_schedule(schedule_id=schedule_id, guild_id=str(interaction.guild_id), publish_at=publish_dt.astimezone(timezone.utc).isoformat() if publish_dt else None, repeat_every_value=every_value, repeat_every_unit=every_unit, enabled=enabled, status=("active" if enabled else "disabled") if enabled is not None else None)
        await send_ephemeral(interaction, f"✅ Timer server {schedule_id} aggiornato." if ok else "❌ Timer server non trovato.")

    @resocontoserver_group.command(name="delete", description="Elimina un timer server")
    async def server_delete(interaction: discord.Interaction, schedule_id: int) -> None:
        if interaction.guild_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in server.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        deleted = await ctx.database.delete_server_summary_schedule(schedule_id=schedule_id, guild_id=str(interaction.guild_id))
        await send_ephemeral(interaction, f"✅ Timer server {schedule_id} eliminato." if deleted else "❌ Timer server non trovato.")

    @resocontoserver_group.command(name="clear", description="Elimina tutti i timer server")
    async def server_clear(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in server.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        removed = await ctx.database.clear_server_summary_schedules(guild_id=str(interaction.guild_id))
        await send_ephemeral(interaction, f"✅ Timer server rimossi: {removed}.")

    server_aura_group = app_commands.Group(name="aura", description="Dettaglio Aura server (manuale)")
    @server_aura_group.command(name="oggi", description="Dettaglio Aura server di oggi")
    async def server_aura_oggi(interaction: discord.Interaction) -> None:
        w = resolve_oggi_window()
        await _run_server_aura_report(interaction, start_dt=w.start_dt, end_dt=w.end_dt, period_label="oggi")
    @server_aura_group.command(name="ieri", description="Dettaglio Aura server di ieri")
    async def server_aura_ieri(interaction: discord.Interaction) -> None:
        w = resolve_ieri_window()
        await _run_server_aura_report(interaction, start_dt=w.start_dt, end_dt=w.end_dt, period_label="ieri")
    @server_aura_group.command(name="ultimi", description="Dettaglio Aura server ultimi N periodi")
    @app_commands.choices(unita=[app_commands.Choice(name="minuti", value="minuti"), app_commands.Choice(name="ore", value="ore"), app_commands.Choice(name="giorni", value="giorni"), app_commands.Choice(name="settimane", value="settimane")])
    async def server_aura_ultimi(interaction: discord.Interaction, quantita: int, unita: app_commands.Choice[str]) -> None:
        window, error = resolve_ultimi_window(quantita, unita.value, ctx.config)
        if error:
            await send_ephemeral(interaction, error)
            return
        await _run_server_aura_report(interaction, start_dt=window.start_dt, end_dt=window.end_dt, period_label="ultimi")
    @server_aura_group.command(name="range", description="Dettaglio Aura server intervallo")
    async def server_aura_range(interaction: discord.Interaction, da: str, a: str) -> None:
        window, error = resolve_range_window(da, a, ctx.config)
        if error:
            await send_ephemeral(interaction, error)
            return
        await _run_server_aura_report(interaction, start_dt=window.start_dt, end_dt=window.end_dt, period_label="range")
    resocontoserver_group.add_command(server_aura_group)
