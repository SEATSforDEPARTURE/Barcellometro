from __future__ import annotations

import json
import logging
from datetime import timezone

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.time_windows import resolve_ieri_window, resolve_oggi_window, resolve_range_window, resolve_ultimi_window
from app.services.aura import compute_and_store_aura_result, render_karma_bar

logger = logging.getLogger(__name__)


def register_aura(aura_group: app_commands.Group, ctx: CommandContext) -> None:
    async def send_ephemeral(interaction: discord.Interaction, message: str) -> None:
        ephemeral = interaction.guild_id is not None
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(message, ephemeral=ephemeral)

    async def _run(interaction: discord.Interaction, *, start_dt, end_dt, target_user: discord.Member | None = None) -> None:
        if interaction.guild_id is None:
            await send_ephemeral(interaction, "Comando disponibile solo in un server.")
            return
        if not await check_permission(interaction, "aura", ctx):
            return

        member = target_user or interaction.user
        aura_cfg = await ctx.entitlements.get_feature_profile_config(interaction.user, "aura")
        limits = aura_cfg.get("limits", {}) if isinstance(aura_cfg, dict) else {}
        if target_user is not None and not bool(limits.get("allow_target_user", False)):
            await send_ephemeral(interaction, "Il tuo tier non permette target user per /aura.")
            return

        start_utc = start_dt.astimezone(timezone.utc).replace(second=0, microsecond=0)
        end_utc = end_dt.astimezone(timezone.utc).replace(second=0, microsecond=0)
        start_ts = start_utc.isoformat()
        end_ts = end_utc.isoformat()
        eligibility = await ctx.aura_eligibility.evaluate_member(member, str(interaction.guild_id), start_ts, end_ts)
        if not eligibility.eligible:
            embed = discord.Embed(title="✨ RESOCONTO AURA", description=f"{eligibility.reason}\nPer attivarla: aumenta i messaggi nel periodo.", color=0x5865F2)
            embed.add_field(name="Periodo", value=f"{start_dt.strftime('%d/%m %H:%M')} → {end_dt.strftime('%d/%m %H:%M')}", inline=False)
            embed.set_footer(text="Stima calcolata in loco: nessuna chiamata AI.")
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        row = await ctx.database.fetch_latest_aura_result_covering_window(str(interaction.guild_id), str(member.id), start_ts, end_ts, channel_id=None)
        if row is None:
            logger.info("aura ondemand compute: guild=%s user=%s start=%s end=%s", str(interaction.guild_id), str(member.id), start_ts, end_ts)
            await compute_and_store_aura_result(
                ctx.database,
                guild_id=str(interaction.guild_id),
                user_id=str(member.id),
                start_ts=start_ts,
                end_ts=end_ts,
                channel_id=None,
                reason_code="ondemand.aggregate",
            )
            row = await ctx.database.fetch_latest_aura_result(str(interaction.guild_id), str(member.id), start_ts, end_ts, channel_id=None)
        if row is None:
            error_embed = discord.Embed(
                title="✨ RESOCONTO AURA",
                description="Impossibile calcolare Aura per il periodo richiesto. Potrebbero non esserci dati sufficienti oppure il calcolo non ha prodotto output.",
                color=0xED4245,
            )
            error_embed.add_field(name="Periodo", value=f"{start_dt.strftime('%d/%m %H:%M')} → {end_dt.strftime('%d/%m %H:%M')}", inline=False)
            error_embed.set_footer(text="Stima calcolata in loco: nessuna chiamata AI.")
            if interaction.response.is_done():
                await interaction.followup.send(embed=error_embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return

        karma = int(row["karma_percent"])
        status = "🟢 Positiva" if karma >= 67 else ("🟡 Bilanciata" if karma >= 34 else "🔴 In calo")
        main = discord.Embed(
            title=f"✨ RESOCONTO AURA \"😇 / 😈 — SERVER\"",
            description=f"Periodo: {start_dt.strftime('%d/%m %H:%M')} → {end_dt.strftime('%d/%m %H:%M')}\nStato: {status}",
            color=0x5865F2,
        )
        main.add_field(name="Karma server", value=render_karma_bar(karma), inline=False)
        main.add_field(name="Narrativa", value="Trend locale calcolato con metriche di attività e impatto comunità.", inline=False)
        main.set_footer(text="Stima calcolata in loco. Eventuali imprecisioni sono possibili.")

        details_max = int((aura_cfg.get("render", {}) or {}).get("details_embeds_max", 1))
        title_prefix = str((aura_cfg.get("render", {}) or {}).get("details_title_prefix", "✨ Dettagli Aura"))
        sections = list((aura_cfg.get("render", {}) or {}).get("sections", []))

        detail_embeds: list[discord.Embed] = []
        ledger = await ctx.database.fetch_aura_ledger_aggregate(str(interaction.guild_id), str(member.id), start_ts, end_ts)
        archetype = await ctx.database.fetch_latest_archetype_profile(str(interaction.guild_id), str(member.id), period_days=30)
        archetype_metrics = json.loads(archetype["metrics_json"]) if archetype and archetype["metrics_json"] else {}
        base_metrics = json.loads(row["metrics_json"])

        sections_rendered = 0
        for i in range(max(details_max, 0)):
            if sections_rendered >= len(sections):
                break
            embed = discord.Embed(title=f"{title_prefix} (Pag {i+1}/{details_max})", color=0x2F3136)
            while sections_rendered < len(sections) and len(embed.fields) < 4:
                sec = sections[sections_rendered]
                if sec == "details.score_breakdown":
                    value = "\n".join([f"• {item['reason_code']}: {item['total']:+d}" for item in ledger[:8]]) or "• Nessun evento"
                    embed.add_field(name="Score breakdown", value=value, inline=False)
                elif sec == "details.metrics_basic":
                    embed.add_field(name="Metriche base", value=f"Volume: {base_metrics.get('msg_count',0)}\nDiversity: {base_metrics.get('unique_interactions',0)}\nInfluence: {base_metrics.get('reply_received',0)}\nConsistency: {base_metrics.get('quality_counter',0)}", inline=False)
                elif sec == "details.metrics_advanced":
                    embed.add_field(name="Metriche avanzate", value=f"Monopoly: {max(0, 100-base_metrics.get('unique_interactions',0))}\nReplies/msg: {base_metrics.get('reply_received',0)}/{max(1, base_metrics.get('msg_count',1))}\nClimate delta: {base_metrics.get('invigorate_events',0)-base_metrics.get('degrade_events',0)}", inline=False)
                elif sec == "details.flags_mod" and bool((aura_cfg.get("privacy", {}) or {}).get("show_mod_flags", False)):
                    embed.add_field(name="Flag mod", value="Nessun flag sensibile esposto in v1.", inline=False)
                elif sec == "details.missions" and bool((aura_cfg.get("missions", {}) or {}).get("enabled", False)):
                    embed.add_field(name="Missioni", value="• Rispondi a 3 utenti nuovi\n• Mantieni tono costruttivo\n• Contribuisci in 2 canali", inline=False)
                elif sec == "details.interactions_top":
                    embed.add_field(name="Top interazioni", value="Classifica interazioni disponibile in v1.1", inline=False)
                elif sec == "details.topics":
                    insights = archetype_metrics.get("insights", []) if isinstance(archetype_metrics, dict) else []
                    embed.add_field(name="Insights", value="\n".join(f"• {x}" for x in insights[:3]) or "• Nessun insight", inline=False)
                sections_rendered += 1
            if embed.fields:
                detail_embeds.append(embed)

        if not interaction.response.is_done():
            await interaction.response.send_message(embeds=[main, *detail_embeds])
        else:
            await interaction.followup.send(embeds=[main, *detail_embeds])

    @aura_group.command(name="ultimi", description="Aura ultimi N periodi")
    @app_commands.describe(quantita="Numero di unità", unita="Unità di tempo", utente="Utente target opzionale")
    @app_commands.choices(unita=[
        app_commands.Choice(name="minuti", value="minuti"),
        app_commands.Choice(name="ore", value="ore"),
        app_commands.Choice(name="giorni", value="giorni"),
        app_commands.Choice(name="settimane", value="settimane"),
    ])
    async def aura_ultimi(interaction: discord.Interaction, quantita: int, unita: app_commands.Choice[str], utente: discord.Member | None = None) -> None:
        window, error = resolve_ultimi_window(quantita, unita.value, ctx.config)
        if error:
            await send_ephemeral(interaction, error)
            return
        assert window is not None
        await _run(interaction, start_dt=window.start_dt, end_dt=window.end_dt, target_user=utente)

    @aura_group.command(name="oggi", description="Aura di oggi")
    async def aura_oggi(interaction: discord.Interaction, utente: discord.Member | None = None) -> None:
        w = resolve_oggi_window()
        await _run(interaction, start_dt=w.start_dt, end_dt=w.end_dt, target_user=utente)

    @aura_group.command(name="ieri", description="Aura di ieri")
    async def aura_ieri(interaction: discord.Interaction, utente: discord.Member | None = None) -> None:
        w = resolve_ieri_window()
        await _run(interaction, start_dt=w.start_dt, end_dt=w.end_dt, target_user=utente)

    @aura_group.command(name="range", description="Aura per intervallo")
    @app_commands.describe(da="Da (DD/MM/YYYY HH:MM)", a="A (DD/MM/YYYY HH:MM)", utente="Utente target opzionale")
    async def aura_range(interaction: discord.Interaction, da: str, a: str, utente: discord.Member | None = None) -> None:
        window, error = resolve_range_window(da, a, ctx.config)
        if error:
            await send_ephemeral(interaction, error)
            return
        assert window is not None
        await _run(interaction, start_dt=window.start_dt, end_dt=window.end_dt, target_user=utente)
