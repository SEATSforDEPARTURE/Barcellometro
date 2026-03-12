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

logger = logging.getLogger(__name__)


EVERY_RE = re.compile(r"^(\d+)\s*(min|hours|days)$")

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

    def _format_window_details(row: dict[str, object]) -> str:
        schedule_type = str(row.get("type") or "oggi")
        if schedule_type == "ultimi":
            start_raw = str(row.get("start_ts") or "")
            end_raw = str(row.get("end_ts") or "")
            try:
                start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
                delta = end_dt - start_dt
            except Exception:
                return "ultimi (durata non disponibile)"
            minutes = max(1, int(delta.total_seconds() // 60))
            if minutes < 60:
                return f"ultimi {minutes} minuti"
            if minutes < 1440:
                hours = max(1, minutes // 60)
                return f"ultime {hours} ore"
            days = max(1, minutes // 1440)
            return f"ultimi {days} giorni"
        if schedule_type == "range":
            return f"{_fmt_schedule_ts(str(row.get('start_ts') or ''))} → {_fmt_schedule_ts(str(row.get('end_ts') or ''))}"
        return schedule_type

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
        channel_summary_service = ctx.channel_summary
        if channel_summary_service is None:
            await send_ephemeral(interaction, "❌ Servizio resoconto non disponibile.")
            return

        every_value, every_unit = _parse_every(every)
        if every and every_value is None:
            await send_ephemeral(interaction, "❌ Formato `every` non valido. Usa ad esempio 1440min, 24hours, 1days.")
            return
        if every_value is not None and not publish_at:
            await send_ephemeral(interaction, "❌ Per usare `every` devi indicare anche `publish_at`.")
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
            suffix = f" ogni {every_value}{every_unit}" if every_value and every_unit else ""
            await interaction.followup.send(f"✅ Timer creato (id={schedule_id}) per {publish_at}{suffix}.", ephemeral=True)
            return

        # Terminal path: immediate execution only (no recursive helper calls).
        sent = await channel_summary_service.generate_and_send_for_channel(guild_id, channel_id, manual=True, window=window)
        await interaction.followup.send(
            "✅ Resoconto canale inviato ora." if sent else "⚠️ Non sono riuscito a inviare il resoconto in questo canale.",
            ephemeral=True,
        )
        return

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
        if not await check_permission(interaction, "riassunto", ctx):
            return
        await ctx.database.set_channel_summary_auto_enabled(str(interaction.guild_id), str(interaction.channel_id), True)
        await send_ephemeral(interaction, "✅ Resoconto canale automatico attivato per questo canale.")

    @canale_group.command(name="off", description="Disabilita pubblicazioni automatiche per il canale")
    async def canale_off(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in un canale guild.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        await ctx.database.set_channel_summary_auto_enabled(str(interaction.guild_id), str(interaction.channel_id), False)
        await send_ephemeral(interaction, "✅ Resoconto canale automatico disattivato per questo canale.")

    @canale_group.command(name="status", description="Mostra stato e schedule del resoconto canale")
    async def canale_status(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in un canale guild.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        guild_id = str(interaction.guild_id)
        channel_id = str(interaction.channel_id)
        enabled = await ctx.database.get_channel_summary_auto_enabled(guild_id, channel_id)
        schedules = await ctx.database.list_channel_summary_schedules(guild_id, channel_id)
        lines: list[str] = []
        for row in schedules:
            row_map = dict(row)
            recurrence = f"{row_map['repeat_every_value']}{row_map['repeat_every_unit']}" if row_map.get("repeat_every_value") else "one-shot"
            lines.append(
                "\n".join(
                    [
                        f"• ID {row_map['id']} — {str(row_map.get('status') or 'active').upper()}",
                        f"  tipo: {row_map['type']} ({_format_window_details(row_map)})",
                        f"  prossimo invio: {_fmt_schedule_ts(str(row_map.get('next_run_at') or row_map.get('publish_at') or ''))}",
                        f"  ultima esecuzione: {_fmt_schedule_ts(str(row_map.get('last_run_at') or ''))}",
                        f"  ricorrenza: {recurrence}",
                    ]
                )
            )
        text = "\n".join(lines) if lines else "• Nessun timer presente per questo canale."
        await send_ephemeral(interaction, f"ℹ️ Automatico canale: {'ON' if enabled else 'OFF'}\n{text}")

    @canale_group.command(name="edit", description="Modifica un timer del resoconto canale")
    @app_commands.describe(
        schedule_id="ID del timer",
        publish_at="Nuovo primo/prossimo invio DD/MM/YYYY HH:MM",
        every="Nuova ricorrenza (es: 12hours) o vuoto per one-shot",
        enabled="Abilita/disabilita il singolo timer",
    )
    async def canale_edit(
        interaction: discord.Interaction,
        schedule_id: int,
        publish_at: str | None = None,
        every: str | None = None,
        enabled: bool | None = None,
    ) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in un canale guild.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        guild_id = str(interaction.guild_id)
        channel_id = str(interaction.channel_id)
        row = await ctx.database.get_channel_summary_schedule(
            schedule_id=schedule_id,
            guild_id=guild_id,
            channel_id=channel_id,
        )
        if row is None:
            await send_ephemeral(interaction, "❌ Timer non trovato in questo canale.")
            return
        publish_dt = parse_italian_datetime(publish_at) if publish_at else None
        if publish_at and publish_dt is None:
            await send_ephemeral(interaction, "❌ Formato `publish_at` non valido. Usa DD/MM/YYYY HH:MM.")
            return
        every_value, every_unit = _parse_every(every)
        if every and every_value is None:
            await send_ephemeral(interaction, "❌ Formato `every` non valido. Usa ad esempio 1440min, 24hours, 1days.")
            return
        if every is None:
            every_value = int(row["repeat_every_value"]) if row["repeat_every_value"] is not None else None
            every_unit = str(row["repeat_every_unit"] or "") or None
        status_value: str | None = None
        if enabled is not None:
            status_value = "active" if enabled else "disabled"
        ok = await ctx.database.update_channel_summary_schedule(
            schedule_id=schedule_id,
            guild_id=guild_id,
            channel_id=channel_id,
            publish_at=publish_dt.astimezone(timezone.utc).isoformat() if publish_dt else None,
            repeat_every_value=every_value,
            repeat_every_unit=every_unit,
            status=status_value,
        )
        if not ok:
            await send_ephemeral(interaction, "❌ Timer non trovato in questo canale.")
            return
        await send_ephemeral(interaction, f"✅ Timer {schedule_id} aggiornato.")

    @canale_group.command(name="delete", description="Elimina un timer del resoconto canale")
    @app_commands.describe(schedule_id="ID del timer da eliminare")
    async def canale_delete(interaction: discord.Interaction, schedule_id: int) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in un canale guild.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        deleted = await ctx.database.delete_channel_summary_schedule(
            schedule_id=schedule_id,
            guild_id=str(interaction.guild_id),
            channel_id=str(interaction.channel_id),
        )
        if not deleted:
            await send_ephemeral(interaction, "❌ Timer non trovato in questo canale.")
            return
        await send_ephemeral(interaction, f"✅ Timer {schedule_id} eliminato.")

    @canale_group.command(name="clear", description="Elimina tutti i timer del canale corrente")
    async def canale_clear(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in un canale guild.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        removed = await ctx.database.clear_channel_summary_schedules(
            guild_id=str(interaction.guild_id),
            channel_id=str(interaction.channel_id),
        )
        await send_ephemeral(interaction, f"✅ Timer rimossi: {removed}.")

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
