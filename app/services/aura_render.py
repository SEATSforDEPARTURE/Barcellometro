from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import discord

from app.utils.embed_limits import MAX_EMBED_CHARS, _ensure_embed_limits, _estimate_embed_size, _split_field_chunks


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
    period_row: str
    period_label: str
    karma_server_percent: int
    karma_channel_percent: int
    server_points_total: int
    channel_points_month: int
    metrics_json: str
    channel_metrics_json: str
    ledger: list[dict[str, int | str]]
    archetype_metrics: dict[str, object]
    trend: AuraTrendInfo


def render_karma_bar(percent: int) -> str:
    value = max(0, min(100, int(percent)))
    center = "🟢"
    if value < 35:
        center = "🔴"
    elif value < 67:
        center = "🟡"
    return f"😈━━━━━━━━{center}━━━━😇  {value}%"


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


def _reason_to_text(reason_code: str, value: int, *, channel_name: str) -> str:
    points = f"{'👍' if value >= 0 else '👎'} {'+' if value >= 0 else ''}{value} P.A."
    code = reason_code.lower()
    if "invigorate" in code:
        return f"**{points}** per aver migliorato il clima in {channel_name}."
    if "degrade" in code:
        return f"**{points}** per aver irrigidito il clima in {channel_name}."
    if "reply" in code:
        return f"**{points}** per aver risposto ad altri utenti in {channel_name}."
    if "conversation" in code or "start" in code:
        return f"**{points}** per aver avviato conversazioni in {channel_name}."
    if "ondemand.aggregate" in code or "batch.aggregate" in code:
        return f"**{points}** bilancio complessivo del periodo in {channel_name}."
    return f"**{points}** attività registrata ({reason_code}) in {channel_name}."


def _score_lines(ledger: list[dict[str, int | str]], *, channel_name: str) -> list[str]:
    if not ledger:
        return ["Nessun dato rilevante nel periodo."]
    natural = [_reason_to_text(str(item.get("reason_code", "evento")), int(item.get("total", 0) or 0), channel_name=channel_name) for item in ledger]
    if len(natural) <= 10:
        return natural
    visible = natural[:10]
    remainder = [int(item.get("total", 0) or 0) for item in ledger[10:]]
    rem_total = sum(remainder)
    rem_abs = abs(rem_total)
    if rem_abs > 0:
        tail = f"**{'👍 +' if rem_total >= 0 else '👎 -'} altri {rem_abs} P.A.**"
        visible.append(tail)
    return visible


def _build_missions(metrics: dict[str, Any], archetype_metrics: dict[str, Any]) -> list[str]:
    msg_count = int(metrics.get("msg_count", 0) or 0)
    unique = int(metrics.get("unique_interactions", 0) or 0)
    degrade = int(metrics.get("degrade_events", 0) or 0)
    scores = archetype_metrics.get("scores", {}) if isinstance(archetype_metrics, dict) else {}
    diversity = int(scores.get("diversity", 0) or 0) if isinstance(scores, dict) else 0
    if msg_count < 3:
        return ["Nessuna per oggi."]

    missions: list[str] = []
    if unique < 2 or diversity < 40:
        missions.append("🔲 Scrivi un messaggio a qualcuno che non contatti di solito. (+5 P.A.)")
    if msg_count >= 2 and unique <= 3:
        missions.append("🔲 Scrivi 2 messaggi a una persona alla quale non hai mai scritto. (+10 P.A.)")
    if degrade > 0:
        missions.append("🔲 Prova a rispondere con tono calmo in una conversazione accesa. (+10 P.A.)")
    if msg_count >= 8 and degrade <= 0:
        missions.append("**✅ Dai il buongiorno per prima.**")
    return missions[:3] if missions else ["Nessuna per oggi."]


def _build_profile_lines(archetype_metrics: dict[str, Any], *, fallback_metrics: dict[str, Any]) -> list[str]:
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
    return [
        f"**🔥 {agitator}% Agitatore** — quando il ritmo cresce, tendi a spingere la discussione.",
        f"**🌿 {pacifier}% Pacificatore** — in più momenti mantieni equilibrio e ascolto.",
    ]


def _build_advice_lines(metrics: dict[str, Any], *, channel_name: str) -> list[str]:
    lines: list[str] = []
    unique = int(metrics.get("unique_interactions", 0) or 0)
    degrade = int(metrics.get("degrade_events", 0) or 0)
    msg_count = int(metrics.get("msg_count", 0) or 0)
    if unique <= 2:
        lines.append(f"Per migliorare la tua aura potresti coinvolgere più persone in {channel_name}.")
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
) -> list[discord.Embed]:
    main = discord.Embed(
        title=f"✨ RESOCONTO AURA \"{aura_payload.username}\"",
        color=0x5865F2,
        description=f"🕒 {aura_payload.period_row}\n{aura_payload.period_label}",
    )
    main.add_field(
        name=f"✨ KARMA \"{aura_payload.server_name}\"",
        value=(
            f"{render_karma_bar(aura_payload.karma_server_percent)}\n"
            f"**PUNTI AURA TOTALI:** {aura_payload.server_points_total}\n"
            "Questi punti NON si resettano mai, sono accumulati dall’ingresso nel server.\n"
            "Il risultato riflette come si è mosso il tuo contributo nel periodo richiesto."
        ),
        inline=False,
    )
    main.add_field(
        name=f"✨ KARMA \"{aura_payload.channel_name}\"",
        value=(
            f"{render_karma_bar(aura_payload.karma_channel_percent)}\n"
            f"**PUNTI AURA CANALE:** {aura_payload.channel_points_month}\n"
            "Questi punti si resettano a fine mese.\n"
            "La stima mostra l’impatto locale nel canale del comando."
        ),
        inline=False,
    )
    main.add_field(
        name="📈 TREND",
        value=(
            f"• Nel server in generale: **{_direction_label(aura_payload.trend.server_direction)}**. {aura_payload.trend.server_comment}\n"
            f"• Nel \"{aura_payload.channel_name}\": **{_direction_label(aura_payload.trend.channel_direction)}**. {aura_payload.trend.channel_comment}"
        ),
        inline=False,
    )
    main.set_footer(text="Stima calcolata in loco. Può variare in base ai dati disponibili.")

    details_sections: list[tuple[str, str]] = []
    metrics = json.loads(aura_payload.metrics_json) if aura_payload.metrics_json else {}
    details_sections.append(("🕹️ PUNTEGGI", _compact_bullets(_score_lines(aura_payload.ledger, channel_name=aura_payload.channel_name), fallback="Nessun dato rilevante nel periodo.")))

    if "details.missions" in include_sections:
        details_sections.append(("📜 MISSIONI QUOTIDIANE", _compact_bullets(_build_missions(metrics, aura_payload.archetype_metrics), fallback="Nessuna per oggi.")))
    if "details.profile" in include_sections:
        details_sections.append(("👤 PROFILO PERSONALE", _compact_bullets(_build_profile_lines(aura_payload.archetype_metrics, fallback_metrics=metrics), fallback="Nessun dato rilevante nel periodo.")))
    if "details.advice" in include_sections:
        details_sections.append(("🧭 CONSIGLI PERSONALIZZATI", _compact_bullets(_build_advice_lines(metrics, channel_name=aura_payload.channel_name), fallback="Nessun dato rilevante nel periodo.")))
    if "details.metrics_aggregated" in include_sections:
        channel_metrics = json.loads(aura_payload.channel_metrics_json) if aura_payload.channel_metrics_json else {}
        metrics_lines = [
            f"volume messaggi: {int(metrics.get('msg_count', 0) or 0)}",
            f"interazioni uniche: {int(metrics.get('unique_interactions', 0) or 0)}",
            f"reply ricevute: {int(metrics.get('reply_received', 0) or 0)}",
            f"consistency/quality_counter: {int(metrics.get('quality_counter', 0) or 0)}",
            f"invigorate/degrade: {int(metrics.get('invigorate_events', 0) or 0)}/{int(metrics.get('degrade_events', 0) or 0)}",
            f"delta clima: {int(metrics.get('invigorate_events', 0) or 0) - int(metrics.get('degrade_events', 0) or 0)}",
            f"metriche server: msg={int(metrics.get('msg_count', 0) or 0)} unique={int(metrics.get('unique_interactions', 0) or 0)}",
            f"metriche canale: msg={int(channel_metrics.get('msg_count', 0) or 0)} unique={int(channel_metrics.get('unique_interactions', 0) or 0)}",
            f"trend precedente vs attuale: {aura_payload.trend.server_delta:+d}/{aura_payload.trend.channel_delta:+d}",
        ]
        details_sections.append((":bricks: METRICHE AGGREGATE", _compact_bullets(metrics_lines, fallback="Nessun dato rilevante nel periodo.")))

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
        embed = discord.Embed(title=f"🗒️ DETTAGLI AURA — \"{tier_label}\" (Pag {page_idx}/{total_pages})", color=0x2F3136)
        for name, value in chunk:
            for part_idx, piece in enumerate(_split_field_chunks(value, 1024)):
                embed.add_field(name=name if part_idx == 0 else f"{name} (cont.)", value=piece, inline=False)
        embed.set_footer(text="Dati elaborati in loco. Eventuali imprecisioni sono possibili.")
        details.append(embed)

    embeds = [main, *details]
    sanitized = _ensure_embed_limits(embeds, max_chars=MAX_EMBED_CHARS)
    final: list[discord.Embed] = []
    for emb in sanitized:
        if _estimate_embed_size(emb) <= MAX_EMBED_CHARS:
            final.append(emb)
    return final
