from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import discord
from discord import app_commands

from app.core.service_registry import ServiceRegistry
from app.services.barcello import BarcelloService
from app.services.barcello_calibration import BarcelloCalibrationService
from app.services.entitlements import EntitlementsService
from app.services.ingest import EventEnvelope, IngestService

logger = logging.getLogger(__name__)


def setup(registry: ServiceRegistry) -> None:
    bot: discord.Client = registry.get("bot")
    database = registry.get("database")
    entitlements = EntitlementsService(database)
    registry.register("entitlements", entitlements)
    barcello = BarcelloService(database)
    registry.register("barcello", barcello)
    barcello_calibration = BarcelloCalibrationService(database)
    registry.register("barcello_calibration", barcello_calibration)
    retention = registry.get("retention")
    backfill = registry.get("backfill")
    guard = registry.get("guard")
    status_service = registry.get("status")
    ai_service = registry.get("ai")
    voice_ingest = registry.get("voice_ingest") if registry.has("voice_ingest") else None
    ingest: IngestService = registry.get("ingest")
    config = registry.get("config")
    response_format_supported: bool | None = None

    guild = discord.Object(id=config.guild_id)

    barcellometro_group = app_commands.Group(name="barcellometro", description="Controlli Barcellometro")
    role_group = app_commands.Group(name="role", description="Gestione permessi e limiti")
    stt_group = app_commands.Group(name="stt", description="Impostazioni STT")
    translate_group = app_commands.Group(name="translate", description="Impostazioni traduzione")
    audio_notes_group = app_commands.Group(name="audio_notes", description="Note vocali")
    voice_ingest_group = app_commands.Group(name="voice_ingest", description="Ingest da canale vocale")
    privacy_group = app_commands.Group(name="privacy", description="Privacy per voice ingest")
    status_group = app_commands.Group(name="status", description="Stato servizi")
    barcellometro_group.add_command(role_group)
    barcellometro_group.add_command(stt_group)
    barcellometro_group.add_command(translate_group)
    barcellometro_group.add_command(audio_notes_group)
    barcellometro_group.add_command(voice_ingest_group)

    async def check_permission(interaction: discord.Interaction, command_name: str) -> bool:
        guild = interaction.guild
        is_admin = bool(guild and interaction.user.guild_permissions.administrator)
        role_ids = [role.id for role in getattr(interaction.user, "roles", [])]
        result = await guard.check_command(
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
            role_ids=role_ids,
            command=command_name,
            is_admin=is_admin,
        )
        if result.allowed:
            return True
        message = result.reason
        if result.remaining is not None:
            message += f" Utilizzi rimanenti: {result.remaining}."
        if result.cooldown_remaining is not None:
            message += f" Cooldown: {result.cooldown_remaining}s."
        ephemeral = interaction.guild_id is not None
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(message, ephemeral=ephemeral)
        return False

    async def ensure_admin(interaction: discord.Interaction) -> bool:
        guild = interaction.guild
        is_admin = bool(guild and interaction.user.guild_permissions.administrator)
        if is_admin:
            return True
        ephemeral = interaction.guild_id is not None
        if interaction.response.is_done():
            await interaction.followup.send("Solo admin.", ephemeral=ephemeral)
        else:
            await interaction.response.send_message("Solo admin.", ephemeral=ephemeral)
        return False

    async def set_setting(key: str, value: str) -> None:
        await database.set_setting(key, value)

    async def get_setting(key: str, default: str) -> str:
        stored = await database.get_setting(key)
        return stored if stored is not None else default

    async def send_ephemeral(interaction: discord.Interaction, message: str) -> None:
        ephemeral = interaction.guild_id is not None
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(message, ephemeral=ephemeral)

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
        embed.add_field(name=name, value=value, inline=False)

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
            stored = await get_setting("barcello.details_color_admin", "")
            return _parse_hex_color(stored) or admin_color
        if profile == "mod":
            stored = await get_setting("barcello.details_color_mod", "")
            return _parse_hex_color(stored) or mod_color
        stored = await get_setting("barcello.details_color_default", "")
        return _parse_hex_color(stored) or default_color

    async def _get_tier_label(profile: str) -> str:
        # Optional manual override for tier labels if you want a name different from the Discord role.
        stored = await get_setting(f"barcello.tier_label.{profile}", "")
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
            if len(text) > 120:
                text = f"{text[:117]}..."
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
            if len(text) > 120:
                text = f"{text[:117]}..."
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
        result: BarcelloResult,
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
        embed.set_footer(text="Barcellometro")
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
        embed.set_footer(text="Barcellometro")
        return embed

    def _build_barcello_details_embed(
        *,
        result: BarcelloResult,
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
        ai_note: str,
    ) -> discord.Embed:
        embed = discord.Embed(title=f"🧾 **DETTAGLI BARCELLO — {tier_display_name}**", color=embed_color)
        if warning_text and not _is_effectively_empty_text(warning_text):
            _add_section(embed, name="⚠️ **CAMPIONE PICCOLO**", value=_with_spacing(warning_text))
        if output_flags.get("show_motivation") and reasons_text:
            if not _is_effectively_empty_text(reasons_text):
                _add_section(embed, name="🔥 **MOTIVAZIONI**", value=_with_spacing(reasons_text))
        if output_flags.get("show_trend") and (result.trend or trend_text):
            if trend_text and not _is_effectively_empty_text(trend_text):
                trend_value = trend_text
            else:
                trend_value, _ = _trend_display(result.trend)
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
        embed.set_footer(text="Barcellometro")
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
                await interaction.response.send_message("Feedback riservato ai mod.", ephemeral=True)
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
                await interaction.response.send_message("Feedback riservato ai mod.", ephemeral=True)
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
                await interaction.response.send_message("Seleziona motivo e correzione.", ephemeral=True)
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
        nonlocal response_format_supported
        try:
            if response_format_supported is False:
                response = await client.responses.create(
                    model=model,
                    input=input_payload,
                )
            else:
                response = await client.responses.create(
                    model=model,
                    response_format={"type": "json_object"},
                    input=input_payload,
                )
                response_format_supported = True
        except TypeError as exc:
            if "response_format" not in str(exc):
                raise
            if response_format_supported is not False:
                logger.info("OpenAI response_format unsupported; using JSON-in-text mode")
            response_format_supported = False
            response = await client.responses.create(
                model=model,
                input=input_payload,
            )
        logger.info("OpenAI response received")
        ai_text = _extract_ai_text(response)
        payload = _parse_json_safe(ai_text)
        return payload, ai_text

    def voice_ingest_key(bot_id: int, key: str) -> str:
        return f"voice_ingest.{bot_id}.{key}"

    async def resolve_voice_channel(
        interaction: discord.Interaction,
        voice_channel: discord.VoiceChannel | None,
    ) -> discord.VoiceChannel | None:
        if voice_channel is not None:
            return voice_channel
        if isinstance(interaction.user, discord.Member) and interaction.user.voice:
            return interaction.user.voice.channel
        return None

    async def resolve_affected_bots(voice_channel: discord.VoiceChannel) -> list[int]:
        bot_ids = {member.id for member in voice_channel.members if member.bot}
        if not bot_ids:
            bot_ids.update(
                int(bot_id)
                for bot_id in await database.find_voice_ingest_bots_for_voice_channel(str(voice_channel.id))
                if bot_id.isdigit()
            )
        return sorted(bot_ids)

    async def emit_privacy_event(
        interaction: discord.Interaction,
        event_type: str,
        voice_channel: discord.VoiceChannel,
        affected_bot_ids: list[int],
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        await ingest.emit(
            EventEnvelope(
                event_id=str(uuid4()),
                event_type=event_type,
                platform="discord",
                ts=ts,
                guild_id=str(interaction.guild_id) if interaction.guild_id else None,
                channel_id=str(voice_channel.id),
                thread_id=None,
                author_id=str(interaction.user.id),
                content=None,
                meta={"voice_channel_id": str(voice_channel.id), "affected_bot_ids": affected_bot_ids},
            )
        )

    @barcellometro_group.command(name="check", description="Abilita o disabilita la raccolta eventi nel canale")
    @app_commands.describe(state="on/off")
    @app_commands.choices(state=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
    async def check_command(interaction: discord.Interaction, state: app_commands.Choice[str]) -> None:
        if not await check_permission(interaction, "barcellometro.check"):
            return
        if not interaction.channel or not isinstance(interaction.channel, discord.abc.GuildChannel):
            await interaction.response.send_message("Questo comando funziona solo nei canali della guild.", ephemeral=True)
            return
        enabled = 1 if state.value == "on" else 0
        await database.upsert_channel(
            channel_id=str(interaction.channel.id),
            guild_id=str(interaction.guild_id),
            name=interaction.channel.name,
            enabled=enabled,
            channel_type=str(interaction.channel.type),
            category_id=str(interaction.channel.category_id) if interaction.channel.category_id else None,
            is_nsfw=1 if interaction.channel.is_nsfw() else 0,
            slowmode_delay=interaction.channel.slowmode_delay,
        )
        await interaction.response.send_message(
            f"Canale {'abilitato' if enabled else 'disabilitato'} per la raccolta eventi.",
            ephemeral=True,
        )

    @barcellometro_group.command(name="retention", description="Gestisci la retention dei dati")
    @app_commands.describe(action="get/set", days="Numero di giorni di retention")
    @app_commands.choices(action=[app_commands.Choice(name="get", value="get"), app_commands.Choice(name="set", value="set")])
    async def retention_command(
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        days: int | None = None,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.retention"):
            return
        if action.value == "get":
            current = await retention.get_retention_days()
            await interaction.response.send_message(f"Retention attuale: {current} giorni.", ephemeral=True)
            return
        if days is None or days <= 0:
            await interaction.response.send_message("Specifica un numero di giorni valido.", ephemeral=True)
            return
        await retention.set_retention_days(days)
        await interaction.response.send_message(f"Retention aggiornata a {days} giorni.", ephemeral=True)

    @barcellometro_group.command(name="backfill", description="Gestisci il backfill dei dati")
    @app_commands.describe(state="on/off", days="Numero di giorni di backfill")
    @app_commands.choices(state=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
    async def backfill_command(
        interaction: discord.Interaction,
        state: app_commands.Choice[str] | None = None,
        days: int | None = None,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.backfill"):
            return
        if interaction.response.is_done():
            responder = interaction.followup
        else:
            responder = interaction.response
        if state is None and days is None:
            current_days = await backfill.get_backfill_days()
            enabled = await backfill.is_enabled()
            await responder.send_message(
                f"Backfill {'attivo' if enabled else 'disattivato'} ({current_days} giorni).",
                ephemeral=True,
            )
            return

        if days is not None:
            if days <= 0:
                await responder.send_message("Specifica un numero di giorni valido.", ephemeral=True)
                return
            await backfill.set_backfill_days(days)

        if state is not None:
            await backfill.set_enabled(state.value == "on")

        if await backfill.is_enabled():
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True, thinking=True)
            result = await backfill.run_once(force_full_window=True)
            await interaction.followup.send(
                "Backfill completato. "
                f"Messaggi: {result.messages}, Eventi: {result.events}, Canali: {result.channels}, Errori: {result.errors}.",
                ephemeral=True,
            )
            return

        await responder.send_message("Backfill disattivato.", ephemeral=True)

    @barcellometro_group.command(name="ai", description="Abilita o disabilita il servizio AI")
    @app_commands.describe(state="on/off")
    @app_commands.choices(state=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
    async def ai_command(interaction: discord.Interaction, state: app_commands.Choice[str]) -> None:
        if not await check_permission(interaction, "barcellometro.ai"):
            return
        enabled = state.value == "on"
        await ai_service.set_enabled(enabled)
        await interaction.response.send_message(
            f"AI {'abilitata' if enabled else 'disabilitata'}.",
            ephemeral=True,
        )

    @barcellometro_group.command(name="ai-model", description="Imposta il modello AI per un task")
    @app_commands.describe(task="Task AI", model="Nome modello")
    @app_commands.choices(
        task=[
            app_commands.Choice(name="summary", value="summary"),
            app_commands.Choice(name="transcription", value="transcription"),
            app_commands.Choice(name="translation", value="translation"),
        ]
    )
    async def ai_model_command(
        interaction: discord.Interaction,
        task: app_commands.Choice[str],
        model: str,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.ai-model"):
            return
        await ai_service.set_model(task.value, model)
        await interaction.response.send_message(
            f"Modello per {task.value} aggiornato a {model}.",
            ephemeral=True,
        )

    @stt_group.command(name="backend", description="Imposta il backend STT")
    @app_commands.choices(
        backend=[
            app_commands.Choice(name="local", value="local"),
            app_commands.Choice(name="ai", value="ai"),
        ]
    )
    async def stt_backend_command(
        interaction: discord.Interaction,
        backend: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.stt.backend"):
            return
        await set_setting("stt.backend", backend.value)
        await interaction.response.send_message(f"Backend STT impostato su {backend.value}.", ephemeral=True)

    @stt_group.command(name="model", description="Imposta il modello STT locale")
    @app_commands.choices(
        model=[
            app_commands.Choice(name="small", value="small"),
            app_commands.Choice(name="medium", value="medium"),
            app_commands.Choice(name="large-v3", value="large-v3"),
        ]
    )
    async def stt_model_command(
        interaction: discord.Interaction,
        model: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.stt.model"):
            return
        await set_setting("stt.local.model", model.value)
        await interaction.response.send_message(f"Modello STT impostato su {model.value}.", ephemeral=True)

    @stt_group.command(name="compute", description="Imposta il compute type STT locale")
    @app_commands.choices(
        compute=[
            app_commands.Choice(name="int8", value="int8"),
            app_commands.Choice(name="int8_float16", value="int8_float16"),
            app_commands.Choice(name="float16", value="float16"),
        ]
    )
    async def stt_compute_command(
        interaction: discord.Interaction,
        compute: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.stt.compute"):
            return
        await set_setting("stt.local.compute_type", compute.value)
        await interaction.response.send_message(f"Compute STT impostato su {compute.value}.", ephemeral=True)

    @stt_group.command(name="beam", description="Imposta il beam size STT locale")
    @app_commands.choices(
        beam=[
            app_commands.Choice(name="1", value="1"),
            app_commands.Choice(name="3", value="3"),
            app_commands.Choice(name="5", value="5"),
        ]
    )
    async def stt_beam_command(
        interaction: discord.Interaction,
        beam: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.stt.beam"):
            return
        await set_setting("stt.local.beam_size", beam.value)
        await interaction.response.send_message(f"Beam STT impostato su {beam.value}.", ephemeral=True)

    @stt_group.command(name="language", description="Imposta la lingua STT locale")
    @app_commands.choices(
        language=[
            app_commands.Choice(name="it", value="it"),
            app_commands.Choice(name="auto", value="auto"),
        ]
    )
    async def stt_language_command(
        interaction: discord.Interaction,
        language: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.stt.language"):
            return
        await set_setting("stt.local.language_hint", language.value)
        await interaction.response.send_message(f"Lingua STT impostata su {language.value}.", ephemeral=True)

    @translate_group.command(name="backend", description="Imposta il backend di traduzione")
    @app_commands.choices(
        backend=[
            app_commands.Choice(name="local", value="local"),
            app_commands.Choice(name="ai", value="ai"),
        ]
    )
    async def translate_backend_command(
        interaction: discord.Interaction,
        backend: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.translate.backend"):
            return
        await set_setting("translate.backend", backend.value)
        await interaction.response.send_message(
            f"Backend traduzione impostato su {backend.value}.",
            ephemeral=True,
        )

    @translate_group.command(name="target", description="Imposta la lingua target")
    @app_commands.choices(target=[app_commands.Choice(name="it", value="it")])
    async def translate_target_command(
        interaction: discord.Interaction,
        target: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.translate.target"):
            return
        await set_setting("translate.target_lang", target.value)
        await interaction.response.send_message(
            f"Lingua target impostata su {target.value}.",
            ephemeral=True,
        )

    @audio_notes_group.command(name="on", description="Abilita le note vocali")
    async def audio_notes_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.audio_notes.on"):
            return
        await set_setting("audio_notes.enabled", "true")
        await interaction.response.send_message("Note vocali abilitate.", ephemeral=True)

    @audio_notes_group.command(name="off", description="Disabilita le note vocali")
    async def audio_notes_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.audio_notes.off"):
            return
        await set_setting("audio_notes.enabled", "false")
        await interaction.response.send_message("Note vocali disabilitate.", ephemeral=True)

    @audio_notes_group.command(name="status", description="Mostra lo stato note vocali")
    async def audio_notes_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.audio_notes.status"):
            return
        enabled = (await get_setting("audio_notes.enabled", "false")).lower() in {"1", "true", "yes", "y"}
        max_mb = await get_setting("audio_notes.max_mb", os.getenv("AUDIO_NOTES_MAX_MB", "25"))
        max_duration = await get_setting("audio_notes.max_duration_s", os.getenv("AUDIO_NOTES_MAX_DURATION_S", "180"))
        max_chars = await get_setting("audio_notes.discord_max_chars", os.getenv("AUDIO_NOTES_DISCORD_MAX_CHARS", "1900"))
        queue_max = await get_setting("audio_notes.queue_max", os.getenv("AUDIO_NOTES_QUEUE_MAX", "50"))
        await interaction.response.send_message(
            "Audio notes "
            f"{'attivo' if enabled else 'disattivo'} | "
            f"max_mb={max_mb}, max_duration_s={max_duration}, max_chars={max_chars}, queue_max={queue_max}",
            ephemeral=True,
        )

    @audio_notes_group.command(name="limits", description="Imposta i limiti note vocali")
    @app_commands.describe(
        max_mb="Massimo MB",
        max_duration_s="Durata massima in secondi",
        discord_max_chars="Massimo caratteri per messaggio",
        queue_max="Dimensione coda",
    )
    async def audio_notes_limits_command(
        interaction: discord.Interaction,
        max_mb: int,
        max_duration_s: int,
        discord_max_chars: int,
        queue_max: int,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.audio_notes.limits"):
            return
        if max_mb <= 0 or max_duration_s <= 0 or discord_max_chars <= 0 or queue_max <= 0:
            await interaction.response.send_message("Specifica limiti validi (> 0).", ephemeral=True)
            return
        await set_setting("audio_notes.max_mb", str(max_mb))
        await set_setting("audio_notes.max_duration_s", str(max_duration_s))
        await set_setting("audio_notes.discord_max_chars", str(discord_max_chars))
        await set_setting("audio_notes.queue_max", str(queue_max))
        await interaction.response.send_message("Limiti note vocali aggiornati.", ephemeral=True)

    @privacy_group.command(name="on", description="Attiva privacy (disconnette il bot dal vocale)")
    @app_commands.describe(voice_channel="Canale vocale (opzionale)")
    async def privacy_on(
        interaction: discord.Interaction,
        voice_channel: discord.VoiceChannel | None = None,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.privacy.on"):
            return
        resolved_voice = await resolve_voice_channel(interaction, voice_channel)
        if resolved_voice is None:
            await interaction.response.send_message("Specifica un canale vocale.", ephemeral=True)
            return
        bot_ids = await resolve_affected_bots(resolved_voice)
        if not bot_ids:
            await interaction.response.send_message("Nessun bot configurato per questo canale vocale.", ephemeral=True)
            return
        for bot_id in bot_ids:
            await set_setting(voice_ingest_key(bot_id, "privacy_mode"), "true")
            await set_setting(voice_ingest_key(bot_id, "auto_join"), "false")
            await set_setting(voice_ingest_key(bot_id, "enabled"), "true")
        await emit_privacy_event(interaction, "voice.privacy_on", resolved_voice, bot_ids)
        if voice_ingest and bot.user and bot.user.id in bot_ids:
            await voice_ingest.leave()
        await interaction.response.send_message(
            f"Privacy attivata per {resolved_voice.name}. Bot interessati: {len(bot_ids)}.",
            ephemeral=True,
        )

    @privacy_group.command(name="off", description="Disattiva privacy (riabilita auto-join)")
    @app_commands.describe(voice_channel="Canale vocale (opzionale)")
    async def privacy_off(
        interaction: discord.Interaction,
        voice_channel: discord.VoiceChannel | None = None,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.privacy.off"):
            return
        resolved_voice = await resolve_voice_channel(interaction, voice_channel)
        if resolved_voice is None:
            await interaction.response.send_message("Specifica un canale vocale.", ephemeral=True)
            return
        bot_ids = await resolve_affected_bots(resolved_voice)
        if not bot_ids:
            await interaction.response.send_message("Nessun bot configurato per questo canale vocale.", ephemeral=True)
            return
        for bot_id in bot_ids:
            await set_setting(voice_ingest_key(bot_id, "privacy_mode"), "false")
            await set_setting(voice_ingest_key(bot_id, "auto_join"), "true")
            await set_setting(voice_ingest_key(bot_id, "enabled"), "true")
        await emit_privacy_event(interaction, "voice.privacy_off", resolved_voice, bot_ids)
        non_bot_members = [m for m in resolved_voice.members if not m.bot]
        if voice_ingest and bot.user and bot.user.id in bot_ids and non_bot_members:
            await voice_ingest.join(resolved_voice)
        await interaction.response.send_message(
            f"Privacy disattivata per {resolved_voice.name}. Bot interessati: {len(bot_ids)}.",
            ephemeral=True,
        )

    @privacy_group.command(name="status", description="Mostra lo stato privacy")
    @app_commands.describe(voice_channel="Canale vocale (opzionale)")
    async def privacy_status(
        interaction: discord.Interaction,
        voice_channel: discord.VoiceChannel | None = None,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.privacy.status"):
            return
        resolved_voice = await resolve_voice_channel(interaction, voice_channel)
        if resolved_voice is None:
            await interaction.response.send_message("Specifica un canale vocale.", ephemeral=True)
            return
        bot_ids = await resolve_affected_bots(resolved_voice)
        if not bot_ids:
            await interaction.response.send_message("Nessun bot configurato per questo canale vocale.", ephemeral=True)
            return
        states = []
        for bot_id in bot_ids:
            privacy_mode = (await get_setting(voice_ingest_key(bot_id, "privacy_mode"), "false")).lower() in {"1", "true", "yes", "y"}
            auto_join = (await get_setting(voice_ingest_key(bot_id, "auto_join"), "true")).lower() in {"1", "true", "yes", "y"}
            enabled = (await get_setting(voice_ingest_key(bot_id, "enabled"), "true")).lower() in {"1", "true", "yes", "y"}
            states.append((bot_id, privacy_mode, auto_join, enabled))
        privacy_values = {state[1] for state in states}
        last_event = await database.get_last_privacy_event(str(resolved_voice.id))
        last_change = "N/A"
        if last_event:
            actor = f"<@{last_event['actor_id']}>" if last_event.get("actor_id") else "sconosciuto"
            last_change = f"{last_event['event_type']} alle {last_event['ts']} da {actor}"
        if len(privacy_values) == 1:
            status = "ON" if True in privacy_values else "OFF"
            message = (
                f"Privacy {status} su {resolved_voice.name}. Bot: {len(bot_ids)}. "
                f"Ultimo cambio: {last_change}"
            )
        else:
            lines = [
                f"Bot {bot_id}: privacy={'ON' if privacy else 'OFF'}, auto_join={auto_join}, enabled={enabled}"
                for bot_id, privacy, auto_join, enabled in states
            ]
            message = (
                f"Privacy su {resolved_voice.name} (stati misti):\n"
                + "\n".join(lines)
                + f"\nUltimo cambio: {last_change}"
            )
        await interaction.response.send_message(message, ephemeral=True)

    @voice_ingest_group.command(name="join", description="Join manuale del canale vocale")
    @app_commands.describe(voice_channel="Canale vocale")
    async def voice_ingest_join(
        interaction: discord.Interaction,
        voice_channel: discord.VoiceChannel,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.voice_ingest.join"):
            return
        if not bot.user:
            await interaction.response.send_message("Bot non pronto.", ephemeral=True)
            return
        await set_setting(voice_ingest_key(bot.user.id, "target_voice_channel_id"), str(voice_channel.id))
        await interaction.response.send_message(
            f"Richiesto join su {voice_channel.name}.",
            ephemeral=True,
        )
        if voice_ingest:
            await voice_ingest.join(voice_channel)

    @voice_ingest_group.command(name="leave", description="Leave manuale del canale vocale")
    async def voice_ingest_leave(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.voice_ingest.leave"):
            return
        await interaction.response.send_message("Richiesto leave dal canale vocale.", ephemeral=True)
        if voice_ingest:
            await voice_ingest.leave()

    @status_group.command(name="barcellometro", description="Stato generale o di un servizio/plugin")
    @app_commands.describe(service="Nome servizio o plugin")
    async def status_barcellometro(interaction: discord.Interaction, service: str | None = None) -> None:
        if not await check_permission(interaction, "status.barcellometro"):
            return
        if service:
            status = status_service.component_status(service)
            message = (
                f"**{service}**\n"
                f"Active: {status['active']}\n"
                f"State: {status['state']}\n"
                f"Metrics: {status['metrics']}"
            )
            await interaction.response.send_message(message, ephemeral=True)
            return
        general = await status_service.general_status()
        message = (
            "**Barcellometro Status**\n"
            f"Bot: online\n"
            f"DB Path: {general['db_path']}\n"
            f"Retention Days: {general['retention_days']}\n"
            f"Enabled Channels: {general['enabled_channels']}\n"
            f"Users: {general['users_count']}\n"
            f"Messages: {general['messages_count']}\n"
            f"Events: {general['events_count']}\n"
            f"Last Event: {general['last_event_ts']}"
        )
        await interaction.response.send_message(message, ephemeral=True)

    # Settings JSON for /barcello (entitlements.policies):
    # {
    #   "commands": {
    #     "barcello": {
    #       "profiles": {
    #         "<profile>": {
    #           "allowed": true,
    #           "output": {
    #             "show_score": true,
    #             "show_motivation": true,
    #             "show_trend": true,
    #             "show_advice": true,
    #             "show_mod_metrics": false
    #           },
    #           "capabilities": ["analysis.ai_preferred"],
    #           "messages": {
    #             "dm_text": "Serve PLUS.",
    #             "footer_text": "Passa a PRO per il trend."
    #           }
    #         }
    #       }
    #     }
    #   },
    #   "features": {
    #     "ai": { "allowed_profiles": ["role2", "role3", "mod"] }
    #   }
    # }
    @app_commands.command(name="barcello", description="Mostra lo stato del barcello (in DM)")
    @app_commands.rename(window_minutes="minuti")
    @app_commands.describe(
        user1="Utente 1 (opzionale)",
        user2="Utente 2 (opzionale)",
        window_minutes="Finestra in minuti",
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
            entitlements_service: EntitlementsService = registry.get("entitlements")
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

            if not await check_permission(interaction, "barcello"):
                return

            if window_minutes is None:
                raw_default = await get_setting("barcello.default_window_minutes", "30")
                try:
                    window_minutes = int(raw_default)
                except ValueError:
                    window_minutes = 30
            if window_minutes <= 0:
                window_minutes = 30

            if user2 is not None and user1 is None:
                await send_ephemeral(interaction, "Specifica il primo utente.")
                return
            if user1 is not None and user2 is not None and user1.id == user2.id:
                await send_ephemeral(interaction, "Seleziona due utenti diversi.")
                return
            if config.ignore_bots:
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
                result = await barcello.compute_pair(
                    str(interaction.guild_id),
                    str(interaction.channel_id),
                    str(pair_user_a.id),
                    str(pair_user_b.id),
                    window_minutes,
                )
            else:
                result = await barcello.compute_channel(
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
                        "ai_key_present": bool(config.openai_api_key),
                        "cache_hit": cache_hit,
                        "model": None,
                        "fallback_reason": "no_data",
                    },
                )
                no_data_embed = _build_barcello_no_data_embed(title=title, window_minutes=window_minutes)
                if await try_send_dm(embed=no_data_embed):
                    await interaction.followup.send("Ti ho inviato un DM", ephemeral=True)
                else:
                    await interaction.followup.send(
                        "Non riesco a inviarti DM (privacy). Abilita i messaggi privati dal server.",
                        ephemeral=True,
                    )
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
            trend_direction, trend_delta = _normalize_trend(result.trend)
            trend_text = _render_trend(trend_direction, trend_delta) if result.trend else ""
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

            ai_key_present = bool(config.openai_api_key)
            ai_allowed = False
            ai_reason = ""
            if insufficient_data:
                ai_reason = "insufficient_data"
            elif "analysis.ai_preferred" not in (command_config.get("capabilities") or []):
                ai_reason = "disabled_by_entitlements"
            elif not registry.has("ai"):
                ai_reason = "missing_key"
            else:
                ai_enabled = await entitlements_service.is_feature_allowed(interaction.user, "ai")
                ai_service_enabled = ai_service.is_enabled() if ai_service else False
                ai_reason = "" if ai_enabled and ai_service_enabled else "disabled_by_entitlements"
            if not ai_reason:
                model_name = ai_service.get_model("summary") if ai_service else None
                client_ready = ai_service.client() if ai_service else None
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
                if registry.has("ai"):
                    ai_enabled = await entitlements_service.is_feature_allowed(interaction.user, "ai")
                    ai_service_enabled = ai_service.is_enabled() if ai_service else False
                    if ai_enabled and ai_service_enabled and ai_service:
                        client = ai_service.client()
                        model = ai_service.get_model("summary")
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
                    database=database,
                    owner_id=interaction.user.id,
                    channel_id=str(interaction.channel_id),
                    snapshot_id=snapshot_id,
                    score_pred=result.score,
                    profile=profile,
                )

            if await try_send_dm(embeds=[public_embed, details_embed], view=feedback_view):
                await interaction.followup.send("Ti ho inviato un DM", ephemeral=True)
            else:
                await interaction.followup.send(
                    "Non riesco a inviarti DM (privacy). Abilita i messaggi privati dal server.",
                    ephemeral=True,
                )
        except Exception:
            logger.exception("barcello: unexpected error")
            await interaction.followup.send("Errore temporaneo, riprova.", ephemeral=True)

    @barcellometro_group.command(name="calibrate", description="Calibra automaticamente i pesi del barcello")
    async def barcellometro_calibrate(interaction: discord.Interaction) -> None:
        entitlements_service: EntitlementsService = registry.get("entitlements")
        profile, _ = await entitlements_service.resolve_profile_with_role_id(interaction.user)
        if profile != "mod":
            await interaction.response.send_message("Feedback riservato ai mod.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        calibration_service: BarcelloCalibrationService = registry.get("barcello_calibration")
        result = await calibration_service.run_calibration(days=14, min_samples=20)
        if result.get("updated"):
            message = f"Calibrazione aggiornata. Campioni: {result.get('samples')}. {result.get('summary')}"
        else:
            message = f"Calibrazione non aggiornata. Campioni: {result.get('samples')}. {result.get('summary')}"
        await interaction.followup.send(message, ephemeral=True)

    bot.tree.add_command(barcellometro_group, guild=guild)
    bot.tree.add_command(status_group, guild=guild)
    bot.tree.add_command(privacy_group, guild=guild)
    bot.tree.add_command(barcello_command, guild=guild)

    @role_group.command(name="set-role", description="Imposta limiti per un ruolo su un comando")
    @app_commands.describe(role="Ruolo", command="Nome comando", usage_limit="Limite utilizzi (vuoto = illimitato)", cooldown_seconds="Cooldown in secondi")
    async def role_set_command(
        interaction: discord.Interaction,
        role: discord.Role,
        command: str,
        usage_limit: int | None = None,
        cooldown_seconds: int | None = None,
    ) -> None:
        if not await ensure_admin(interaction):
            return
        if usage_limit is not None and usage_limit <= 0:
            await interaction.response.send_message("Specifica un limite utilizzi valido.", ephemeral=True)
            return
        if cooldown_seconds is not None and cooldown_seconds < 0:
            await interaction.response.send_message("Specifica un cooldown valido.", ephemeral=True)
            return
        await database.upsert_role_policy(
            guild_id=str(interaction.guild_id),
            role_id=str(role.id),
            command=command,
            usage_limit=usage_limit,
            cooldown_seconds=cooldown_seconds,
        )
        await interaction.response.send_message("Policy ruolo aggiornata.", ephemeral=True)

    @role_group.command(name="set-user", description="Imposta limiti per un utente su un comando")
    @app_commands.describe(user="Utente", command="Nome comando", usage_limit="Limite utilizzi (vuoto = illimitato)", cooldown_seconds="Cooldown in secondi")
    async def user_set_command(
        interaction: discord.Interaction,
        user: discord.User,
        command: str,
        usage_limit: int | None = None,
        cooldown_seconds: int | None = None,
    ) -> None:
        if not await ensure_admin(interaction):
            return
        if usage_limit is not None and usage_limit <= 0:
            await interaction.response.send_message("Specifica un limite utilizzi valido.", ephemeral=True)
            return
        if cooldown_seconds is not None and cooldown_seconds < 0:
            await interaction.response.send_message("Specifica un cooldown valido.", ephemeral=True)
            return
        await database.upsert_user_policy(
            guild_id=str(interaction.guild_id),
            user_id=str(user.id),
            command=command,
            usage_limit=usage_limit,
            cooldown_seconds=cooldown_seconds,
        )
        await interaction.response.send_message("Policy utente aggiornata.", ephemeral=True)

    @role_group.command(name="clear-role", description="Rimuove la policy di un ruolo")
    @app_commands.describe(role="Ruolo", command="Nome comando")
    async def role_clear_command(
        interaction: discord.Interaction,
        role: discord.Role,
        command: str,
    ) -> None:
        if not await ensure_admin(interaction):
            return
        await database.delete_role_policy(
            guild_id=str(interaction.guild_id),
            role_id=str(role.id),
            command=command,
        )
        await interaction.response.send_message("Policy ruolo rimossa.", ephemeral=True)

    @role_group.command(name="clear-user", description="Rimuove la policy di un utente")
    @app_commands.describe(user="Utente", command="Nome comando")
    async def user_clear_command(
        interaction: discord.Interaction,
        user: discord.User,
        command: str,
    ) -> None:
        if not await ensure_admin(interaction):
            return
        await database.delete_user_policy(
            guild_id=str(interaction.guild_id),
            user_id=str(user.id),
            command=command,
        )
        await interaction.response.send_message("Policy utente rimossa.", ephemeral=True)

    @role_group.command(name="show-role", description="Mostra le policy di un ruolo")
    @app_commands.describe(role="Ruolo")
    async def role_show_command(interaction: discord.Interaction, role: discord.Role) -> None:
        if not await ensure_admin(interaction):
            return
        rows = await database.fetch_role_policies(str(interaction.guild_id), str(role.id))
        if not rows:
            await interaction.response.send_message("Nessuna policy per questo ruolo.", ephemeral=True)
            return
        lines = []
        for row in rows:
            limit = row["usage_limit"] if row["usage_limit"] is not None else "∞"
            cooldown = row["cooldown_seconds"] if row["cooldown_seconds"] is not None else "∞"
            lines.append(f"{row['command']}: limit={limit} cooldown={cooldown}")
        await interaction.response.send_message("\\n".join(lines), ephemeral=True)

    @role_group.command(name="show-user", description="Mostra le policy di un utente")
    @app_commands.describe(user="Utente")
    async def user_show_command(interaction: discord.Interaction, user: discord.User) -> None:
        if not await ensure_admin(interaction):
            return
        rows = await database.fetch_user_policies(str(interaction.guild_id), str(user.id))
        if not rows:
            await interaction.response.send_message("Nessuna policy per questo utente.", ephemeral=True)
            return
        lines = []
        for row in rows:
            limit = row["usage_limit"] if row["usage_limit"] is not None else "∞"
            cooldown = row["cooldown_seconds"] if row["cooldown_seconds"] is not None else "∞"
            lines.append(f"{row['command']}: limit={limit} cooldown={cooldown}")
        await interaction.response.send_message("\\n".join(lines), ephemeral=True)

    async def handle_ready() -> None:
        try:
            synced = await bot.tree.sync(guild=guild)
            logger.info("Synced %s commands for guild %s", len(synced), config.guild_id)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to sync commands")

    bot.add_listener(handle_ready, "on_ready")
