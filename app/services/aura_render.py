from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import discord

from app.services.config_file_loader import load_json_file
from app.utils.embed_limits import MAX_EMBED_CHARS, _ensure_embed_limits, _estimate_embed_size, _split_field_chunks

ARCHETYPES_CONFIG_PATH = "app/settings/aura_archetypes.json"
ARCHETYPES_EXAMPLE_PATH = "app/settings/aura_archetypes.example.json"
MISSIONS_CONFIG_PATH = "app/settings/aura_missions.json"
MISSIONS_EXAMPLE_PATH = "app/settings/aura_missions.example.json"


@dataclass
class AuraTrendInfo:
    server_direction: str
    server_comment: str
    channel_direction: str
    channel_comment: str
    server_delta: int
    channel_delta: int


@dataclass
class AuraRenderPayload:
    username: str
    server_name: str
    channel_name: str
    period_line: str
    karma_server_percent: int
    karma_channel_percent: int
    server_points_total: int
    channel_points_month: int
    metrics_json: str
    channel_metrics_json: str
    ledger: list[dict[str, int | str]]
    archetype_metrics: dict[str, object]
    trend: AuraTrendInfo
    assigned_missions: list[dict[str, Any]] | None = None
    points_timeline_lines: list[str] | None = None


def render_karma_bar(percent: int) -> str:
    value = max(0, min(100, int(percent)))
    normalized = value / 100
    segments = ["━"] * 12
    marker_idx = round(normalized * (len(segments) - 1))

    marker = "🟡"
    if normalized < 0.4:
        marker = "🔴"
    elif normalized > 0.6:
        marker = "🟢"

    segments[marker_idx] = marker
    return f"😈{''.join(segments)}😇"


def _direction_label(direction: str) -> str:
    mapping = {
        "improving": "in miglioramento",
        "stable": "stabile",
        "worsening": "in peggioramento",
    }
    return mapping.get(direction, "stabile")


def _compact_bullets(lines: list[str], *, fallback: str) -> str:
    clean = [str(line).strip() for line in lines if str(line).strip()]
    if not clean:
        return f"• {fallback}"
    return "\n".join(f"• {line}" for line in clean)


def _score_lines(ledger_lines: list[str]) -> list[str]:
    if not ledger_lines:
        return ["Nessun dato rilevante nel periodo."]
    if len(ledger_lines) <= 10:
        return ledger_lines
    return ledger_lines[:10]


def _build_main_aura_description(*, aura_payload: AuraRenderPayload) -> str:
    return "\n\n".join(
        [
            f"**🕒 {aura_payload.period_line}**",
            (
                f"**✨ KARMA \"{aura_payload.server_name}\"**\n"
                f"{render_karma_bar(aura_payload.karma_server_percent)}\n\n"
                f"PUNTI AURA TOTALI: **{aura_payload.server_points_total}**"
            ),
            (
                f"**✨ KARMA \"{aura_payload.channel_name}\"**\n"
                f"{render_karma_bar(aura_payload.karma_channel_percent)}\n\n"
                f"PUNTI AURA CANALE: **{aura_payload.channel_points_month}**"
            ),
            (
                "📈 TREND\n"
                f"• Nel server in generale: {_direction_label(aura_payload.trend.server_direction)}. {aura_payload.trend.server_comment}\n"
                f"• Nel \"{aura_payload.channel_name}\": {_direction_label(aura_payload.trend.channel_direction)}. {aura_payload.trend.channel_comment}"
            ),
        ]
    )


def _build_missions(metrics: dict[str, Any], archetype_metrics: dict[str, Any], assigned: list[dict[str, Any]] | None = None) -> list[str]:
    cfg = load_json_file(MISSIONS_CONFIG_PATH) or load_json_file(MISSIONS_EXAMPLE_PATH) or {}
    if assigned:
        pending: list[dict[str, Any]] = []
        completed: list[dict[str, Any]] = []
        expired: list[dict[str, Any]] = []
        for item in assigned:
            status = str(item.get("status", "assigned")).lower()
            if status == "completed":
                completed.append(item)
            elif status in {"expired", "scaduta", "scaduto"}:
                expired.append(item)
            else:
                pending.append(item)

        lines: list[str] = []
        for item in [*pending, *completed, *expired][:3]:
            label = str(item.get("meta", {}).get("label") or item.get("mission_id") or "missione")
            reward = int(item.get("reward_points", 0) or 0)
            status = str(item.get("status", "assigned")).lower()
            if status == "completed":
                box = "✅"
            elif status in {"expired", "scaduta", "scaduto"}:
                box = "⌛"
            else:
                box = "⬜"
            text = f"{box} {label} (+{reward} P.A.)" if reward > 0 else f"{box} {label}"
            if status == "completed":
                text = f"**{text}**"
            lines.append(text)
        return lines or ["Nessuna per oggi."]
    mission_defs = cfg.get("missions", []) if isinstance(cfg, dict) else []
    msg_count = int(metrics.get("msg_count", 0) or 0)
    unique = int(metrics.get("unique_interactions", 0) or 0)
    degrade = int(metrics.get("degrade_events", 0) or 0)
    scores = archetype_metrics.get("scores", {}) if isinstance(archetype_metrics, dict) else {}
    diversity = int(scores.get("diversity", 0) or 0) if isinstance(scores, dict) else 0
    if msg_count < 3:
        return ["Nessuna per oggi."]

    missions: list[str] = []
    if isinstance(mission_defs, list) and mission_defs:
        for item in mission_defs:
            if not isinstance(item, dict) or not bool(item.get("enabled", True)):
                continue
            text = str(item.get("text", "")).strip()
            reward = int(item.get("bonus_points", 0) or 0)
            cond = str(item.get("condition", "always")).strip().lower()
            ok = cond == "always"
            if cond == "low_diversity":
                ok = unique < 2 or diversity < 40
            elif cond == "high_activity":
                ok = msg_count >= 8 and degrade <= 0
            elif cond == "tension":
                ok = degrade > 0
            if ok and text:
                missions.append(f"⬜ {text} (+{reward} P.A.)" if reward > 0 else f"⬜ {text}")
            if len(missions) >= int(cfg.get("max_per_day", 3) or 3):
                break
    if not missions:
        if unique < 2 or diversity < 40:
            missions.append("⬜ Scrivi un messaggio a qualcuno che non contatti di solito. (+5 P.A.)")
        if msg_count >= 2 and unique <= 3:
            missions.append("⬜ Scrivi 2 messaggi a una persona alla quale non hai mai scritto. (+10 P.A.)")
        if degrade > 0:
            missions.append("⬜ Prova a rispondere con tono calmo in una conversazione accesa. (+10 P.A.)")
        if msg_count >= 8 and degrade <= 0:
            missions.append("**✅ Dai il buongiorno per prima.**")
    return missions[:3] if missions else ["Nessuna per oggi."]


def _build_profile_lines(archetype_metrics: dict[str, Any], *, fallback_metrics: dict[str, Any]) -> list[str]:
    cfg = load_json_file(ARCHETYPES_CONFIG_PATH) or load_json_file(ARCHETYPES_EXAMPLE_PATH) or {}
    profile_defs = cfg.get("archetypes", {}) if isinstance(cfg, dict) else {}
    scores = archetype_metrics.get("scores", {}) if isinstance(archetype_metrics, dict) else {}
    if not isinstance(scores, dict) or not scores:
        climate = max(0, min(100, 50 + (int(fallback_metrics.get("invigorate_events", 0) or 0) - int(fallback_metrics.get("degrade_events", 0) or 0)) * 10))
        return [
            f"**🔥 {climate}% Agitatore** — nel periodo hai avuto diversi momenti intensi.",
            f"**🌿 {100 - climate}% Pacificatore** — hai anche segnali di dialogo costruttivo.",
        ]

    agitator_raw = int(scores.get("climate_impact", 0) or 0)
    pacifier = max(0, min(100, 100 - agitator_raw))
    agitator = 100 - pacifier
    ag = profile_defs.get("agitatore", {}) if isinstance(profile_defs, dict) else {}
    pa = profile_defs.get("pacificatore", {}) if isinstance(profile_defs, dict) else {}
    ag_emoji = str(ag.get("emoji", "🔥"))
    ag_label = str(ag.get("label", "Agitatore"))
    ag_desc = str(ag.get("description", "quando il ritmo cresce, tendi a spingere la discussione."))
    pa_emoji = str(pa.get("emoji", "🌿"))
    pa_label = str(pa.get("label", "Pacificatore"))
    pa_desc = str(pa.get("description", "in più momenti mantieni equilibrio e ascolto."))
    return [
        f"**{ag_emoji} {agitator}% {ag_label}** — {ag_desc}",
        f"**{pa_emoji} {pacifier}% {pa_label}** — {pa_desc}",
    ]


def _build_advice_lines(metrics: dict[str, Any], *, channel_name: str) -> list[str]:
    cfg = load_json_file(ARCHETYPES_CONFIG_PATH) or load_json_file(ARCHETYPES_EXAMPLE_PATH) or {}
    advice_cfg = cfg.get("default_advice", []) if isinstance(cfg, dict) else []
    if isinstance(advice_cfg, list) and advice_cfg:
        return [str(x) for x in advice_cfg[:3]]
    lines: list[str] = []
    unique = int(metrics.get("unique_interactions", 0) or 0)
    degrade = int(metrics.get("degrade_events", 0) or 0)
    msg_count = int(metrics.get("msg_count", 0) or 0)
    if unique <= 2:
        lines.append("Per migliorare la tua aura potresti coinvolgere più persone in canali diversi.")
    if degrade > 0:
        lines.append("Potresti bilanciare meglio i toni nei momenti di confronto acceso.")
    if msg_count < 5:
        lines.append(f"Ti farebbe bene partecipare di più in {channel_name} con messaggi brevi ma frequenti.")
    if not lines:
        lines.append("Continua così: il tuo contributo è già ben bilanciato.")
    return lines[:3]


def build_aura_embeds(
    *,
    profile_name: str,
    aura_payload: AuraRenderPayload,
    include_sections: list[str],
    details_title_prefix: str,
    details_embeds_max: int,
    ledger_lines: list[str],
) -> list[discord.Embed]:
    main = discord.Embed(
        title=f"✨ RESOCONTO AURA \"{aura_payload.username}\"",
        color=0x5865F2,
        description=_build_main_aura_description(aura_payload=aura_payload),
    )
    main.set_footer(text="Stima calcolata in loco. Può variare in base ai dati disponibili.")

    details_sections: list[tuple[str, str]] = []
    metrics = json.loads(aura_payload.metrics_json) if aura_payload.metrics_json else {}
    details_sections.append(("🕹️ PUNTEGGI", _compact_bullets(_score_lines(ledger_lines), fallback="Nessun dato rilevante nel periodo.")))

    if "details.missions" in include_sections:
        details_sections.append(("📜 MISSIONI QUOTIDIANE", _compact_bullets(_build_missions(metrics, aura_payload.archetype_metrics, aura_payload.assigned_missions), fallback="Nessuna per oggi.")))
    if "details.profile" in include_sections:
        details_sections.append(("👤 PROFILO PERSONALE", _compact_bullets(_build_profile_lines(aura_payload.archetype_metrics, fallback_metrics=metrics), fallback="Nessun dato rilevante nel periodo.")))
    if "details.advice" in include_sections:
        details_sections.append(("🧭 CONSIGLI PERSONALIZZATI", _compact_bullets(_build_advice_lines(metrics, channel_name=aura_payload.channel_name), fallback="Nessun dato rilevante nel periodo.")))
    if "details.points_timeline" in include_sections and aura_payload.points_timeline_lines is not None:
        details_sections.append(("🧾 BREAKDOWN PUNTI", _compact_bullets(aura_payload.points_timeline_lines, fallback="Nessun dato rilevante nel periodo.")))
    if "details.metrics_aggregated" in include_sections:
        details_sections.append((":bricks: METRICHE AGGREGATE", "Dettagli completi nel file allegato."))

    if "details.note.role1" in include_sections:
        details_sections.append(("📌 NOTE", "• Per conoscere i dettagli sul tuo profilo personale e i consigli su come migliorare la tua aura, abbonati a un piano superiore PRO o PRO MAX. 😉"))
    if "details.note.role2" in include_sections:
        details_sections.append(("📌 NOTE", "• Per avere i consigli su come migliorare la tua aura, abbonati al piano superiore PRO MAX. 😉"))

    if not details_sections:
        return [main]

    page_size = 3
    page_chunks: list[list[tuple[str, str]]] = []
    for idx in range(0, len(details_sections), page_size):
        page_chunks.append(details_sections[idx : idx + page_size])

    max_pages = max(1, details_embeds_max)
    page_chunks = page_chunks[:max_pages]
    total_pages = len(page_chunks)
    details: list[discord.Embed] = []
    tier_label_map = {"role1": "PLUS", "role2": "PRO", "role3": "PRO MAX", "mod": "MOD"}
    tier_label = tier_label_map.get(profile_name, profile_name.upper())

    for page_idx, chunk in enumerate(page_chunks, start=1):
        prefix = details_title_prefix.strip() if details_title_prefix else "🗒️ DETTAGLI AURA"
        embed = discord.Embed(title=f"{prefix} — \"{tier_label}\" (Pag {page_idx}/{total_pages})", color=0x2F3136)
        for name, value in chunk:
            for part_idx, piece in enumerate(_split_field_chunks(value, 1024)):
                embed.add_field(name=name if part_idx == 0 else f"{name} (cont.)", value=piece, inline=False)
        embed.set_footer(text="Dati elaborati in loco. Eventuali imprecisioni sono possibili.")
        details.append(embed)

    embeds = [main, *details]
    sanitized = _ensure_embed_limits(embeds, max_chars=MAX_EMBED_CHARS)
    return [emb for emb in sanitized if _estimate_embed_size(emb) <= MAX_EMBED_CHARS]
