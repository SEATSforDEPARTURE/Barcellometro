from __future__ import annotations

import json
from dataclasses import dataclass

import discord



def render_karma_bar(percent: int) -> str:
    value = max(0, min(100, int(percent)))
    width = 13
    cursor_idx = int(round((value / 100) * (width - 1)))
    cells = ["━"] * width
    cells[cursor_idx] = "🟣"
    return f"😈{''.join(cells)}😇  {value}%"


@dataclass
class AuraRenderPayload:
    period_label: str
    karma_percent: int
    metrics_json: str
    ledger: list[dict[str, int | str]]
    archetype_metrics: dict[str, object]


def _bullets(lines: list[str]) -> str:
    clean = [line.strip() for line in lines if str(line or "").strip()]
    if not clean:
        return "• Nessun dato"
    return "\n".join(f"• {line}" for line in clean)


def _status_label(karma: int) -> str:
    if karma >= 67:
        return "🟢 POSITIVA"
    if karma >= 34:
        return "🟡 BILANCIATA"
    return "🔴 IN CALO"


def build_aura_embeds(
    *,
    profile_name: str,
    aura_payload: AuraRenderPayload,
    include_sections: list[str],
    details_title_prefix: str,
    details_embeds_max: int,
) -> list[discord.Embed]:
    karma = int(aura_payload.karma_percent)
    base_metrics = json.loads(aura_payload.metrics_json) if aura_payload.metrics_json else {}
    title = "✨ RESOCONTO AURA 😇/😈 — SERVER"
    header_lines = [
        f"**Periodo**\n{aura_payload.period_label}",
        f"**Stato**\n{_status_label(karma)}",
    ]
    main = discord.Embed(
        title=title,
        description="\n\n".join(header_lines),
        color=0x5865F2,
    )
    main.add_field(name="KARMA SERVER", value=render_karma_bar(karma), inline=False)
    main.add_field(name="NARRATIVA", value="Trend locale calcolato con metriche di attività e impatto comunità.", inline=False)

    section_map: dict[str, tuple[str, str]] = {
        "details.score_breakdown": (
            "SCORE BREAKDOWN",
            _bullets([f"{item['reason_code']}: {int(item['total']):+d}" for item in aura_payload.ledger[:8]]),
        ),
        "details.metrics_basic": (
            "METRICHE BASE",
            _bullets(
                [
                    f"Volume: {base_metrics.get('msg_count', 0)}",
                    f"Diversity: {base_metrics.get('unique_interactions', 0)}",
                    f"Influence: {base_metrics.get('reply_received', 0)}",
                    f"Consistency: {base_metrics.get('quality_counter', 0)}",
                ]
            ),
        ),
        "details.metrics_advanced": (
            "METRICHE AVANZATE",
            _bullets(
                [
                    f"Monopoly: {max(0, 100 - int(base_metrics.get('unique_interactions', 0) or 0))}",
                    f"Replies/msg: {base_metrics.get('reply_received', 0)}/{max(1, int(base_metrics.get('msg_count', 1) or 1))}",
                    f"Climate delta: {int(base_metrics.get('invigorate_events', 0) or 0) - int(base_metrics.get('degrade_events', 0) or 0)}",
                ]
            ),
        ),
        "details.flags_mod": ("FLAG MOD", "• Nessun flag sensibile esposto in v1."),
        "details.missions": (
            "MISSIONI",
            _bullets([
                "Rispondi a 3 utenti nuovi",
                "Mantieni tono costruttivo",
                "Contribuisci in 2 canali",
            ]),
        ),
        "details.interactions_top": ("TOP INTERAZIONI", "• Classifica interazioni disponibile in v1.1"),
        "details.topics": (
            "INSIGHTS",
            _bullets([str(x) for x in (aura_payload.archetype_metrics.get("insights", []) if isinstance(aura_payload.archetype_metrics, dict) else [])[:3]]),
        ),
    }

    selected_sections = [section for section in include_sections if section.startswith("details.") and section in section_map]
    detail_items = [section_map[section] for section in selected_sections]
    details: list[discord.Embed] = []
    page_size = 4
    max_pages = max(0, details_embeds_max)
    for page_idx in range(max_pages):
        start = page_idx * page_size
        end = start + page_size
        chunk = detail_items[start:end]
        if not chunk:
            break
        details_embed = discord.Embed(
            title=f"{details_title_prefix.upper()} (Pag {page_idx + 1}/{max_pages}) — {profile_name.upper()}",
            color=0x2F3136,
        )
        for field_name, field_value in chunk:
            details_embed.add_field(name=field_name, value=field_value, inline=False)
        details.append(details_embed)

    return [main, *details]
