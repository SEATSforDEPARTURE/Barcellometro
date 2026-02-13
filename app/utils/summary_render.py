from __future__ import annotations

import logging
from typing import Any, Callable

import discord

from app.services.summary import SummaryImpact, SummaryItem, SummaryQuote, SummaryResult
from app.utils.embed_limits import (
    MAX_EMBED_CHARS,
    _clone_embed_shell,
    _ensure_embed_limits,
    _estimate_embed_size,
    _split_field_chunks,
)

logger = logging.getLogger(__name__)
MOMENTS_FIELD_NAME = "📌 MOMENTI SALIENTI"


def _truncate_text(s: str | None, limit: int) -> str:
    if s is None:
        return ""
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)] + "…"


def _split_lines_into_field_values(lines: list[str], limit: int = 1024) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for raw in lines:
        line = str(raw or "")
        if not line:
            continue
        line_len = len(line) + (1 if current else 0)
        if current and current_len + line_len > limit:
            chunks.append("\n".join(current))
            current = [line]
            current_len = len(line)
            continue
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def build_summary_detail_embeds(
    *,
    profile: str,
    summary: SummaryResult,
    include_names: bool,
    include_date_in_time: bool,
    guild_id: int,
    channel_id: int,
    name_map: dict[str, str],
    moment_primary: dict[int, str | None],
    quote_primary: dict[int, str | None],
    dynamic_primary: dict[int, str | None],
    impact_primary: dict[int, str | None],
    moment_display: dict[int, str | None],
    quote_display: dict[int, str | None],
    dynamic_names: dict[int, list[str]],
    quote_texts: dict[int, str | None],
    privacy_intervals: list[tuple[str, str]] | None,
    privacy_disclaimer_lines: list[str] | None,
    metrics_report: str | None,
    extra_sections: list[tuple[str, str, int]] | None,
    tier_label: str,
    tier_config: dict[str, Any],
    details_color: int,
    req_id: str,
    format_moment_line: Callable[..., str],
    format_quote_line: Callable[..., str],
    format_dynamic_line: Callable[..., str],
    format_impact_line: Callable[..., str],
    format_bullets: Callable[[list[str]], str],
) -> list[discord.Embed]:
    sections_map: dict[str, list[tuple[str, str, int]]] = {}
    has_privacy_gaps = bool(privacy_intervals)
    privacy_notice_line = "🔒 Alcuni contenuti sono stati omessi per privacy."
    privacy_empty_line = "🔒 Contenuto omesso per privacy."

    themes_value = ", ".join(summary.themes) if summary.themes else "Nessun tema rilevato."
    sections_map["themes"] = [("🏷️ TEMI", themes_value, 1)]

    moment_lines = [
        format_moment_line(
            moment=moment,
            guild_id=guild_id,
            channel_id=channel_id,
            include_names=include_names,
            display_name=moment_display.get(id(moment)),
            link_limit=1,
            primary_id=moment_primary.get(id(moment)),
            include_date=include_date_in_time,
        )
        for moment in summary.moments
    ]
    if moment_lines:
        moment_lines = moment_lines[:10]
        if privacy_disclaimer_lines:
            allowed = max(10 - len(privacy_disclaimer_lines), 0)
            moment_lines = moment_lines[:allowed] + privacy_disclaimer_lines
        sections_map["moments"] = [(MOMENTS_FIELD_NAME, format_bullets(moment_lines), 1)]

    quote_lines = [
        format_quote_line(
            quote=quote,
            guild_id=guild_id,
            channel_id=channel_id,
            primary_id=quote_primary.get(id(quote)),
            display_name=quote_display.get(id(quote)),
            text_override=quote_texts.get(id(quote)),
            include_date=include_date_in_time,
        )
        for quote in summary.quotes
    ]
    if has_privacy_gaps:
        quote_lines = quote_lines + [privacy_notice_line] if quote_lines else [privacy_empty_line]
    if quote_lines and profile in {"role2", "role3", "mod"}:
        sections_map["quotes"] = [("💬 FRASI ICONICHE", format_bullets(quote_lines), 2)]

    dynamic_lines = [
        format_dynamic_line(
            dynamic=dynamic,
            guild_id=guild_id,
            channel_id=channel_id,
            primary_id=dynamic_primary.get(id(dynamic)),
            include_names=include_names,
            display_names=dynamic_names.get(id(dynamic), []),
            include_date=include_date_in_time,
        )
        for dynamic in summary.dynamics
    ]
    if has_privacy_gaps:
        dynamic_lines = dynamic_lines + [privacy_notice_line] if dynamic_lines else [privacy_empty_line]
    if dynamic_lines and profile in {"role3", "mod"}:
        sections_map["dynamics"] = [("🔁 DINAMICHE INTERESSANTI", format_bullets(dynamic_lines), 2)]

    if profile == "mod":
        if summary.degrade:
            degrade_lines = [
                format_impact_line(
                    impact=impact,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    display_name=name_map.get(impact.author_id or ""),
                    link_limit=1,
                    prefix="🔥",
                    primary_id=impact_primary.get(id(impact)),
                    include_date=include_date_in_time,
                )
                for impact in summary.degrade
            ]
            sections_map["impact"] = [("🔥 CHI DEGRADA", format_bullets(degrade_lines), 3)]
        if summary.invigorate:
            inv_lines = [
                format_impact_line(
                    impact=impact,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    display_name=name_map.get(impact.author_id or ""),
                    link_limit=1,
                    prefix="🌿",
                    primary_id=impact_primary.get(id(impact)),
                    include_date=include_date_in_time,
                )
                for impact in summary.invigorate
            ]
            sections_map.setdefault("impact", []).append(("🌿 CHI RINVIGORISCE", format_bullets(inv_lines), 3))
        if summary.advice:
            sections_map["advice"] = [("🧭 CONSIGLI PERSONALIZZATI", format_bullets(summary.advice), 3)]
        if metrics_report:
            sections_map["metrics"] = [("🧱 METRICHE AGGREGATE", "Dettagli completi nel file allegato.", 3)]

    if extra_sections:
        sections_map["extra"] = extra_sections

    note_by_profile = {
        "role1": "🔒 Per un riassunto più approfondito e le frasi iconiche, passa a PRO o a PRO MAX per vedere anche le dinamiche.",
        "role2": "🔒 Per vedere anche le dinamiche interessanti passa a PRO MAX.",
    }
    if profile in note_by_profile:
        sections_map["note"] = [("📌 NOTE", note_by_profile[profile], 3)]

    section_order = tier_config.get("sections") or list(sections_map.keys())
    sections: list[tuple[str, str, int]] = []
    for section_id in section_order:
        sections.extend(sections_map.get(section_id, []))
    for tail in ("extra", "note"):
        if tail in sections_map and tail not in section_order:
            sections.extend(sections_map[tail])

    embeds: list[discord.Embed] = []
    groups = sorted({grp for _, _, grp in sections})

    def build_shell() -> discord.Embed:
        e = discord.Embed(title=f"🗒️ DETTAGLI RIASSUNTO — {tier_label}", color=details_color)
        e.set_footer(text="Barcellometro")
        return e

    def chunk_sections(section_list: list[tuple[str, str, int]]) -> list[discord.Embed]:
        out: list[discord.Embed] = []
        current = build_shell()
        for name, value, _ in section_list:
            pieces = _split_lines_into_field_values(value.split("\n"), 1024) if name == MOMENTS_FIELD_NAME else _split_field_chunks(value, 1024)
            for idx, piece in enumerate(pieces):
                field_name = name if idx == 0 else f"{name} (cont.)"
                candidate = _clone_embed_shell(current)
                for existing in current.fields:
                    candidate.add_field(name=existing.name, value=existing.value, inline=existing.inline)
                candidate.add_field(name=_truncate_text(field_name, 256), value=_truncate_text(piece, 1024), inline=False)
                if _estimate_embed_size(candidate) >= MAX_EMBED_CHARS or len(candidate.fields) > 25:
                    if current.fields:
                        out.append(current)
                    current = build_shell()
                    current.add_field(name=_truncate_text(field_name, 256), value=_truncate_text(piece, 1024), inline=False)
                else:
                    current = candidate
        if current.fields:
            out.append(current)
        return out

    if len(groups) <= 1:
        embeds = chunk_sections(sections)
    else:
        for group in groups:
            group_sections = [item for item in sections if item[2] == group]
            embeds.extend(chunk_sections(group_sections))

    embeds = _ensure_embed_limits(embeds, max_chars=MAX_EMBED_CHARS)
    total = max(len(embeds), 1)
    for idx, embed in enumerate(embeds, start=1):
        embed.title = f"🗒️ DETTAGLI RIASSUNTO — {tier_label} (Pag {idx}/{total})"
    return embeds
