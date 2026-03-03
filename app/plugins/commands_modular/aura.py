from __future__ import annotations

import json
import logging
from datetime import timezone

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.time_windows import resolve_ieri_window, resolve_oggi_window, resolve_range_window, resolve_ultimi_window
from app.services.aura import compute_and_store_aura_result
from app.services.aura_render import AuraRenderPayload, build_aura_embeds

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
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)
        if not await check_permission(interaction, "aura", ctx):
            return

        member = target_user or interaction.user
        aura_cfg = await ctx.entitlements.get_feature_profile_config(interaction.user, "aura")
        caller_profile, _ = await ctx.entitlements.resolve_profile_with_role_id(interaction.user)
        limits = aura_cfg.get("limits", {}) if isinstance(aura_cfg, dict) else {}
        if target_user is not None and not bool(limits.get("allow_target_user", False)):
            await send_ephemeral(interaction, "Il tuo tier non permette target user per /aura.")
            return

        start_utc = start_dt.astimezone(timezone.utc).replace(second=0, microsecond=0)
        end_utc = end_dt.astimezone(timezone.utc).replace(second=0, microsecond=0)
        start_ts = start_utc.isoformat()
        end_ts = end_utc.isoformat()
        guild_id = str(interaction.guild_id)
        user_id = str(member.id)

        eligibility = await ctx.aura_eligibility.evaluate_member(member, guild_id, start_ts, end_ts)
        if not eligibility.eligible:
            embed = discord.Embed(title="✨ RESOCONTO AURA", description=f"{eligibility.reason}\nPer attivarla: aumenta i messaggi nel periodo.", color=0x5865F2)
            embed.add_field(name="Periodo", value=f"{start_dt.strftime('%d/%m %H:%M')} → {end_dt.strftime('%d/%m %H:%M')}", inline=False)
            embed.set_footer(text="Stima calcolata in loco: nessuna chiamata AI.")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        row = await ctx.database.fetch_latest_aura_result_covering_window(guild_id, user_id, start_ts, end_ts, channel_id=None)
        if row is None:
            logger.info("aura ondemand compute: guild=%s user=%s start=%s end=%s", guild_id, user_id, start_ts, end_ts)
            await compute_and_store_aura_result(
                ctx.database,
                guild_id=guild_id,
                user_id=user_id,
                start_ts=start_ts,
                end_ts=end_ts,
                channel_id=None,
                reason_code="ondemand.aggregate",
            )
            row = await ctx.database.fetch_latest_aura_result(guild_id, user_id, start_ts, end_ts, channel_id=None)
        if row is None:
            error_embed = discord.Embed(
                title="✨ RESOCONTO AURA",
                description="Impossibile calcolare Aura per il periodo richiesto. Potrebbero non esserci dati sufficienti oppure il calcolo non ha prodotto output.",
                color=0xED4245,
            )
            error_embed.add_field(name="Periodo", value=f"{start_dt.strftime('%d/%m %H:%M')} → {end_dt.strftime('%d/%m %H:%M')}", inline=False)
            await interaction.followup.send(embed=error_embed, ephemeral=True)
            return

        render_cfg = aura_cfg.get("render", {}) if isinstance(aura_cfg, dict) else {}
        sections = render_cfg.get("sections", []) if isinstance(render_cfg.get("sections", []), list) else []
        details_max = int(render_cfg.get("details_embeds_max", 1) or 1)
        title_prefix = str(render_cfg.get("details_title_prefix", "✨ DETTAGLI AURA") or "✨ DETTAGLI AURA")

        ledger = await ctx.database.fetch_aura_ledger_aggregate(guild_id, user_id, start_ts, end_ts)
        archetype = await ctx.database.fetch_latest_archetype_profile(guild_id, user_id, period_days=30)
        archetype_metrics = json.loads(archetype["metrics_json"]) if archetype and archetype["metrics_json"] else {}

        embeds = build_aura_embeds(
            profile_name=caller_profile,
            aura_payload=AuraRenderPayload(
                period_label=f"{start_dt.strftime('%d/%m %H:%M')} → {end_dt.strftime('%d/%m %H:%M')}",
                karma_percent=int(row["karma_percent"]),
                metrics_json=str(row["metrics_json"] or "{}"),
                ledger=ledger,
                archetype_metrics=archetype_metrics if isinstance(archetype_metrics, dict) else {},
            ),
            include_sections=sections,
            details_title_prefix=title_prefix,
            details_embeds_max=details_max,
        )

        try:
            dm = await interaction.user.create_dm()
            for idx in range(0, len(embeds), 10):
                await dm.send(embeds=embeds[idx : idx + 10])
            logger.info("aura dm sent: user=%s guild=%s pages=%s", str(interaction.user.id), guild_id, len(embeds))
            await interaction.followup.send("📩 Resoconto Aura inviato in DM.", ephemeral=True)
        except discord.Forbidden:
            logger.warning("aura dm blocked: user=%s guild=%s", str(interaction.user.id), guild_id)
            await interaction.followup.send("Non posso scriverti in DM. Abilita i DM dal server e riprova.", ephemeral=True)

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
