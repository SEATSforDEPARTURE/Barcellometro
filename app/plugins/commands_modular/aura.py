from __future__ import annotations

import json
import logging
from io import BytesIO
from datetime import timezone

import discord

from app.services.footer import attach_footer_meta
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.settings import get_setting
from app.plugins.commands_modular.time_windows import (
    TimeWindowResult,
    build_period_label,
    resolve_ieri_window,
    resolve_oggi_window,
    resolve_range_window,
    resolve_ultimi_window,
)
from app.services.aura import build_discord_jump_link, resolve_aura_reason_label, compute_and_store_aura_result
from app.services.aura_render import AuraRenderPayload, AuraTrendInfo, build_aura_embeds
from app.services.config_file_loader import load_json_file
from app.services.barcello_window import resolve_default_window_minutes
from app.utils.command_embeds import send_standard_response

logger = logging.getLogger(__name__)
BARCELLO_TRIGGER_CONFIG_PATH = "settings/barcello_trigger.json"


def register_aura(aura_group: app_commands.Group, ctx: CommandContext) -> None:
    async def send_ephemeral(interaction: discord.Interaction, message: str) -> None:
        text = str(message or "").strip()
        kind = "info"
        if text.startswith("✅"):
            kind = "success"
        elif text.startswith("⚠️"):
            kind = "warning"
        elif text.startswith("❌"):
            kind = "error"
        await send_standard_response(
            interaction,
            top_level="aura",
            subcommand_path=str(getattr(getattr(interaction, "command", None), "qualified_name", "") or "aura"),
            lines=[("dettaglio", text.lstrip("✅⚠️❌ℹ️ ").strip() or "Nessun dettaglio disponibile.")],
            kind=kind,
            footer_service=ctx.footer,
            ephemeral=interaction.guild_id is not None,
        )

    async def _resolve_default_window_for_aura(interaction: discord.Interaction) -> TimeWindowResult:
        raw_default = await get_setting(ctx, "barcello.default_window_minutes", "30")
        trigger_config = load_json_file(BARCELLO_TRIGGER_CONFIG_PATH)
        resolved = resolve_default_window_minutes(interaction.channel_id or 0, raw_default, trigger_config)
        return resolve_ultimi_window(max(1, resolved), "minuti", ctx.config)[0] or resolve_oggi_window()

    def _trend_direction(delta: int) -> tuple[str, str]:
        if delta >= 3:
            return "improving", "Segnali più costruttivi rispetto alla finestra precedente."
        if delta <= -3:
            return "worsening", "Sono emersi più attriti rispetto alla finestra precedente."
        return "stable", "Andamento vicino alla finestra precedente."

    def _period_prefix(period_key: str) -> str:
        mapping = {
            "oggi": "Oggi",
            "ieri": "Ieri",
        }
        return mapping.get(period_key, "")

    def _format_period_line(period_key: str, period_text: str, start_dt, end_dt) -> str:
        prefix = _period_prefix(period_key)
        if period_key == "ultimi":
            label = period_text
        elif period_key == "range":
            label = "Range"
        else:
            label = prefix
        return f"{label} {start_dt.strftime('%d/%m/%Y %H:%M')} → {end_dt.strftime('%d/%m/%Y %H:%M')}".strip()

    def _resolve_event_reason_label(event: dict[str, object], *, audience: str) -> str:
        reason = str(event.get("reason_code", "evento"))
        meta = event.get("meta", {}) if isinstance(event.get("meta"), dict) else {}
        completion_text = str(meta.get("completion_text") or "").strip()
        if reason == "mission_completed" and completion_text:
            return f"per {completion_text}"
        return resolve_aura_reason_label(reason, audience=audience)

    def _is_aggregate_reason(reason_code: str) -> bool:
        return reason_code in {"ondemand.aggregate", "batch.aggregate"}

    def _timeline_event_line(
        event: dict[str, object],
        *,
        channel_map: dict[str, str],
        audience: str,
        with_jump_link: bool,
        guild_id: str | None = None,
        include_reason_rule: bool = False,
    ) -> str | None:
        delta = int(event.get("delta_points", 0) or 0)
        reason = str(event.get("reason_code", "evento"))
        if _is_aggregate_reason(reason):
            return None

        channel_id = str(event.get("channel_id") or "")
        channel_name = channel_map.get(channel_id) if channel_id else None
        label = _resolve_event_reason_label(event, audience=audience)
        place = f" in {channel_name}" if channel_name else ""

        if not with_jump_link:
            emoji = "👍" if delta >= 0 else "👎"
            return f"{emoji} **{delta:+d} P.A.** {label}{place}."

        meta = event.get("meta", {}) if isinstance(event.get("meta"), dict) else {}
        message_id = str(event.get("message_id") or meta.get("message_id") or "")
        ts = str(event.get("ts", ""))
        try:
            from datetime import datetime as _dt

            dt = _dt.fromisoformat(ts.replace("Z", "+00:00"))
            ts_label = dt.strftime("%d/%m %H:%M")
        except Exception:
            ts_label = ts
        jump = build_discord_jump_link(guild_id or "", channel_id or None, message_id or None)
        head = f"[{ts_label}]({jump})" if jump else ts_label
        side = "👍" if delta >= 0 else "👎"
        suffix = f" *(regola: {reason})*" if include_reason_rule else ""
        return f"**{head} {side} {delta:+d} P.A.** {label}{place}.{suffix}"

    def _ledger_lines(ledger_events: list[dict[str, object]], channel_map: dict[str, str], guild_id: str) -> list[str]:
        lines: list[str] = []
        for event in ledger_events:
            line = _timeline_event_line(
                event,
                channel_map=channel_map,
                audience="user",
                with_jump_link=True,
                guild_id=guild_id,
            )
            if line:
                lines.append(line)
        if not lines:
            return ["Nessun evento aura dettagliato registrato nel periodo."]
        return lines[:10]

    def _points_timeline_lines(ledger_events: list[dict[str, object]], guild_id: str, channel_map: dict[str, str]) -> list[str]:
        lines: list[str] = []
        for event in ledger_events[:20]:
            line = _timeline_event_line(
                event,
                channel_map=channel_map,
                audience="mod",
                with_jump_link=True,
                guild_id=guild_id,
                include_reason_rule=True,
            )
            if line:
                lines.append(f"• {line}")
        return lines or ["• Nessun evento aura dettagliato registrato nel periodo."]

    def _points_timeline_text_lines(ledger_events: list[dict[str, object]], channel_map: dict[str, str]) -> list[str]:
        lines: list[str] = []
        for event in ledger_events[:50]:
            delta = int(event.get("delta_points", 0) or 0)
            reason = str(event.get("reason_code", "evento"))
            if _is_aggregate_reason(reason):
                continue
            ts = str(event.get("ts", ""))
            try:
                from datetime import datetime as _dt

                dt = _dt.fromisoformat(ts.replace("Z", "+00:00"))
                ts_label = dt.strftime("%d/%m %H:%M")
            except Exception:
                ts_label = ts
            side = "😇" if delta >= 0 else "😈"
            label = _resolve_event_reason_label(event, audience="mod")
            channel_id = str(event.get("channel_id") or "")
            channel_name = channel_map.get(channel_id) if channel_id else None
            place = f" in {channel_name}" if channel_name else ""
            lines.append(f"• {ts_label} — {side} {delta:+d} P.A. — {label}{place}. (regola: {reason})")
        return lines or ["• Nessun evento aura dettagliato registrato nel periodo."]

    def _build_mod_metrics_txt(
        *,
        guild_id: str,
        user_id: str,
        start_ts: str,
        end_ts: str,
        server_points_total: int,
        channel_points_month: int,
        server_metrics: dict[str, object],
        channel_metrics: dict[str, object],
        trend_server_delta: int,
        trend_channel_delta: int,
        ledger: list[dict[str, object]],
        channel_map: dict[str, str],
        archetype_metrics: dict[str, object],
        missions: list[str],
    ) -> bytes:
        lines = [
            "=== METADATI ===",
            f"guild_id: {guild_id}",
            f"user_id: {user_id}",
            f"period_start: {start_ts}",
            f"period_end: {end_ts}",
            "scope: server + channel",
            "",
            "=== SCORE ===",
            f"punti_totali_server: {server_points_total}",
            f"punti_totali_canale_mese: {channel_points_month}",
            "",
            "=== METRICHE BASE ===",
            f"server_msg_count: {server_metrics.get('msg_count', 0)}",
            f"server_unique_interactions: {server_metrics.get('unique_interactions', 0)}",
            f"server_reply_received: {server_metrics.get('reply_received', 0)}",
            f"server_quality_counter: {server_metrics.get('quality_counter', 0)}",
            f"server_invigorate: {server_metrics.get('invigorate_events', 0)}",
            f"server_degrade: {server_metrics.get('degrade_events', 0)}",
            f"channel_msg_count: {channel_metrics.get('msg_count', 0)}",
            f"channel_unique_interactions: {channel_metrics.get('unique_interactions', 0)}",
            "",
            "=== TREND ===",
            f"trend_server_delta: {trend_server_delta:+d}",
            f"trend_channel_delta: {trend_channel_delta:+d}",
            "",
            "=== BREAKDOWN PUNTI ===",
            "",
        ]
        lines.extend(_points_timeline_text_lines(ledger, channel_map))
        lines += ["", "=== ARCHETIPI ===", json.dumps(archetype_metrics, ensure_ascii=False), "", "=== MISSIONI ==="]
        lines.extend(missions or ["Nessuna per oggi."])
        return "\n".join(lines).encode("utf-8")

    async def _compute_or_fetch_result(*, guild_id: str, user_id: str, start_ts: str, end_ts: str, channel_id: str | None):
        row = await ctx.database.fetch_latest_aura_result_covering_window(guild_id, user_id, start_ts, end_ts, channel_id=channel_id)
        if row is None:
            await compute_and_store_aura_result(
                ctx.database,
                guild_id=guild_id,
                user_id=user_id,
                start_ts=start_ts,
                end_ts=end_ts,
                channel_id=channel_id,
                reason_code="ondemand.aggregate" if channel_id is None else None,
            )
            row = await ctx.database.fetch_latest_aura_result(guild_id, user_id, start_ts, end_ts, channel_id=channel_id)
        return row

    async def _run(
        interaction: discord.Interaction,
        *,
        start_dt,
        end_dt,
        period_label: str,
        target_user: discord.Member | None = None,
    ) -> None:
        if interaction.guild_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in un server.")
            return
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)
        if not await check_permission(interaction, "aura", ctx):
            return

        aura_cfg = await ctx.entitlements.get_feature_profile_config(interaction.user, "aura")
        caller_profile, _ = await ctx.entitlements.resolve_profile_with_role_id(interaction.user)
        limits = aura_cfg.get("limits", {}) if isinstance(aura_cfg, dict) else {}
        can_target = bool(limits.get("allow_target_user", False)) or caller_profile == "mod"
        if target_user is not None and not can_target:
            await send_ephemeral(interaction, "Puoi usare /aura solo sul tuo profilo.")
            return
        member = target_user or interaction.user

        start_utc = start_dt.astimezone(timezone.utc).replace(second=0, microsecond=0)
        end_utc = end_dt.astimezone(timezone.utc).replace(second=0, microsecond=0)
        start_ts = start_utc.isoformat()
        end_ts = end_utc.isoformat()
        guild_id = str(interaction.guild_id)
        user_id = str(member.id)
        channel_id = str(interaction.channel_id) if interaction.channel_id else None

        eligibility = await ctx.aura_eligibility.evaluate_member(member, guild_id, start_ts, end_ts)
        if not eligibility.eligible:
            embed = discord.Embed(title="✨ RESOCONTO AURA", description=f"{eligibility.reason}\nPer attivarla: aumenta i messaggi nel periodo.", color=0x5865F2)
            embed.add_field(name="Periodo", value=f"{start_dt.strftime('%d/%m %H:%M')} → {end_dt.strftime('%d/%m %H:%M')}", inline=False)
            attach_footer_meta(embed, service_name="aura", used_local_processing=True)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        server_row = await _compute_or_fetch_result(guild_id=guild_id, user_id=user_id, start_ts=start_ts, end_ts=end_ts, channel_id=None)
        channel_row = await _compute_or_fetch_result(guild_id=guild_id, user_id=user_id, start_ts=start_ts, end_ts=end_ts, channel_id=channel_id)
        if server_row is None:
            await send_ephemeral(interaction, "Impossibile calcolare Aura nel periodo richiesto.")
            return

        duration = end_utc - start_utc
        prev_end = start_utc
        prev_start = prev_end - duration
        prev_server = await ctx.database.fetch_aura_metrics(guild_id, user_id, prev_start.isoformat(), prev_end.isoformat(), channel_id=None)
        cur_server = await ctx.database.fetch_aura_metrics(guild_id, user_id, start_ts, end_ts, channel_id=None)
        prev_channel = await ctx.database.fetch_aura_metrics(guild_id, user_id, prev_start.isoformat(), prev_end.isoformat(), channel_id=channel_id)
        cur_channel = await ctx.database.fetch_aura_metrics(guild_id, user_id, start_ts, end_ts, channel_id=channel_id)
        server_delta = (cur_server.get("invigorate_events", 0) - cur_server.get("degrade_events", 0)) - (
            prev_server.get("invigorate_events", 0) - prev_server.get("degrade_events", 0)
        )
        channel_delta = (cur_channel.get("invigorate_events", 0) - cur_channel.get("degrade_events", 0)) - (
            prev_channel.get("invigorate_events", 0) - prev_channel.get("degrade_events", 0)
        )
        server_dir, server_comment = _trend_direction(server_delta)
        channel_dir, channel_comment = _trend_direction(channel_delta)

        month_start = end_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        channel_month_row = await _compute_or_fetch_result(
            guild_id=guild_id,
            user_id=user_id,
            start_ts=month_start.isoformat(),
            end_ts=end_ts,
            channel_id=channel_id,
        )

        render_cfg = aura_cfg.get("render", {}) if isinstance(aura_cfg, dict) else {}
        sections = render_cfg.get("sections", []) if isinstance(render_cfg.get("sections", []), list) else []
        details_max = int(render_cfg.get("details_embeds_max", 1) or 1)
        title_prefix = str(render_cfg.get("details_title_prefix", "🗒️ DETTAGLI AURA") or "🗒️ DETTAGLI AURA")

        ledger = await ctx.database.fetch_aura_ledger_aggregate(guild_id, user_id, start_ts, end_ts)
        ledger_events = await ctx.database.fetch_aura_ledger_events(guild_id, user_id, start_ts, end_ts)
        channel_map = await ctx.database.get_channel_name_map(guild_id)
        ledger_lines = _ledger_lines(ledger_events, channel_map, guild_id)
        missions_assigned = await ctx.database.list_aura_missions_for_user(guild_id, user_id, start_ts, end_ts)
        archetype = await ctx.database.fetch_latest_archetype_profile(guild_id, user_id, period_days=90)
        archetype_metrics = json.loads(archetype["metrics_json"]) if archetype and archetype["metrics_json"] else {}

        guild_name = interaction.guild.name if interaction.guild else "Server"
        channel_name = interaction.channel.name if hasattr(interaction.channel, "name") and interaction.channel else "canale"
        period_text = build_period_label(
            period_label,
            start_dt=start_dt,
            end_dt=end_dt,
            start_ts=start_ts,
            end_ts=end_ts,
        )
        period_row = _format_period_line(period_label, period_text, start_dt, end_dt)

        embeds = build_aura_embeds(
            profile_name=caller_profile,
            aura_payload=AuraRenderPayload(
                username=member.display_name if isinstance(member, discord.Member) else getattr(member, "name", "Utente"),
                server_name=guild_name,
                channel_name=channel_name,
                period_line=period_row,
                karma_server_percent=int(server_row["karma_percent"]),
                karma_channel_percent=int(channel_row["karma_percent"]) if channel_row else int(server_row["karma_percent"]),
                server_points_total=await ctx.database.sum_aura_points(guild_id, user_id, channel_id=None),
                channel_points_month=int(channel_month_row["points_total"]) if channel_month_row else 0,
                metrics_json=str(server_row["metrics_json"] or "{}"),
                channel_metrics_json=str(channel_row["metrics_json"] or "{}") if channel_row else "{}",
                ledger=ledger,
                archetype_metrics=archetype_metrics if isinstance(archetype_metrics, dict) else {},
                assigned_missions=missions_assigned,
                points_timeline_lines=_points_timeline_lines(ledger_events, guild_id, channel_map) if caller_profile == "mod" and "details.points_timeline" in sections else None,
                trend=AuraTrendInfo(
                    server_direction=server_dir,
                    server_comment=server_comment,
                    channel_direction=channel_dir,
                    channel_comment=channel_comment,
                    server_delta=server_delta,
                    channel_delta=channel_delta,
                ),
            ),
            include_sections=sections,
            details_title_prefix=title_prefix,
            details_embeds_max=details_max,
            ledger_lines=ledger_lines,
        )

        mod_file: discord.File | None = None
        if caller_profile == "mod" and "details.metrics_aggregated" in sections:
            server_metrics = json.loads(str(server_row["metrics_json"] or "{}")) if server_row else {}
            channel_metrics = json.loads(str(channel_row["metrics_json"] or "{}")) if channel_row else {}
            missions_preview = [str(m.get("mission_id")) for m in missions_assigned] or ["Nessuna per oggi."]
            payload = _build_mod_metrics_txt(
                guild_id=guild_id,
                user_id=user_id,
                start_ts=start_ts,
                end_ts=end_ts,
                server_points_total=await ctx.database.sum_aura_points(guild_id, user_id, channel_id=None),
                channel_points_month=int(channel_month_row["points_total"]) if channel_month_row else 0,
                server_metrics=server_metrics,
                channel_metrics=channel_metrics,
                trend_server_delta=server_delta,
                trend_channel_delta=channel_delta,
                ledger=ledger_events,
                channel_map=channel_map,
                archetype_metrics=archetype_metrics if isinstance(archetype_metrics, dict) else {},
                missions=missions_preview,
            )
            mod_file = discord.File(BytesIO(payload), filename=f"aura_metrics_{guild_id}_{user_id}.txt")

        try:
            dm = await interaction.user.create_dm()
            for idx in range(0, len(embeds), 10):
                files = [mod_file] if idx == 0 and mod_file is not None else None
                await dm.send(embeds=embeds[idx : idx + 10], files=files)
            logger.info("aura dm sent: user=%s guild=%s pages=%s", str(interaction.user.id), guild_id, len(embeds))
            await send_ephemeral(interaction, "✅ Resoconto Aura inviato in DM.")
        except discord.Forbidden:
            logger.warning("aura dm blocked: user=%s guild=%s", str(interaction.user.id), guild_id)
            await send_ephemeral(interaction, "⚠️ Non posso scriverti in DM. Abilita i DM dal server e riprova.")

    @aura_group.command(name="ultimi", description="Aura ultimi N periodi")
    @app_commands.describe(quantita="Numero di unità", unita="Unità di tempo", utente="Utente target (solo mod)")
    @app_commands.choices(unita=[
        app_commands.Choice(name="minuti", value="minuti"),
        app_commands.Choice(name="ore", value="ore"),
        app_commands.Choice(name="giorni", value="giorni"),
        app_commands.Choice(name="settimane", value="settimane"),
    ])
    async def aura_ultimi(
        interaction: discord.Interaction,
        quantita: app_commands.Range[int, 1, 999] | None = None,
        unita: app_commands.Choice[str] | None = None,
        utente: discord.Member | None = None,
    ) -> None:
        if quantita is None or unita is None:
            window = await _resolve_default_window_for_aura(interaction)
        else:
            window, error = resolve_ultimi_window(quantita, unita.value, ctx.config)
            if error:
                await send_ephemeral(interaction, error)
                return
            assert window is not None
        await _run(interaction, start_dt=window.start_dt, end_dt=window.end_dt, period_label="ultimi", target_user=utente)

    @aura_group.command(name="oggi", description="Aura di oggi")
    async def aura_oggi(interaction: discord.Interaction, utente: discord.Member | None = None) -> None:
        w = resolve_oggi_window()
        await _run(interaction, start_dt=w.start_dt, end_dt=w.end_dt, period_label="oggi", target_user=utente)

    @aura_group.command(name="ieri", description="Aura di ieri")
    async def aura_ieri(interaction: discord.Interaction, utente: discord.Member | None = None) -> None:
        w = resolve_ieri_window()
        await _run(interaction, start_dt=w.start_dt, end_dt=w.end_dt, period_label="ieri", target_user=utente)

    @aura_group.command(name="range", description="Aura per intervallo")
    @app_commands.describe(da="Da (DD/MM/YYYY HH:MM)", a="A (DD/MM/YYYY HH:MM)", utente="Utente target (solo mod)")
    async def aura_range(interaction: discord.Interaction, da: str, a: str, utente: discord.Member | None = None) -> None:
        window, error = resolve_range_window(da, a, ctx.config)
        if error:
            await send_ephemeral(interaction, error)
            return
        assert window is not None
        await _run(interaction, start_dt=window.start_dt, end_dt=window.end_dt, period_label="range", target_user=utente)
