from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import discord

from app.core.config_paths import BARCELLO_TRIGGER_JSON
from app.services.footer import attach_footer_meta
from discord import app_commands

from app.services.entitlements import EntitlementsService
from app.services.config_file_loader import load_json_file
from app.features.barcello.services.barcello_window_defaults import resolve_default_window_minutes
from app.plugins.commands_modular.command_helpers import add_group_once
from app.shared.discord.embed_limits import _split_field_chunks
from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.settings import get_setting
from app.shared.discord.command_embeds import send_standard_response
from app.shared.discord.component_notices import send_standard_component_notice
from app.shared.discord.report_embeds import apply_standard_report_style
from app.domain.reporting.trend import normalize_trend, render_trend, render_trend_value

logger = logging.getLogger(__name__)



def register_barcello(bm_group: app_commands.Group, ctx: CommandContext) -> None:
    response_format_supported: bool | None = None
    barcello_group = app_commands.Group(name="barcello", description="Barcello controls")
    add_group_once(bm_group, barcello_group, logger)

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
            top_level="barcello",
            subcommand_path=str(getattr(getattr(interaction, "command", None), "qualified_name", "") or "bm barcello"),
            lines=[("dettaglio", text.lstrip("✅⚠️❌ℹ️ ").strip() or "Nessun dettaglio disponibile.")],
            kind=kind,
            footer_service=ctx.footer,
            ephemeral=interaction.guild_id is not None,
        )

    async def _require_channel_scope(interaction: discord.Interaction) -> tuple[str, str] | None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "This command only works in guild channels.")
            return None
        return str(interaction.guild_id), str(interaction.channel_id)

    async def _send_barcello_dm_notice(interaction: discord.Interaction, *, sent: bool, blocked_message: str | None = None) -> None:
        if sent:
            await send_standard_response(
                interaction,
                top_level="barcello",
                subcommand_path="bm barcello run",
                lines=[("result", "Ti ho inviato un DM")],
                kind="success",
                footer_service=ctx.footer,
            )
            return
        await send_standard_response(
            interaction,
            top_level="barcello",
            subcommand_path="bm barcello run",
            lines=[("error", blocked_message or "Non riesco a inviarti DM. Abilita i messaggi privati dal server.")],
            kind="error",
            footer_service=ctx.footer,
        )

    def _build_barcello_dm_report(*, public_embed: discord.Embed, details_embed: discord.Embed) -> list[discord.Embed]:
        return apply_standard_report_style(
            [public_embed, details_embed],
            service_name="barcello",
            cover_title=public_embed.title or "❤️ REPORT BARCELLO",
        )

    async def _set_toggle(interaction: discord.Interaction, action: str) -> None:
        if not await check_permission(interaction, f"bm.barcello.{action}", ctx):
            return
        scope = await _require_channel_scope(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        if action == "status":
            enabled = await ctx.database.get_trigger_enabled(guild_id, channel_id, "barcello")
            await send_ephemeral(interaction, f"Barcello trigger is {'on' if enabled else 'off'} for this channel.")
            return
        enabled = action == "on"
        await ctx.database.set_trigger_enabled(guild_id, channel_id, "barcello", enabled)
        await send_ephemeral(interaction, f"Barcello trigger {'enabled' if enabled else 'disabled'} for this channel.")

    async def _show_mood(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.barcello.mood_show", ctx, legacy_aliases=["bm.barcello.mood"]):
            return
        scope = await _require_channel_scope(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        cfg = load_json_file(BARCELLO_TRIGGER_JSON)
        stored = await ctx.database.get_trigger_state(guild_id, channel_id, "barcello_mood")
        stored_mood = str(stored.get("mood") or "")

        channels_cfg = cfg.get("channels") if isinstance(cfg.get("channels"), dict) else {}
        channel_cfg = channels_cfg.get(channel_id) if isinstance(channels_cfg.get(channel_id), dict) else {}
        cfg_default = str(cfg.get("mood_default") or "chill")
        channel_default = str(channel_cfg.get("mood_default") or "")
        effective = stored_mood or channel_default or cfg_default

        time_buckets = cfg.get("time_buckets") if isinstance(cfg.get("time_buckets"), dict) else {}
        now_local = datetime.now(ctx.timezone)
        current_hour = now_local.hour
        time_bucket = "unknown"
        for name, payload in time_buckets.items():
            if not isinstance(payload, dict):
                continue
            start = payload.get("start")
            end = payload.get("end")
            if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= 24 and start <= current_hour < end:
                time_bucket = str(name)
                break

        daily = await ctx.database.get_trigger_state(guild_id, channel_id, "barcello_daily")
        day_key = now_local.date().isoformat()
        counts = daily.get("counts") if isinstance(daily.get("counts"), dict) and str(daily.get("date") or "") == day_key else {}
        last_status = await ctx.database.get_barcello_trigger_state(guild_id, channel_id)
        current_color = str((last_status or {}).get("last_color") or "")
        state_count_today = int(counts.get(current_color) or 0) if current_color else 0

        tiers = cfg.get("dramatic_tiers") if isinstance(cfg.get("dramatic_tiers"), list) else [{"min_count_today": 1, "label": "t1"}]
        drama_label = "t1"
        for tier in tiers:
            if not isinstance(tier, dict):
                continue
            minimum = tier.get("min_count_today")
            label = tier.get("label")
            if isinstance(minimum, int) and isinstance(label, str) and state_count_today >= minimum:
                drama_label = label

        await send_ephemeral(
            interaction,
            "\n".join(
                [
                    f"Current mood: `{effective}`",
                    f"Stored mood: `{stored_mood or '-'}`",
                    f"Channel default mood: `{channel_default or '-'}`",
                    f"Global default mood: `{cfg_default}`",
                    f"Current time bucket: `{time_bucket}`",
                    f"Current drama label: `{drama_label}` (count {state_count_today}, state {current_color or '-'})",
                ]
            ),
        )

    @barcello_group.command(name="on", description="Enable the Barcello trigger for this channel.")
    async def barcello_on_command(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "on")

    @barcello_group.command(name="off", description="Disable the Barcello trigger for this channel.")
    async def barcello_off_command(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "off")

    @barcello_group.command(name="status", description="Show Barcello trigger status for this channel.")
    async def barcello_status_command(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "status")

    @barcello_group.command(name="mood_set", description="Set the Barcello mood for this channel.")
    @app_commands.describe(value="Mood value.")
    async def barcello_mood_set_command(interaction: discord.Interaction, value: str) -> None:
        if not await check_permission(interaction, "bm.barcello.mood_set", ctx, legacy_aliases=["bm.barcello.mood"]):
            return
        scope = await _require_channel_scope(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        normalized = value.strip()
        if not normalized:
            await send_ephemeral(interaction, "Please provide a valid mood.")
            return
        cfg = load_json_file(BARCELLO_TRIGGER_JSON)
        available_moods = cfg.get("moods") if isinstance(cfg.get("moods"), dict) else {}
        if available_moods and normalized not in available_moods:
            await send_ephemeral(
                interaction,
                f"Mood `{normalized}` is not defined in config. Available: {', '.join(sorted(available_moods.keys()))}",
            )
            return
        today = datetime.now(ctx.timezone).date().isoformat()
        await ctx.database.set_trigger_state(
            guild_id,
            channel_id,
            "barcello_mood",
            {"mood": normalized, "date": today, "mode": "manual"},
        )
        await send_ephemeral(interaction, f"Barcello mood set to `{normalized}` for this channel.")

    @barcello_group.command(name="mood_show", description="Show the Barcello mood for this channel.")
    async def barcello_mood_show_command(interaction: discord.Interaction) -> None:
        await _show_mood(interaction)

    @barcello_group.command(name="mood_reset", description="Reset the Barcello mood for this channel.")
    async def barcello_mood_reset_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.barcello.mood_reset", ctx, legacy_aliases=["bm.barcello.mood_reset"]):
            return
        scope = await _require_channel_scope(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        await ctx.database.set_trigger_state(guild_id, channel_id, "barcello_mood", {})
        await send_ephemeral(interaction, "Barcello mood reset for this channel.")

    @barcello_group.command(name="calibrate", description="Recalculate Barcello calibration weights.")
    async def barcello_calibrate_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.barcello.calibrate", ctx):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await ctx.barcello_calibration_service.run_calibration(days=14, min_samples=20)
        if result.get("updated"):
            message = f"Calibration updated. Samples: {result.get('samples')}. {result.get('summary')}"
        else:
            message = f"Calibration not updated. Samples: {result.get('samples')}. {result.get('summary')}"
        await send_standard_response(
            interaction,
            top_level="barcello",
            subcommand_path="bm barcello calibrate",
            lines=[("samples", result.get("samples")), ("summary", result.get("summary"))],
            kind="success" if result.get("updated") else "warning",
            footer_service=ctx.footer,
            ephemeral=True,
        )

    def _render_health_bar(score: int, color_emoji: str) -> str:
        score = max(0, min(100, score))
        filled = int(round(score / 10))
        empty = max(0, 10 - filled)
        return f"{color_emoji * filled}{'⚪' * empty}"

    def _health_description(score: int) -> str:
        if score >= 90:
            return "Ottima! 😄 Il clima è disteso, positivo e molto ricettivo."
        if score >= 75:
            return "Molto buona. 😊 La conversazione scorre senza attriti."
        if score >= 60:
            return "Buona. 😃 Il clima è stabile, con lievi variazioni."
        if score >= 45:
            return "Discreta. 🤔 Clima gestibile ma con primi segnali di tensione."
        if score >= 30:
            return "Delicata. 😬 Il clima richiede cautela."
        return "Critica. 🚨 Situazione tesa e facilmente infiammabile."

    def _alert_message(score: int, color_label: str | None = None) -> str:
        if color_label:
            normalized = color_label.lower()
            if normalized == "verde":
                return "È un buon momento per scrivere e partecipare 💬"
            if normalized == "giallo":
                return "Clima un po’ teso: scrivi con calma e chiarisci se serve 🙂"
            if normalized == "rosso":
                return "Tensione alta: evita provocazioni e abbassa i toni 🧯"
            if normalized == "nero":
                return "Situazione critica: meglio fermarsi e moderare subito 🚨"
        if score >= 60:
            return "È un buon momento per scrivere e partecipare 💬"
        if score >= 45:
            return "Meglio fare attenzione ⚠️ Mantieni un tono neutro."
        if score >= 30:
            return "Situazione delicata 🟠 Meglio osservare."
        return "Alta tensione 🔴 È consigliato non intervenire ora."

    def _trend_display(trend: dict[str, Any]) -> tuple[str, str]:
        direction = trend.get("direction", "stable")
        delta = trend.get("delta", 0)
        mapping = {
            "improving": ("IN MIGLIORAMENTO", "😄"),
            "stable": ("STABILE", "😐"),
            "worsening": ("IN PEGGIORAMENTO", "😟"),
        }
        label, emoji = mapping.get(direction, ("STABILE", "😐"))
        return f"**{label}** {emoji}  *(Δ {delta})*", label

    def _format_metrics(metrics: dict[str, Any]) -> str:
        keys = [
            "message_count",
            "window_minutes",
            "msg_per_min",
            "caps_ratio",
            "negativity_hits",
            "mention_count",
            "mention_per_min",
            "reply_war",
            "top1_author_share",
            "top3_author_share",
            "max_msgs_per_minute",
            "std_msgs_per_minute",
            "burst_ratio",
            "contrast_per_msg",
            "challenge_per_msg",
            "playful_emoji_ratio",
            "passive_aggressive_emoji_ratio",
            "sarcasm_marker_hits",
            "msg_count_user_a",
            "msg_count_user_b",
            "balance_ratio",
            "mentions_a_to_b",
            "mentions_b_to_a",
            "avg_msg_len_a",
            "avg_msg_len_b",
        ]
        lines = [f"{key}: {metrics.get(key)}" for key in keys]
        return "```\n" + "\n".join(lines) + "\n```"

    def _with_spacing(text: str) -> str:
        return text

    def _add_section(embed: discord.Embed, *, name: str, value: str) -> None:
        chunks = _split_field_chunks(value, 1024)
        available = 25 - len(embed.fields)
        if available <= 0:
            return
        if len(chunks) > available:
            chunks = chunks[:available]
        for idx, chunk in enumerate(chunks):
            field_name = name if idx == 0 else f"{name} (cont.)"
            embed.add_field(name=field_name, value=chunk, inline=False)

    def _parse_hex_color(raw: str | None) -> int | None:
        if not raw:
            return None
        value = raw.strip().lower()
        if value.startswith("#"):
            value = value[1:]
        if value.startswith("0x"):
            value = value[2:]
        try:
            return int(value, 16)
        except ValueError:
            return None

    async def _get_details_embed_color(profile: str) -> int:
        default_color = 0x95A5A6
        mod_color = 0x5865F2
        admin_color = 0x9B59B6
        if profile == "admin":
            stored = await get_setting(ctx, "barcello.details_color_admin", "")
            return _parse_hex_color(stored) or admin_color
        if profile == "mod":
            stored = await get_setting(ctx, "barcello.details_color_mod", "")
            return _parse_hex_color(stored) or mod_color
        stored = await get_setting(ctx, "barcello.details_color_default", "")
        return _parse_hex_color(stored) or default_color

    async def _get_tier_label(profile: str) -> str:
        stored = await get_setting(ctx, f"barcello.tier_label.{profile}", "")
        if stored:
            return stored
        defaults = {
            "base": "Utente",
            "role1": "Utente",
            "role2": "Utente",
            "role3": "Utente",
            "mod": "Mod",
            "admin": "Admin",
        }
        return defaults.get(profile, "Utente")

    async def _resolve_tier_display_name(
        *,
        profile: str,
        winner_role_id: str | None,
        guild: discord.Guild | None,
    ) -> str:
        if profile in {"mod", "admin"}:
            return await _get_tier_label(profile)
        if winner_role_id and guild:
            role = guild.get_role(int(winner_role_id))
            if role:
                logger.info("barcello: resolved tier role name=%s (id=%s)", role.name, winner_role_id)
                return role.name
        return await _get_tier_label(profile)

    def _bullet_list(lines: list[str]) -> str:
        cleaned: list[str] = []
        for line in lines:
            text = line.strip()
            if not text:
                continue
            cleaned.append(text)
        return "\n".join(f"• {line}" for line in cleaned)

    def _clean_bullets(lines: list[str] | None) -> list[str]:
        if not lines:
            return []
        cleaned: list[str] = []
        for line in lines:
            text = str(line).strip()
            if not text:
                continue
            normalized = text.lstrip("-• ").strip().lower()
            if normalized in {"(nessuna)", "nessuna", "• (nessuna)", "• nessuna"}:
                continue
            cleaned.append(text)
        return cleaned

    def normalize_bullets(raw: Any) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if item is not None and str(item).strip()]
        if isinstance(raw, str):
            return [line.strip() for line in raw.splitlines() if line.strip()]
        value = str(raw).strip()
        return [value] if value else []

    def clean_bullets(lines: list[str] | None) -> list[str]:
        return _clean_bullets(lines)

    def should_show_section(lines: list[str] | None) -> bool:
        return len(clean_bullets(normalize_bullets(lines))) > 0

    def _is_effectively_empty_section(lines: list[str] | None) -> bool:
        return len(_clean_bullets(lines)) == 0

    def _is_effectively_empty_text(text: str | None) -> bool:
        if not text:
            return True
        stripped = text.strip()
        if not stripped:
            return True
        normalized = stripped.lstrip("-• ").strip().lower()
        return normalized in {"(nessuna)", "nessuna", "• (nessuna)", "• nessuna"}

    def _format_bullets(lines: list[str]) -> str:
        cleaned = clean_bullets(lines)
        if not cleaned:
            return ""
        formatted: list[str] = []
        for line in cleaned:
            text = line.strip()
            if text.startswith(("- ", "* ")):
                text = text[2:].strip()
            if text.startswith("•"):
                text = text.lstrip("•").strip()
            if text.startswith("•"):
                text = text.lstrip("•").strip()
            if text.startswith("• •"):
                text = text.replace("• •", "•", 1).strip()
            formatted.append(f"• {text}")
        return "\n".join(formatted)

    def _normalize_trend(trend_value: Any) -> tuple[str | None, int | None]:
        if isinstance(trend_value, dict):
            direction = trend_value.get("direction")
            delta_raw = trend_value.get("delta")
            try:
                delta = int(delta_raw) if delta_raw is not None else None
            except (TypeError, ValueError):
                delta = None
            return str(direction) if direction else None, delta
        if isinstance(trend_value, str):
            value = trend_value.strip().lower()
            mapping = {
                "stable": "stable",
                "stabile": "stable",
                "improving": "improving",
                "miglioramento": "improving",
                "in miglioramento": "improving",
                "worsening": "worsening",
                "peggioramento": "worsening",
                "in peggioramento": "worsening",
            }
            return mapping.get(value, None), None
        return None, None

    def _render_trend(direction: str | None, delta: int | None) -> str:
        if direction == "improving":
            base = "In miglioramento."
        elif direction == "worsening":
            base = "In peggioramento."
        else:
            base = "Stabile."
        if delta is None:
            return base
        return f"{base} (Δ {delta:+d})."

    def _build_trend_reason(reasons: list[dict[str, Any]], direction: str | None) -> str:
        if not reasons:
            return "Perché: il tono resta abbastanza uniforme e senza scosse."
        key = str(reasons[0].get("key", "")).lower()
        label = str(reasons[0].get("label", "")).lower()
        if "reply_war" in key or "botta" in label:
            return "Perché: si è innescata una botta e risposta che scalda il clima."
        if "burst" in key or "densit" in label:
            return "Perché: tanti messaggi tutti insieme fanno salire la tensione."
        if "top1" in key or "top3" in key or "concentrazione" in label:
            return "Perché: si parla in pochi e ci si punzecchia più facilmente."
        if "challenge" in key or "domande" in label:
            return "Perché: ci sono domande un po’ sfidanti che accendono il tono."
        if "contrast" in key or "frizione" in label:
            return "Perché: si percepisce attrito nelle parole e rischio fraintendimenti."
        if "caps" in key or "maiuscole" in label:
            return "Perché: il tono sembra acceso e serve più calma."
        if "negativity" in key or "negativi" in label:
            return "Perché: il tono è pungente e ci si risponde di pancia."
        if "mentions" in key or "menzion" in label:
            return "Perché: troppe chiamate dirette alzano la tensione."
        if direction == "improving":
            return "Perché: il tono sta diventando più morbido."
        if direction == "worsening":
            return "Perché: il tono si sta irrigidendo."
        return "Perché: il clima resta simile senza scossoni."

    def _format_motivations(reasons: list[dict[str, Any]]) -> list[str]:
        lines: list[str] = []
        for reason in reasons:
            key = str(reason.get("key", "")).lower()
            label = str(reason.get("label", "")).lower()
            if "reply_war" in key or "botta" in label:
                lines.append("Botta e risposta che rimbalza: serve una pausa.")
            elif "burst" in key or "densit" in label:
                lines.append("Tanti messaggi tutti insieme: il clima si scalda in fretta.")
            elif "top1" in key or "top3" in key or "concentrazione" in label:
                lines.append("Si parla in pochi: quando sono sempre gli stessi, si rischia di pungersi.")
            elif "challenge" in key or "domande" in label:
                lines.append("Ci sono domande un po’ sfidanti: meglio chiarire con calma.")
            elif "contrast" in key or "frizione" in label:
                lines.append("Si percepisce attrito nelle parole: rischio fraintendimenti.")
            elif "caps" in key or "maiuscole" in label:
                lines.append("Il tono sembra acceso: meglio abbassare i toni.")
            elif "negativity" in key or "negativi" in label:
                lines.append("Il tono è pungente: serve più gentilezza.")
            elif "mentions" in key or "menzion" in label:
                lines.append("Troppe chiamate dirette: meglio chiarire senza puntare il dito.")
            else:
                lines.append("Si percepisce tensione diffusa: serve calma e ascolto.")
        unique_lines: list[str] = []
        for line in lines:
            if line not in unique_lines:
                unique_lines.append(line)
        return unique_lines[:4]

    def _bullets_to_text(lines: list[str]) -> str:
        return _format_bullets(lines)

    def _fallback_personal_advice(color_label: str) -> list[str]:
        if color_label == "verde":
            return [
                "Coinvolgi i nuovi: fai una domanda leggera.",
                "Mantieni il ritmo: alterna messaggi brevi e chiari.",
                "Rinforza i contributi positivi con un semplice 👍.",
            ]
        if color_label == "giallo":
            return [
                "Usa un tono neutro e fai domande aperte.",
                "Evita ironie: meglio chiarezza e messaggi brevi.",
                "Se serve, sposta un tema caldo in privato.",
            ]
        return [
            "Evita interventi diretti: favorisci de-escalation o pausa.",
            "Se scrivi, resta neutro e invita al rispetto reciproco.",
            "Rimanda i temi caldi a un momento più tranquillo.",
        ]

    def _fallback_mod_advice(color_label: str) -> list[str]:
        if color_label == "verde":
            return [
                "Monitora senza intervenire: lascia spazio alla conversazione.",
                "Premia i toni costruttivi con una reazione rapida.",
                "Se emergono tensioni, suggerisci un cambio di topic leggero.",
            ]
        if color_label == "giallo":
            return [
                "Intervieni presto con un richiamo soft sui toni.",
                "Invita a chiarire in privato i punti più spinosi.",
                "Riduci il rumore: chiedi messaggi sintetici.",
            ]
        return [
            "Valuta un intervento pubblico di de-escalation.",
            "Se necessario, sposta la discussione su un topic neutro.",
            "Monitora utenti/coppie ricorrenti e intervieni in privato.",
        ]

    def _resolve_display_name(member: discord.Member) -> str:
        return (
            getattr(member, "display_name", None)
            or getattr(member, "global_name", None)
            or getattr(member, "name", None)
            or "Utente"
        )

    MIN_MSG_TOTAL_CHANNEL = 8
    MIN_MSG_TOTAL_PAIR = 6
    MIN_MSG_EACH_PAIR = 2

    def _apply_output_caps(output_flags: dict[str, Any], insufficient_data: bool) -> dict[str, Any]:
        if not insufficient_data:
            return dict(output_flags)
        return {
            "show_score": True,
            "show_motivation": False,
            "show_trend": False,
            "show_advice": True,
            "show_mod_metrics": False,
        }

    def _fallback_pair_personal_advice(metrics: dict[str, Any]) -> list[str]:
        advice: list[str] = []
        balance_ratio = float(metrics.get("balance_ratio") or 0)
        mentions_total = int(metrics.get("mentions_a_to_b") or 0) + int(metrics.get("mentions_b_to_a") or 0)
        caps_ratio = float(metrics.get("caps_ratio") or 0)
        negativity_hits = int(metrics.get("negativity_hits") or 0)
        reply_war = bool(metrics.get("reply_war"))

        if balance_ratio and balance_ratio < 0.6:
            advice.append("Bilancia i turni: lascia spazio all’altra persona prima di rispondere.")
        if mentions_total >= 3:
            advice.append("Usa le menzioni solo per chiarire, non per accelerare il confronto.")
        if caps_ratio > 0.3:
            advice.append("Riduci le MAIUSCOLE: aiutano a evitare fraintendimenti sul tono.")
        if negativity_hits > 0:
            advice.append("Mantieni un tono neutro e riformula quando il clima si irrigidisce.")
        if reply_war:
            advice.append("Se la discussione accelera, proponi una pausa breve o sposta il tema.")
        if not advice:
            advice = [
                "Fai domande di chiarimento prima di rispondere di pancia.",
                "Sintetizza i punti chiave per evitare malintesi.",
                "Conferma i punti su cui siete già d’accordo.",
            ]
        return advice[:5]

    def _fallback_pair_affinity(metrics: dict[str, Any]) -> list[str]:
        affinity: list[str] = []
        balance_ratio = float(metrics.get("balance_ratio") or 0)
        avg_len_a = float(metrics.get("avg_msg_len_a") or 0)
        avg_len_b = float(metrics.get("avg_msg_len_b") or 0)
        mentions_total = int(metrics.get("mentions_a_to_b") or 0) + int(metrics.get("mentions_b_to_a") or 0)
        negativity_hits = int(metrics.get("negativity_hits") or 0)
        reply_war = bool(metrics.get("reply_war"))

        if balance_ratio >= 0.8:
            affinity.append("Scambio abbastanza bilanciato: potete coordinare i turni con facilità.")
        if avg_len_a and avg_len_b and abs(avg_len_a - avg_len_b) <= 25:
            affinity.append("Stile di messaggi simile (lunghezze comparabili): facilita la sintonia.")
        if mentions_total > 0:
            affinity.append("Le menzioni reciproche indicano disponibilità a chiarire.")
        if not reply_war and negativity_hits == 0:
            affinity.append("Tono generalmente controllato: terreno comune per conversazioni calme.")
        if not affinity:
            affinity = [
                "C’è spazio per stabilire un ritmo condiviso.",
                "Punti di contatto: chiarezza e sintesi nei messaggi.",
                "Funziona bene quando vi date il tempo di rispondere.",
            ]
        return affinity[:5]

    def _fallback_pair_mod_advice(metrics: dict[str, Any]) -> list[str]:
        advice: list[str] = []
        balance_ratio = float(metrics.get("balance_ratio") or 0)
        mentions_total = int(metrics.get("mentions_a_to_b") or 0) + int(metrics.get("mentions_b_to_a") or 0)
        caps_ratio = float(metrics.get("caps_ratio") or 0)
        negativity_hits = int(metrics.get("negativity_hits") or 0)
        reply_war = bool(metrics.get("reply_war"))

        if balance_ratio and balance_ratio < 0.6:
            advice.append("Invita al turn-taking: chiedi risposte più distanziate tra loro.")
        if mentions_total >= 3:
            advice.append("Riduci i callout: chiedi di limitare le menzioni dirette.")
        if caps_ratio > 0.3 or negativity_hits > 0:
            advice.append("Richiama i toni: suggerisci riformulazioni più neutrali.")
        if reply_war:
            advice.append("Applica un cooldown leggero o separa la discussione in thread.")
        advice.append("Se serve, proponi chiarimenti guidati in privato con punti specifici.")
        advice.append("Monitora il canale per evitare escalation improvvise.")
        return advice[:6]

    def _fallback_pair_contact_points(metrics: dict[str, Any]) -> list[str]:
        contacts: list[str] = []
        balance_ratio = float(metrics.get("balance_ratio") or 0)
        avg_len_a = float(metrics.get("avg_msg_len_a") or 0)
        avg_len_b = float(metrics.get("avg_msg_len_b") or 0)
        mentions_total = int(metrics.get("mentions_a_to_b") or 0) + int(metrics.get("mentions_b_to_a") or 0)
        reply_war = bool(metrics.get("reply_war"))

        if balance_ratio >= 0.75:
            contacts.append("Scambio equilibrato: utile per richieste di chiarimento reciproco.")
        if avg_len_a and avg_len_b and abs(avg_len_a - avg_len_b) <= 25:
            contacts.append("Stile comunicativo simile: incoraggia sintesi e turni alternati.")
        if mentions_total > 0:
            contacts.append("Disponibilità a citarsi: sfruttabile per accordi rapidi.")
        if not reply_war:
            contacts.append("Meno escalation: terreno adatto a mediazione leggera.")
        if not contacts:
            contacts = [
                "Preferenza per messaggi chiari e diretti.",
                "Disponibilità a rispondere se sollecitati con calma.",
                "Meglio con istruzioni brevi e neutrali.",
            ]
        return contacts[:5]

    def _build_barcello_public_embed(
        *,
        result: Any,
        channel_name: str,
        window_minutes: int,
        title_override: str | None = None,
    ) -> discord.Embed:
        color_label = (result.color or "nero").lower()
        color_map = {
            "verde": (0x2ECC71, "🟢", "verde"),
            "giallo": (0xF1C40F, "🟡", "giallo"),
            "rosso": (0xE74C3C, "🔴", "rosso"),
            "nero": (0x2C2F33, "⚫", "nero"),
        }
        embed_color, emoji, label = color_map.get(color_label, (0x2C2F33, "⚫", color_label))
        title_channel = channel_name or "canale"
        title = title_override or f"🫛 **STATO BARCELLO “{title_channel}”**"
        description_lines = [
            f"🕒 **Ultimi {window_minutes} minuti**",
            "",
            f"{emoji} **ALLERTA {label.upper()}**",
            f"*{_alert_message(result.score, label)}*",
        ]
        embed = discord.Embed(
            title=title,
            description="\n".join(description_lines),
            color=embed_color,
        )
        bar = _render_health_bar(result.score, emoji)
        _add_section(
            embed,
            name="🫀 **PUNTI SALUTE**",
            value=_with_spacing(f"{bar}  **({result.score}/100)**\n*{_health_description(result.score)}*"),
        )
        attach_footer_meta(embed, service_name="barcello", used_local_processing=True)
        return embed

    def _build_barcello_no_data_embed(
        *,
        title: str,
        window_minutes: int,
    ) -> discord.Embed:
        description_lines = [
            f"🕒 **Ultimi {window_minutes} minuti**",
            "",
            "Nessun messaggio nella finestra temporale selezionata.",
            "Prova ad aumentare i minuti della finestra.",
        ]
        embed = discord.Embed(
            title=title,
            description="\n".join(description_lines),
            color=0x95A5A6,
        )
        attach_footer_meta(embed, service_name="barcello", used_local_processing=True)
        return embed

    def _build_barcello_details_embed(
        *,
        result: Any,
        window_minutes: int,
        output_flags: dict[str, Any],
        profile: str,
        tier_display_name: str,
        embed_color: int,
        reasons_text: str,
        trend_text: str,
        trend_reason: str | None = None,
        personal_advice: list[str],
        mod_advice: list[str],
        affinity_bullets: list[str] | None = None,
        contact_points_bullets: list[str] | None = None,
        pair_mode: bool = False,
        pair_mode_profile: str | None = None,
        warning_text: str | None = None,
        ai_debug_line: str | None = None,
        ai_note: str = "",
    ) -> discord.Embed:
        embed = discord.Embed(title=f"🧾 **DETTAGLI BARCELLO — {tier_display_name}**", color=embed_color)
        if warning_text and not _is_effectively_empty_text(warning_text):
            _add_section(embed, name="⚠️ **CAMPIONE PICCOLO**", value=_with_spacing(warning_text))
        if output_flags.get("show_motivation") and reasons_text:
            if not _is_effectively_empty_text(reasons_text):
                _add_section(embed, name="🔥 **MOTIVAZIONI**", value=_with_spacing(reasons_text))
        if output_flags.get("show_trend"):
            trend_value = trend_text if trend_text else render_trend_value(result.trend)
            if trend_reason and not _is_effectively_empty_text(trend_reason):
                trend_value = f"{trend_value}\n{trend_reason}"
            _add_section(embed, name="📈 **TREND**", value=_with_spacing(trend_value))
        if output_flags.get("show_advice"):
            if pair_mode and pair_mode_profile == "role3":
                advice_lines = clean_bullets(personal_advice)[:5]
                if should_show_section(advice_lines):
                    _add_section(embed, name="🧠 **COME ANDARE D’ACCORDO**", value=_format_bullets(advice_lines))
                affinity_lines = clean_bullets(affinity_bullets)[:5]
                if should_show_section(affinity_lines):
                    _add_section(embed, name="💞 **AFFINITÀ**", value=_format_bullets(affinity_lines))
            elif pair_mode and pair_mode_profile == "mod":
                mod_lines = clean_bullets(mod_advice)[:6]
                if should_show_section(mod_lines):
                    _add_section(embed, name="🛡️ **CONSIGLI PER LA MODERAZIONE**", value=_format_bullets(mod_lines))
                contact_lines = clean_bullets(contact_points_bullets)[:5]
                if should_show_section(contact_lines):
                    _add_section(embed, name="🤝 **PUNTI DI CONTATTO**", value=_format_bullets(contact_lines))
            else:
                advice_lines = clean_bullets(personal_advice)[:5]
                if should_show_section(advice_lines):
                    _add_section(embed, name="🧠 **CONSIGLI PERSONALIZZATI**", value=_format_bullets(advice_lines))
                if profile == "mod":
                    mod_lines = clean_bullets(mod_advice)[:5]
                    if should_show_section(mod_lines):
                        _add_section(embed, name="🛡️ **CONSIGLI PER LA MODERAZIONE**", value=_format_bullets(mod_lines))
        if output_flags.get("show_mod_metrics") and profile == "mod":
            _add_section(embed, name="🧮 **METRICHE AGGREGATE**", value=_with_spacing(_format_metrics(result.metrics)))
        if ai_note:
            _add_section(embed, name="ℹ️ **NOTA**", value=_with_spacing(ai_note))
        if ai_debug_line and (profile == "mod" or os.getenv("DEBUG", "").lower() in {"1", "true", "yes", "y"}):
            _add_section(embed, name="🔎 **AI**", value=_with_spacing(ai_debug_line))
        notes_by_profile = {
            "base": "*Per maggiori info su trend e consigli passa a un piano superiore! 😉*",
            "role1": "*Per maggiori info su trend e consigli passa a un piano superiore! 😉*",
            "role2": "*Per i consigli personalizzati passa al livello successivo! 🧠*",
            "role3": "*Hai sbloccato i consigli personalizzati ✨*",
            "mod": "*Report completo per moderazione.*",
        }
        if profile != "role3":
            note_value = notes_by_profile.get(profile, "")
            if note_value:
                _add_section(embed, name="📌 **NOTE**", value=_with_spacing(note_value))
        attach_footer_meta(embed, service_name="barcello", used_local_processing=True)
        return embed

    class _BarcelloFeedbackView(discord.ui.View):
        def __init__(
            self,
            *,
            database: Any,
            owner_id: int,
            channel_id: str,
            snapshot_id: str,
            score_pred: int,
            profile: str | None,
        ) -> None:
            super().__init__(timeout=600)
            self._database = database
            self._owner_id = owner_id
            self._channel_id = channel_id
            self._snapshot_id = snapshot_id
            self._score_pred = score_pred
            self._profile = profile

        async def _ensure_owner(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self._owner_id:
                await send_standard_component_notice(interaction, area="barcello feedback", message="Feedback riservato ai mod.", kind="error")
                return False
            return True

        async def _store_feedback(
            self,
            *,
            verdict: str,
            reason: str | None,
            delta_target: int | None,
        ) -> None:
            try:
                await self._database.insert_barcello_feedback(
                    created_at=datetime.now(timezone.utc).isoformat(),
                    channel_id=self._channel_id,
                    snapshot_id=self._snapshot_id,
                    rater_user_id=str(self._owner_id),
                    verdict=verdict,
                    reason=reason,
                    delta_target=delta_target,
                    score_pred=self._score_pred,
                    profile=self._profile,
                )
            except Exception:
                logger.exception("Failed to store barcello feedback")

        async def _finalize(self, interaction: discord.Interaction) -> None:
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(
                content="Feedback registrato ✅",
                embeds=interaction.message.embeds,
                view=self,
            )

        @discord.ui.button(label="✅ Accurato", style=discord.ButtonStyle.success)
        async def accurate(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
            if not await self._ensure_owner(interaction):
                return
            await self._store_feedback(verdict="accurate", reason=None, delta_target=None)
            await self._finalize(interaction)

        @discord.ui.button(label="❌ Inaccurato", style=discord.ButtonStyle.danger)
        async def inaccurate(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
            if not await self._ensure_owner(interaction):
                return
            view = _BarcelloFeedbackSelectView(
                database=self._database,
                owner_id=self._owner_id,
                channel_id=self._channel_id,
                snapshot_id=self._snapshot_id,
                score_pred=self._score_pred,
                profile=self._profile,
            )
            await interaction.response.edit_message(
                content="Seleziona motivo e correzione punteggio.",
                embeds=interaction.message.embeds,
                view=view,
            )

    class _BarcelloFeedbackSelectView(discord.ui.View):
        def __init__(
            self,
            *,
            database: Any,
            owner_id: int,
            channel_id: str,
            snapshot_id: str,
            score_pred: int,
            profile: str | None,
        ) -> None:
            super().__init__(timeout=600)
            self._database = database
            self._owner_id = owner_id
            self._channel_id = channel_id
            self._snapshot_id = snapshot_id
            self._score_pred = score_pred
            self._profile = profile
            self._reason: str | None = None
            self._delta_target: int | None = None

            self.reason_select = discord.ui.Select(
                placeholder="Motivo",
                min_values=1,
                max_values=1,
                options=[
                    discord.SelectOption(label="Sarcasmo/ironia scambiato per tensione", value="sarcasmo"),
                    discord.SelectOption(label="Tensione fredda non rilevata", value="tensione_fredda"),
                    discord.SelectOption(label="Duello tra pochi utenti", value="duello_pochi"),
                    discord.SelectOption(label="Picco momentaneo", value="picco_momentaneo"),
                    discord.SelectOption(label="Altro", value="altro"),
                ],
            )
            self.reason_select.callback = self._on_reason_select
            self.add_item(self.reason_select)

            self.delta_select = discord.ui.Select(
                placeholder="Correzione punteggio",
                min_values=1,
                max_values=1,
                options=[
                    discord.SelectOption(label="Troppo severo → +10", value="10"),
                    discord.SelectOption(label="Troppo severo → +20", value="20"),
                    discord.SelectOption(label="Troppo severo → +30", value="30"),
                    discord.SelectOption(label="Troppo permissivo → -10", value="-10"),
                    discord.SelectOption(label="Troppo permissivo → -20", value="-20"),
                    discord.SelectOption(label="Troppo permissivo → -30", value="-30"),
                ],
            )
            self.delta_select.callback = self._on_delta_select
            self.add_item(self.delta_select)

        async def _ensure_owner(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self._owner_id:
                await send_standard_component_notice(interaction, area="barcello feedback", message="Feedback riservato ai mod.", kind="error")
                return False
            return True

        async def _on_reason_select(self, interaction: discord.Interaction) -> None:
            if not await self._ensure_owner(interaction):
                return
            self._reason = self.reason_select.values[0]
            await interaction.response.defer()

        async def _on_delta_select(self, interaction: discord.Interaction) -> None:
            if not await self._ensure_owner(interaction):
                return
            value = self.delta_select.values[0]
            try:
                self._delta_target = int(value)
            except ValueError:
                self._delta_target = None
            await interaction.response.defer()

        @discord.ui.button(label="Invia feedback", style=discord.ButtonStyle.primary)
        async def submit(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
            if not await self._ensure_owner(interaction):
                return
            if not self._reason or self._delta_target is None:
                await send_standard_component_notice(interaction, area="barcello feedback", message="Seleziona motivo e correzione.", kind="warning")
                return
            try:
                await self._database.insert_barcello_feedback(
                    created_at=datetime.now(timezone.utc).isoformat(),
                    channel_id=self._channel_id,
                    snapshot_id=self._snapshot_id,
                    rater_user_id=str(self._owner_id),
                    verdict="inaccurate",
                    reason=self._reason,
                    delta_target=self._delta_target,
                    score_pred=self._score_pred,
                    profile=self._profile,
                )
            except Exception:
                logger.exception("Failed to store barcello feedback")
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(
                content="Feedback registrato ✅",
                embeds=interaction.message.embeds,
                view=self,
            )

    def _extract_ai_text(response: Any) -> str:
        output_text = getattr(response, "output_text", "") or ""
        if output_text:
            return output_text
        chunks: list[str] = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                text = getattr(content, "text", None)
                if not text and getattr(content, "type", None) in {"output_text", "text"}:
                    text = getattr(content, "text", "")
                if text:
                    chunks.append(text)
        return "\n".join(chunks).strip()

    def _parse_json_safe(text: str) -> dict[str, Any] | None:
        if not text:
            return None
        raw = text.strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass
        if "```" in raw:
            start = raw.find("```")
            if start != -1:
                fence_lang_end = raw.find("\n", start + 3)
                if fence_lang_end != -1:
                    end = raw.find("```", fence_lang_end + 1)
                    if end != -1:
                        fenced = raw[fence_lang_end:end].strip()
                        try:
                            parsed = json.loads(fenced)
                            return parsed if isinstance(parsed, dict) else None
                        except json.JSONDecodeError:
                            return None
        start_obj = raw.find("{")
        end_obj = raw.rfind("}")
        if start_obj != -1 and end_obj != -1 and end_obj > start_obj:
            candidate = raw[start_obj : end_obj + 1]
            try:
                parsed = json.loads(candidate)
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
        return None

    async def _call_openai_json(
        client: Any,
        model: str,
        input_payload: list[dict[str, str]],
    ) -> tuple[dict[str, Any] | None, str]:
        _ = client
        _ = model
        system_prompt = input_payload[0].get("content", "") if input_payload else ""
        user_payload = input_payload[-1].get("content", "") if input_payload else ""
        ai_text = await ctx.ai.ask_for_task("summary", user_payload, system_prompt) if ctx.ai is not None else ""
        ai_text = ai_text or ""
        payload = _parse_json_safe(ai_text)
        return payload, ai_text

    @barcello_group.command(name="run", description="Run the Barcello analysis.")
    @app_commands.describe(
        user1="Optional first user.",
        user2="Optional second user.",
        window_minutes="Analysis window in minutes.",
    )
    async def barcello_command(
        interaction: discord.Interaction,
        user1: discord.Member | None = None,
        user2: discord.Member | None = None,
        window_minutes: int | None = None,
    ) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True, thinking=True)
                logger.info("barcello: deferred")
            except Exception:
                logger.exception("barcello: failed to defer")
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Questo comando funziona solo nei canali della guild.")
            return

        try:
            entitlements_service: EntitlementsService = ctx.entitlements
            command_config = await entitlements_service.get_command_profile_config(interaction.user, "barcello")
            profile, winner_role_id = await entitlements_service.resolve_profile_with_role_id(interaction.user)

            async def try_send_dm(
                content: str | None = None,
                *,
                embed: discord.Embed | None = None,
                embeds: list[discord.Embed] | None = None,
                view: discord.ui.View | None = None,
            ) -> bool:
                try:
                    if embeds is not None:
                        await interaction.user.send(embeds=embeds, view=view)
                    elif embed is not None:
                        await interaction.user.send(embed=embed, view=view)
                    else:
                        await interaction.user.send(content or "")
                    return True
                except discord.Forbidden:
                    return False

            if not command_config["allowed"]:
                dm_text = command_config["messages"].get("dm_text", "Serve almeno PLUS per usare /barcello.")
                if await try_send_dm(dm_text):
                    await send_ephemeral(interaction, "Ti ho inviato un DM")
                else:
                    await send_ephemeral(interaction, "Apri i DM per ricevere la risposta")
                return

            if not await check_permission(interaction, "bm.barcello.run", ctx, legacy_aliases=["barcello"]):
                return

            if window_minutes is None:
                raw_default = await get_setting(ctx, "barcello.default_window_minutes", "30")
                trigger_config = load_json_file(BARCELLO_TRIGGER_JSON)
                window_minutes = resolve_default_window_minutes(interaction.channel_id, raw_default, trigger_config)
                default_window_minutes = int(raw_default) if str(raw_default).isdigit() else 30
                if default_window_minutes <= 0:
                    default_window_minutes = 30
                if window_minutes != default_window_minutes:
                    logger.info("barcello window override applied channel_id=%s window=%s", interaction.channel_id, window_minutes)
            if window_minutes <= 0:
                window_minutes = 30

            if user2 is not None and user1 is None:
                await send_ephemeral(interaction, "Specifica il primo utente.")
                return
            if user1 is not None and user2 is not None and user1.id == user2.id:
                await send_ephemeral(interaction, "Seleziona due utenti diversi.")
                return
            if ctx.config.ignore_bots:
                if (user1 and user1.bot) or (user2 and user2.bot):
                    await send_ephemeral(interaction, "Non posso usare bot per il barcello.")
                    return

            pair_mode = user1 is not None
            pair_mode_profile: str | None = None
            pair_user_a: discord.Member | None = None
            pair_user_b: discord.Member | None = None

            if pair_mode:
                if user2 is not None:
                    if profile != "mod":
                        await send_ephemeral(interaction, "Solo i mod possono usare due utenti.")
                        return
                    pair_mode_profile = "mod"
                    pair_user_a = user1
                    pair_user_b = user2
                else:
                    if profile not in {"role3", "mod"}:
                        await send_ephemeral(interaction, "Solo ruolo 3 o mod possono usare questo comando.")
                        return
                    pair_mode_profile = "role3"
                    pair_user_a = interaction.user if isinstance(interaction.user, discord.Member) else None
                    pair_user_b = user1
                if pair_user_a is None or pair_user_b is None:
                    await send_ephemeral(interaction, "Utenti non validi.")
                    return

            if pair_mode:
                result = await ctx.barcello_service.compute_pair(
                    str(interaction.guild_id),
                    str(interaction.channel_id),
                    str(pair_user_a.id),
                    str(pair_user_b.id),
                    window_minutes,
                )
            else:
                result = await ctx.barcello_service.compute_channel(
                    str(interaction.guild_id),
                    str(interaction.channel_id),
                    window_minutes,
                )

            def log_ai_event(tag: str, payload: dict[str, Any]) -> None:
                logger.info("%s barcello %s", tag, json.dumps(payload, ensure_ascii=False))

            mode_label = "pair" if pair_mode else "channel"
            msg_count_total = int(result.metrics.get("message_count") or 0)
            msg_count_a = int(result.metrics.get("msg_count_user_a") or 0)
            msg_count_b = int(result.metrics.get("msg_count_user_b") or 0)
            cache_hit = bool(result.metrics.get("cache_hit")) if isinstance(result.metrics, dict) else False

            if msg_count_total == 0:
                title_override = None
                if pair_mode and pair_mode_profile == "role3" and pair_user_b is not None:
                    other_name = _resolve_display_name(pair_user_b)
                    title_override = f"🫛 **STATO BARCELLO CON {other_name}**"
                elif pair_mode and pair_mode_profile == "mod" and pair_user_a is not None and pair_user_b is not None:
                    name_a = _resolve_display_name(pair_user_a)
                    name_b = _resolve_display_name(pair_user_b)
                    title_override = f"🫛 **STATO BARCELLO TRA {name_a} E {name_b}**"
                title = title_override or f"🫛 **STATO BARCELLO “{getattr(interaction.channel, 'name', 'canale')}”**"
                log_ai_event(
                    "AI_FALLBACK",
                    {
                        "guild_id": interaction.guild_id,
                        "channel_id": interaction.channel_id,
                        "profile": profile,
                        "mode": mode_label,
                        "window_minutes": window_minutes,
                        "msg_count": msg_count_total,
                        "ai_allowed": False,
                        "reason": "no_data",
                        "ai_key_present": bool(ctx.config.openai_api_key),
                        "cache_hit": cache_hit,
                        "model": None,
                        "fallback_reason": "no_data",
                    },
                )
                no_data_embed = _build_barcello_no_data_embed(title=title, window_minutes=window_minutes)
                if await try_send_dm(embed=no_data_embed):
                    await _send_barcello_dm_notice(interaction, sent=True)
                else:
                    await _send_barcello_dm_notice(interaction, sent=False)
                return

            insufficient_data = (
                msg_count_total > 0
                and (
                    (mode_label == "channel" and msg_count_total < MIN_MSG_TOTAL_CHANNEL)
                    or (
                        mode_label == "pair"
                        and (
                            msg_count_total < MIN_MSG_TOTAL_PAIR
                            or msg_count_a < MIN_MSG_EACH_PAIR
                            or msg_count_b < MIN_MSG_EACH_PAIR
                        )
                    )
                )
            )
            warning_text = ""
            if insufficient_data:
                warning_text = (
                    f"⚠️ Campione piccolo: {msg_count_total} messaggi negli ultimi "
                    f"{window_minutes} min. Affidabilità: bassa."
                )

            reasons_text = _bullets_to_text(_format_motivations(result.reasons))
            trend_direction, trend_delta = normalize_trend(result.trend)
            trend_text = render_trend(trend_direction, trend_delta)
            trend_reason = _build_trend_reason(result.reasons, trend_direction) if result.trend else ""
            advice_candidates = [item.strip() for item in (result.advice or []) if str(item).strip()]
            color_label = (result.color or "nero").lower()
            affinity_bullets: list[str] = []
            contact_points_bullets: list[str] = []
            if insufficient_data:
                personal_advice = [
                    "Aspetta risposte complete prima di replicare.",
                    "Mantieni un tono neutro e messaggi chiari.",
                ]
                mod_advice = []
                affinity_bullets = []
                contact_points_bullets = []
                reasons_text = ""
                trend_text = ""
                trend_reason = ""
            elif pair_mode and pair_mode_profile == "role3":
                fallback_personal = _fallback_pair_personal_advice(result.metrics)
                affinity_bullets = _fallback_pair_affinity(result.metrics)
                personal_advice = advice_candidates or fallback_personal
                if len(personal_advice) < 3:
                    personal_advice = (personal_advice + fallback_personal)[:3]
                mod_advice = _fallback_mod_advice(color_label)
            elif pair_mode and pair_mode_profile == "mod":
                personal_advice = advice_candidates or []
                mod_advice = _fallback_pair_mod_advice(result.metrics)
                contact_points_bullets = _fallback_pair_contact_points(result.metrics)
            else:
                fallback_personal = _fallback_personal_advice(color_label)
                personal_advice = advice_candidates or fallback_personal
                if len(personal_advice) < 3:
                    personal_advice = (personal_advice + fallback_personal)[:3]
                mod_advice = _fallback_mod_advice(color_label)
            ai_note = ""
            ai_debug_line = None

            ai_key_present = bool(ctx.config.openai_api_key)
            ai_allowed = False
            ai_reason = ""
            if insufficient_data:
                ai_reason = "insufficient_data"
            elif "analysis.ai_preferred" not in (command_config.get("capabilities") or []):
                ai_reason = "disabled_by_entitlements"
            elif ctx.ai is None:
                ai_reason = "missing_key"
            else:
                ai_enabled = await entitlements_service.is_feature_allowed(interaction.user, "ai")
                ai_service_enabled = ctx.ai.is_enabled() if ctx.ai else False
                ai_reason = "" if ai_enabled and ai_service_enabled else "disabled_by_entitlements"
            if not ai_reason:
                model_name = ctx.ai.get_model("summary") if ctx.ai else None
                client_ready = ctx.ai.client() if ctx.ai else None
                if not ai_key_present or not model_name or not client_ready:
                    ai_reason = "missing_key"
            if not ai_reason and ai_key_present:
                ai_allowed = True
            if not ai_allowed:
                fallback_reason = ai_reason or "missing_key"
                log_ai_event(
                    "AI_FALLBACK",
                    {
                        "guild_id": interaction.guild_id,
                        "channel_id": interaction.channel_id,
                        "profile": profile,
                        "mode": mode_label,
                        "window_minutes": window_minutes,
                        "msg_count": msg_count_total,
                        "ai_allowed": False,
                        "reason": fallback_reason,
                        "ai_key_present": ai_key_present,
                        "cache_hit": cache_hit,
                        "model": None,
                        "fallback_reason": fallback_reason,
                    },
                )
                ai_debug_line = f"🔎 AI: OFF (fallback={fallback_reason})"

            if ai_allowed:
                if ctx.ai is not None:
                    ai_enabled = await entitlements_service.is_feature_allowed(interaction.user, "ai")
                    ai_service_enabled = ctx.ai.is_enabled() if ctx.ai else False
                    if ai_enabled and ai_service_enabled and ctx.ai:
                        client = ctx.ai.client()
                        model = ctx.ai.get_model("summary")
                        if client and model:
                            try:
                                log_ai_event(
                                    "AI_REQUEST",
                                    {
                                        "guild_id": interaction.guild_id,
                                        "channel_id": interaction.channel_id,
                                        "profile": profile,
                                        "mode": mode_label,
                                        "window_minutes": window_minutes,
                                        "msg_count": msg_count_total,
                                        "ai_allowed": True,
                                        "reason": None,
                                        "ai_key_present": ai_key_present,
                                        "cache_hit": cache_hit,
                                        "model": model,
                                    },
                                )
                                start_ts = datetime.now(timezone.utc)
                                metrics = result.metrics or {}
                                if pair_mode and pair_mode_profile == "role3":
                                    system_prompt = (
                                        "Scrivi in italiano, tono cricetoso, semplice e pratico. "
                                        "Non includere nomi utenti, dati sensibili o accuse. "
                                        "Non usare numeri, percentuali o metriche (es. ratio, top3). "
                                        "Non aggiungere dettagli non presenti. "
                                        "Motivation e bullets devono parlare di segnali percepibili "
                                        "(botta e risposta, tono pungente, poca ascolto, clima che si scalda). "
                                        "Restituisci SOLO JSON con chiavi: motivation, trend_reason, "
                                        "pair_advice_bullets, affinity_bullets. "
                                        "Le liste devono avere 3-5 elementi, massimo 120 caratteri ciascuno. "
                                        "Return ONLY valid JSON. No markdown, no prose."
                                    )
                                    user_payload = json.dumps(
                                        {
                                            "context": "pair_mode_role3",
                                            "window_minutes": window_minutes,
                                            "score": result.score,
                                            "color": result.color,
                                            "trend": result.trend,
                                            "motivations": result.reasons,
                                            "pair_metrics": {
                                                "msg_count_user_a": metrics.get("msg_count_user_a"),
                                                "msg_count_user_b": metrics.get("msg_count_user_b"),
                                                "balance_ratio": metrics.get("balance_ratio"),
                                                "mentions_a_to_b": metrics.get("mentions_a_to_b"),
                                                "mentions_b_to_a": metrics.get("mentions_b_to_a"),
                                                "caps_ratio": metrics.get("caps_ratio"),
                                                "negativity_hits": metrics.get("negativity_hits"),
                                                "reply_war": metrics.get("reply_war"),
                                                "avg_msg_len_a": metrics.get("avg_msg_len_a"),
                                                "avg_msg_len_b": metrics.get("avg_msg_len_b"),
                                            },
                                            "signals": {
                                                "escalation": metrics.get("reply_war"),
                                                "imbalance": metrics.get("balance_ratio"),
                                                "tone_caps": metrics.get("caps_ratio"),
                                                "tone_negativity": metrics.get("negativity_hits"),
                                            },
                                            "behavior_profiles": None,
                                        },
                                        ensure_ascii=False,
                                    )
                                elif pair_mode and pair_mode_profile == "mod":
                                    system_prompt = (
                                        "Scrivi in italiano, tono cricetoso, pratico e neutro da playbook mod. "
                                        "Non includere nomi utenti, dati sensibili o accuse. "
                                        "Non usare numeri, percentuali o metriche (es. ratio, top3). "
                                        "Non aggiungere dettagli non presenti. "
                                        "Motivation e bullets devono parlare di segnali percepibili "
                                        "(botta e risposta, tono pungente, poca ascolto, clima che si scalda). "
                                        "Restituisci SOLO JSON con chiavi: motivation, trend_reason, "
                                        "mod_advice_bullets, contact_points_bullets. "
                                        "mod_advice_bullets deve avere 4-6 elementi; "
                                        "contact_points_bullets 3-5 elementi; massimo 120 caratteri ciascuno. "
                                        "Return ONLY valid JSON. No markdown, no prose."
                                    )
                                    user_payload = json.dumps(
                                        {
                                            "context": "pair_mode_mod",
                                            "window_minutes": window_minutes,
                                            "score": result.score,
                                            "color": result.color,
                                            "trend": result.trend,
                                            "motivations": result.reasons,
                                            "pair_metrics": {
                                                "msg_count_user_a": metrics.get("msg_count_user_a"),
                                                "msg_count_user_b": metrics.get("msg_count_user_b"),
                                                "balance_ratio": metrics.get("balance_ratio"),
                                                "mentions_a_to_b": metrics.get("mentions_a_to_b"),
                                                "mentions_b_to_a": metrics.get("mentions_b_to_a"),
                                                "caps_ratio": metrics.get("caps_ratio"),
                                                "negativity_hits": metrics.get("negativity_hits"),
                                                "reply_war": metrics.get("reply_war"),
                                                "avg_msg_len_a": metrics.get("avg_msg_len_a"),
                                                "avg_msg_len_b": metrics.get("avg_msg_len_b"),
                                            },
                                            "signals": {
                                                "escalation": metrics.get("reply_war"),
                                                "imbalance": metrics.get("balance_ratio"),
                                                "tone_caps": metrics.get("caps_ratio"),
                                                "tone_negativity": metrics.get("negativity_hits"),
                                            },
                                            "behavior_profiles": None,
                                        },
                                        ensure_ascii=False,
                                    )
                                else:
                                    system_prompt = (
                                        "Scrivi in italiano, tono cricetoso, semplice e pratico. "
                                        "Non includere nomi utenti, dati sensibili o accuse. "
                                        "Non usare numeri, percentuali o metriche (es. ratio, top3). "
                                        "Non aggiungere dettagli non presenti. "
                                        "Motivation e bullets devono parlare di segnali percepibili "
                                        "(botta e risposta, tono pungente, poca ascolto, clima che si scalda). "
                                        "Restituisci SOLO JSON con chiavi: motivation, trend_reason, "
                                        "personal_advice_bullets, mod_advice_bullets. "
                                        "Le liste devono avere 3-5 elementi, massimo 120 caratteri ciascuno. "
                                        "Return ONLY valid JSON. No markdown, no prose."
                                    )
                                    user_payload = json.dumps(
                                        {
                                            "channel": getattr(interaction.channel, "name", ""),
                                            "window_minutes": window_minutes,
                                            "score": result.score,
                                            "color": result.color,
                                            "trend": result.trend,
                                            "motivations": result.reasons,
                                            "metrics": {
                                                "msg_per_min": metrics.get("msg_per_min"),
                                                "caps_ratio": metrics.get("caps_ratio"),
                                                "mention_per_min": metrics.get("mention_per_min"),
                                                "negativity_hits": metrics.get("negativity_hits"),
                                                "reply_war": metrics.get("reply_war"),
                                            },
                                            "wants_mod_advice": profile == "mod",
                                        },
                                        ensure_ascii=False,
                                    )
                                ai_payload, ai_text = await _call_openai_json(
                                    client,
                                    model,
                                    [
                                        {"role": "system", "content": system_prompt},
                                        {"role": "user", "content": user_payload},
                                    ],
                                )
                                latency_ms = int((datetime.now(timezone.utc) - start_ts).total_seconds() * 1000)
                                log_ai_event(
                                    "AI_RESPONSE",
                                    {
                                        "guild_id": interaction.guild_id,
                                        "channel_id": interaction.channel_id,
                                        "profile": profile,
                                        "mode": mode_label,
                                        "window_minutes": window_minutes,
                                        "msg_count": msg_count_total,
                                        "ai_allowed": True,
                                        "reason": None,
                                        "ai_key_present": ai_key_present,
                                        "cache_hit": cache_hit,
                                        "model": model,
                                        "latency_ms": latency_ms,
                                    },
                                )
                                ai_debug_line = f"🔎 AI: ON (model={model})"
                                if not ai_text:
                                    logger.warning("OpenAI output empty")
                                if ai_payload is None:
                                    snippet = ai_text[:200]
                                    logger.warning("OpenAI output not JSON: %s", snippet)
                                    ai_note = "AI non disponibile: report base."
                                    log_ai_event(
                                        "AI_FALLBACK",
                                        {
                                            "guild_id": interaction.guild_id,
                                            "channel_id": interaction.channel_id,
                                            "profile": profile,
                                            "mode": mode_label,
                                            "window_minutes": window_minutes,
                                            "msg_count": msg_count_total,
                                            "ai_allowed": False,
                                            "reason": "invalid_json",
                                            "ai_key_present": ai_key_present,
                                            "cache_hit": cache_hit,
                                            "model": model,
                                            "fallback_reason": "invalid_json",
                                        },
                                    )
                                    ai_debug_line = "🔎 AI: OFF (fallback=invalid_json)"
                                else:
                                    logger.info("AI JSON parsed ok")
                                    motivation_lines = normalize_bullets(ai_payload.get("motivation"))
                                    if motivation_lines:
                                        reasons_text = _bullets_to_text(motivation_lines)
                                    ai_trend_reason = normalize_bullets(ai_payload.get("trend_reason"))
                                    if ai_trend_reason:
                                        trend_reason = "Perché: " + " ".join(clean_bullets(ai_trend_reason))
                                    if pair_mode and pair_mode_profile == "role3":
                                        ai_advice = ai_payload.get("pair_advice_bullets")
                                        ai_affinity = ai_payload.get("affinity_bullets")
                                        personal_advice = clean_bullets(normalize_bullets(ai_advice))
                                        affinity_bullets = clean_bullets(normalize_bullets(ai_affinity))
                                        fallback_personal = _fallback_pair_personal_advice(result.metrics)
                                        if len(personal_advice) < 3:
                                            personal_advice = (personal_advice + fallback_personal)[:3]
                                        if len(affinity_bullets) < 3:
                                            affinity_bullets = (_fallback_pair_affinity(result.metrics) + affinity_bullets)[:3]
                                    elif pair_mode and pair_mode_profile == "mod":
                                        ai_mod = ai_payload.get("mod_advice_bullets")
                                        ai_contacts = ai_payload.get("contact_points_bullets")
                                        mod_advice = clean_bullets(normalize_bullets(ai_mod))
                                        contact_points_bullets = clean_bullets(normalize_bullets(ai_contacts))
                                        if len(mod_advice) < 4:
                                            mod_advice = (_fallback_pair_mod_advice(result.metrics) + mod_advice)[:4]
                                        if len(contact_points_bullets) < 3:
                                            contact_points_bullets = (
                                                _fallback_pair_contact_points(result.metrics) + contact_points_bullets
                                            )[:3]
                                    else:
                                        ai_personal = ai_payload.get("personal_advice_bullets")
                                        ai_mod = ai_payload.get("mod_advice_bullets")
                                        personal_advice = clean_bullets(normalize_bullets(ai_personal))
                                        mod_advice = clean_bullets(normalize_bullets(ai_mod))
                                        fallback_personal = _fallback_personal_advice(color_label)
                                        if len(personal_advice) < 3:
                                            personal_advice = (personal_advice + fallback_personal)[:3]
                                        if len(mod_advice) < 3:
                                            mod_advice = (mod_advice + _fallback_mod_advice(color_label))[:3]
                            except Exception as exc:  # noqa: BLE001
                                logger.exception("AI barcello enrichment failed")
                                ai_note = "AI non disponibile: report base."
                                log_ai_event(
                                    "AI_FALLBACK",
                                    {
                                        "guild_id": interaction.guild_id,
                                        "channel_id": interaction.channel_id,
                                        "profile": profile,
                                        "mode": mode_label,
                                        "window_minutes": window_minutes,
                                        "msg_count": msg_count_total,
                                        "ai_allowed": True,
                                        "reason": "exception",
                                        "ai_key_present": ai_key_present,
                                        "cache_hit": cache_hit,
                                        "model": model,
                                        "fallback_reason": "exception",
                                        "exception": f"{exc.__class__.__name__}: {exc}",
                                    },
                                )
                                ai_debug_line = f"🔎 AI: OFF (fallback=exception)"

            output_flags = _apply_output_caps(command_config.get("output", {}), insufficient_data)
            title_override = None
            if pair_mode and pair_mode_profile == "role3" and pair_user_b is not None:
                other_name = _resolve_display_name(pair_user_b)
                title_override = f"🫛 **STATO BARCELLO CON {other_name}**"
            elif pair_mode and pair_mode_profile == "mod" and pair_user_a is not None and pair_user_b is not None:
                name_a = _resolve_display_name(pair_user_a)
                name_b = _resolve_display_name(pair_user_b)
                title_override = f"🫛 **STATO BARCELLO TRA {name_a} E {name_b}**"
            public_embed = _build_barcello_public_embed(
                result=result,
                channel_name=getattr(interaction.channel, "name", ""),
                window_minutes=window_minutes,
                title_override=title_override,
            )
            details_color = await _get_details_embed_color(profile)
            tier_display_name = await _resolve_tier_display_name(
                profile=profile,
                winner_role_id=winner_role_id,
                guild=interaction.guild,
            )
            details_embed = _build_barcello_details_embed(
                result=result,
                window_minutes=window_minutes,
                output_flags=output_flags,
                profile=profile,
                tier_display_name=tier_display_name,
                embed_color=details_color,
                reasons_text=reasons_text,
                trend_text=trend_text,
                trend_reason=trend_reason,
                personal_advice=personal_advice,
                mod_advice=mod_advice,
                affinity_bullets=affinity_bullets,
                contact_points_bullets=contact_points_bullets,
                pair_mode=pair_mode and not insufficient_data,
                pair_mode_profile=pair_mode_profile if not insufficient_data else None,
                warning_text=warning_text,
                ai_debug_line=ai_debug_line,
                ai_note=ai_note,
            )
            feedback_view = None
            if profile == "mod":
                snapshot_id = f"{interaction.channel_id}:{result.window_start_ts}:{result.window_end_ts}"
                feedback_view = _BarcelloFeedbackView(
                    database=ctx.database,
                    owner_id=interaction.user.id,
                    channel_id=str(interaction.channel_id),
                    snapshot_id=snapshot_id,
                    score_pred=result.score,
                    profile=profile,
                )

            report_embeds = _build_barcello_dm_report(public_embed=public_embed, details_embed=details_embed)
            if await try_send_dm(embeds=report_embeds, view=feedback_view):
                await _send_barcello_dm_notice(interaction, sent=True)
            else:
                await _send_barcello_dm_notice(interaction, sent=False)
        except Exception:
            logger.exception("barcello: unexpected error")
            await send_standard_response(
                interaction,
                top_level="barcello",
                subcommand_path="bm barcello run",
                lines=[("error", "Errore temporaneo, riprova.")],
                kind="error",
                footer_service=ctx.footer,
            )

    logger.info(
        "Registered /bm barcello subcommands=%s",
        [command.name for command in barcello_group.commands],
    )
