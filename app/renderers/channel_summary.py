from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from zoneinfo import ZoneInfo

import discord

from app.services.barcello_service import BarcelloResult
from app.services.author import attach_author_meta, attach_author_meta_to_all
from app.services.embed_images import attach_embed_images_meta, attach_embed_images_meta_to_all
from app.services.footer import attach_footer_meta, attach_footer_meta_to_all
from app.services.content_summary_service import SummaryItem, SummaryResult
from app.domain.reporting.trend import render_trend_value
from app.plugins.commands_modular.time_windows import format_rolling_window_label, infer_rolling_window_request
from app.shared.discord.embed_body import format_standard_description, format_standard_field_name, format_standard_title

ROME_TZ = ZoneInfo("Europe/Rome")
MAX_FIELD_VALUE = 1024
MAX_EMBED_DESCRIPTION = 4096
MAX_FIELDS_PER_EMBED = 24

logger = logging.getLogger(__name__)

WEEKDAY_IT = {0: "Lunedì", 1: "Martedì", 2: "Mercoledì", 3: "Giovedì", 4: "Venerdì", 5: "Sabato", 6: "Domenica"}
MONTH_IT = {1: "Gennaio", 2: "Febbraio", 3: "Marzo", 4: "Aprile", 5: "Maggio", 6: "Giugno", 7: "Luglio", 8: "Agosto", 9: "Settembre", 10: "Ottobre", 11: "Novembre", 12: "Dicembre"}


@dataclass(frozen=True)
class MessageMeta:
    message_id: str
    ts: str | None
    author_id: str | None = None


@dataclass(frozen=True)
class QuoteRenderItem:
    message_id: str | None
    ts: str | None
    quote_text: str
    author_display: str | None


def _render_health_bar(score: int, color_emoji: str) -> str:
    bounded = max(0, min(100, int(score)))
    filled = int(round(bounded / 10))
    return f"{color_emoji * filled}{'⚪' * max(0, 10 - filled)}"


def _barcello_emoji_from_color(color: str | None) -> str:
    mapping = {
        "verde": "🟢",
        "giallo": "🟡",
        "rosso": "🔴",
        "nero": "⚫",
    }
    return mapping.get(str(color or "").strip().lower(), "⚪")


def _jump_link(guild_id: int, channel_id: int, message_id: str) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def _format_local_time(ts: str | None, *, multi_day: bool = False) -> str:
    if not ts:
        return "--:--"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return "--:--"
    if dt.tzinfo is None:
        return dt.strftime("%H:%M")
    return dt.astimezone(ROME_TZ).strftime("%d/%m %H:%M" if multi_day else "%H:%M")


def format_time_link(guild_id: int, channel_id: int, message_id: str | None, ts: str | None, *, multi_day: bool = False) -> str:
    hhmm = _format_local_time(ts, multi_day=multi_day)
    if message_id:
        return f"[**{hhmm}**]({_jump_link(guild_id, channel_id, message_id)})"
    return f"**{hhmm}**"


def format_day_label(dt_local: datetime) -> str:
    return f"{WEEKDAY_IT[dt_local.weekday()]}, {dt_local.day} {MONTH_IT[dt_local.month]} {dt_local.year}"


def format_window_header(*, period_label: str, start_dt: datetime, end_dt: datetime, requested_quantity: int | None = None, requested_unit: str | None = None) -> str:
    if period_label == "oggi":
        return f"**🗓️ Oggi. {format_day_label(end_dt)}**"
    if period_label == "ieri":
        return f"**🗓️ Ieri. {format_day_label(start_dt)}**"
    if period_label == "ultimi":
        qty = requested_quantity
        unit = requested_unit
        if qty is None:
            qty, unit = infer_rolling_window_request(start_dt, end_dt)
        title = format_rolling_window_label(qty, str(unit or "minuti"))
        return f"**🗓️ {title}\n{start_dt.strftime('%d/%m/%Y %H:%M')} → {end_dt.strftime('%d/%m/%Y %H:%M')}**"
    return f"**🗓️ {start_dt.strftime('%d/%m/%Y %H:%M')} → {end_dt.strftime('%d/%m/%Y %H:%M')}**"


def _as_hashtag(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    return clean if clean.startswith("#") else f"#{clean}"


def _resolve_message_meta(message_ids: Iterable[str], message_index: dict[str, MessageMeta]) -> MessageMeta | None:
    for mid in message_ids:
        key = str(mid or "").strip()
        if key and (resolved := message_index.get(key)):
            return resolved
    return None


def _split_field_value(text: str, limit: int = MAX_FIELD_VALUE) -> list[str]:
    raw = str(text or "")
    if not raw:
        return [" "]
    if len(raw) <= limit:
        return [raw]
    lines = raw.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        ln = str(line)
        if len(ln) > limit:
            ln = ln[: max(1, limit - 1)] + "…"
        candidate_len = len(ln) + (1 if current else 0)
        if current and current_len + candidate_len > limit:
            chunks.append("\n".join(current))
            current = [ln]
            current_len = len(ln)
        else:
            current.append(ln)
            current_len += candidate_len
    if current:
        chunks.append("\n".join(current))
    return chunks or [" "]


def _standard_field_name(name: str) -> str:
    raw = str(name or "").strip()
    for emoji in ("🏷️", "📌", "💬", "🔁", "👥", "🧭", "🍀", "🫀", "📈"):
        if raw.startswith(f"{emoji} "):
            return format_standard_field_name(raw[len(emoji)+1:].strip(), emoji=emoji)
    return format_standard_field_name(raw)


def _window_header_to_narrative_period(window_header: str) -> str:
    clean = str(window_header or "").strip()
    if clean.startswith("**") and clean.endswith("**"):
        clean = clean[2:-2].strip()
    clean = clean.replace("🗓️", "").strip()
    clean = re.sub(r"\s*\n\s*", " ", clean)
    return clean or "Periodo selezionato."


def _sanitize_barcello_commentary(line: str) -> str:
    clean = str(line or "").strip()
    clean = re.sub(r"\(\s*\d+\s*/\s*100\s*\)", "", clean)
    clean = re.sub(r"\s{2,}", " ", clean).strip(" ,.")
    return clean


def _rolling_period_to_italian(period_label: str) -> str:
    clean = re.sub(r"\([^)]*\)", "", str(period_label or "")).strip()
    match = re.match(r"(?i)^ultim[oaie]\s+(?:(\d+)\s+)?(minuto|minuti|ora|ore|giorno|giorni|settimana|settimane)\b", clean)
    if not match:
        return clean or "Nel periodo selezionato"
    qty = int(match.group(1) or "1")
    unit = match.group(2).lower()
    if qty == 1:
        singular_map = {
            "minuto": "Nell'ultimo minuto",
            "minuti": "Nell'ultimo minuto",
            "ora": "Nell'ultima ora",
            "ore": "Nell'ultima ora",
            "giorno": "Nell'ultimo giorno",
            "giorni": "Nell'ultimo giorno",
            "settimana": "Nell'ultima settimana",
            "settimane": "Nell'ultima settimana",
        }
        return singular_map.get(unit, "Nell'ultimo periodo")
    plural_map = {
        "minuto": "Negli ultimi",
        "minuti": "Negli ultimi",
        "giorno": "Negli ultimi",
        "giorni": "Negli ultimi",
        "ora": "Nelle ultime",
        "ore": "Nelle ultime",
        "settimana": "Nelle ultime",
        "settimane": "Nelle ultime",
    }
    return f"{plural_map.get(unit, 'Negli ultimi')} {qty} {unit}"


def _window_header_to_period_and_range(window_header: str) -> tuple[str, str | None]:
    clean = str(window_header or "").strip()
    if clean.startswith("**") and clean.endswith("**"):
        clean = clean[2:-2].strip()
    clean = clean.replace("🗓️", "").strip()
    clean = re.sub(r"\s*\n\s*", " ", clean)
    clean = re.sub(r"\s{2,}", " ", clean).strip()
    range_match = re.search(r"(\d{2}/\d{2}/\d{4} \d{2}:\d{2})\s*→\s*(\d{2}/\d{2}/\d{4} \d{2}:\d{2})", clean)
    range_text = f"{range_match.group(1)} → {range_match.group(2)}" if range_match else None
    if range_match:
        period_raw = clean[: range_match.start()].strip(" .")
        if not period_raw:
            return "Periodo selezionato", range_text
        if period_raw.lower().startswith("ultim"):
            return _rolling_period_to_italian(period_raw), range_text
        return period_raw, range_text
    period_raw = clean or "Periodo selezionato"
    return period_raw, None


def build_channel_summary_period_prefix(window_header: str, *, trailing_period: bool = True) -> str:
    period_text, range_text = _window_header_to_period_and_range(window_header)
    period_prefix = period_text.strip().rstrip(".")
    if range_text:
        return f"{period_prefix} ({range_text}){'.' if trailing_period else ''}"
    return f"{period_prefix}{'.' if trailing_period else ''}"


def _extract_climate_description(*, color_label: str, commentary: str) -> str:
    climate = _sanitize_barcello_commentary(commentary)
    climate = re.sub(r"(?i)\b(?:nel\s+)?periodo selezionato\b", "", climate)
    climate = re.sub(r"(?i)^il barcello è stat[oa]\s+", "", climate).strip(" ,.")
    climate = re.sub(rf"(?i)^{re.escape(color_label)}\s*,\s*", "", climate).strip(" ,.")
    climate = re.sub(r"(?i)^Nella giornata di(?: oggi| ieri)?\s+", "", climate).strip(" ,.")
    climate = re.sub(r"(?i)^Nel periodo selezionato\s+", "", climate).strip(" ,.")
    climate = re.sub(r"(?i)^il barcello è rimasto\s+", "", climate).strip(" ,.")
    climate = re.sub(r"(?i)^con un clima\s+", "", climate).strip(" ,.")
    climate = re.sub(r"(?i),?\s*con un clima\s+", " ", climate).strip(" ,.")
    climate = re.sub(r"(?i)\bclima\b", "", climate).strip(" ,.")
    climate = re.sub(r"(?i)\b(?:verde|giallo|rosso|nero)\b", "", climate).strip(" ,.")
    climate = re.sub(r"(?i)\bcomplessivamente\b", "", climate)
    climate = re.sub(r"\s{2,}", " ", climate).strip(" ,.")
    if not climate:
        climate = "monitorato dal Barcellometro"
    if climate.lower() == color_label.lower():
        climate = "coerente con questo andamento"
    return climate


def _build_channel_summary_overview_description(*, period_text: str, range_text: str | None, color_label: str, climate_description: str) -> str:
    period_segment = f"**{period_text}**"
    if range_text:
        period_segment += f" ({range_text})"
    return f"*{period_segment} il barcello è stato **{color_label}**, con un clima **{climate_description}**.*"

def _add_field_chunked(pages: list[discord.Embed], *, name: str, value: str, color: int) -> None:
    for idx, chunk in enumerate(_split_field_value(value, MAX_FIELD_VALUE)):
        field_name = _standard_field_name(name if idx == 0 else f"{name} (cont.)")
        if len(pages[-1].fields) >= MAX_FIELDS_PER_EMBED:
            pages.append(discord.Embed(title=format_standard_title("RESOCONTO CANALE · RIASSUNTO", emoji="📓"), color=color))
        pages[-1].add_field(name=field_name[:256], value=chunk[:MAX_FIELD_VALUE], inline=False)


def _moment_line(*, moment: SummaryItem, guild_id: int, channel_id: int, message_index: dict[str, MessageMeta], primary_id: str | None, barcello_status: BarcelloResult, multi_day: bool) -> str:
    ref = message_index.get(primary_id) if primary_id else _resolve_message_meta(moment.message_ids, message_index)
    ts = (ref.ts if ref else None) or moment.ts
    text = str(moment.text or "").replace("{AUTHOR}", "").strip() or "(nessun dettaglio)"
    emoji = _barcello_emoji_from_color(getattr(barcello_status, "color", None))
    score = getattr(barcello_status, "score", None)
    safe_score = int(score) if isinstance(score, int) or str(score).isdigit() else "--"
    return f"• {format_time_link(guild_id, channel_id, primary_id or (ref.message_id if ref else None), ts, multi_day=multi_day)} {emoji} **{safe_score}** — {text}"


def _quote_line(*, item: QuoteRenderItem, guild_id: int, channel_id: int, multi_day: bool) -> str:
    line = f"• {format_time_link(guild_id, channel_id, item.message_id, item.ts, multi_day=multi_day)} — “{item.quote_text}”"
    if item.author_display:
        line += f" — **{item.author_display}**"
    return line


def _dynamic_line(*, dynamic: SummaryItem, guild_id: int, channel_id: int, message_index: dict[str, MessageMeta], primary_id: str | None, display_names: list[str], multi_day: bool) -> str:
    ref = message_index.get(primary_id) if primary_id else _resolve_message_meta(dynamic.message_ids, message_index)
    ts = (ref.ts if ref else None) or dynamic.ts
    text = str(dynamic.text or "").replace("{AUTHOR}", "").strip() or "(nessun dettaglio)"
    line = f"• {format_time_link(guild_id, channel_id, primary_id or (ref.message_id if ref else None), ts, multi_day=multi_day)} — {text}"
    clean_names = [n for n in display_names if str(n or "").strip()]
    if clean_names:
        line += f" — Coinvolti: {', '.join([f'**{name}**' for name in clean_names])}"
    return line


def _bold_known_names(text: str, names: list[str]) -> str:
    out = str(text or "")
    for name in sorted({str(n).strip() for n in names if str(n).strip()}, key=len, reverse=True):
        if f"**{name}**" in out:
            continue
        escaped = re.escape(name)
        start_guard = r"(?<![0-9A-Za-zÀ-ÖØ-öø-ÿ_])" if re.match(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ_]", name[:1]) else ""
        end_guard = r"(?![0-9A-Za-zÀ-ÖØ-öø-ÿ_])" if re.match(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ_]", name[-1:]) else ""
        out = re.sub(rf"(?<!\*){start_guard}{escaped}{end_guard}(?!\*)", f"**{name}**", out)
    return out


def _bold_leading_actor(text: str, known_names: list[str] | None = None) -> str:
    line = str(text or "").strip()
    if not line:
        return line
    if known_names:
        line = _bold_known_names(line, known_names)
        if "**" in line:
            return line
    if line.startswith("**"):
        return line
    return re.sub(r"^([^\s].*?)(\s+(?:ha|è|si|con|nel|in)\b)", r"**\1**\2", line, count=1, flags=re.IGNORECASE)


def build_channel_summary_embeds(*, guild_id: int, channel_id: int, channel_name: str, barcello_status: BarcelloResult, barcello_line: str, summary_result: SummaryResult, message_index: dict[str, MessageMeta], advice_bullets: list[str], proverbio: str, window_header: str, moment_primary: dict[int, str | None], dynamic_primary: dict[int, str | None], dynamic_names: dict[int, list[str]], quote_render_items: list[QuoteRenderItem], moment_barcello: dict[int, BarcelloResult] | None = None, who_interacted_lines: list[str] | None = None, known_display_names: list[str] | None = None, trend_value: str | None = None, multi_day: bool = False, aura_embed: discord.Embed | None = None) -> list[discord.Embed]:
    color_label = (barcello_status.color or "nero").lower()
    color_map = {"verde": (0x2ECC71, "🟢", "VERDE"), "giallo": (0xF1C40F, "🟡", "GIALLA"), "rosso": (0xE74C3C, "🔴", "ROSSA"), "nero": (0x2F3136, "⚫", "NERA")}
    embed_color, emoji, alert_label = color_map.get(color_label, (0x2F3136, "⚫", color_label.upper()))
    period_text, range_text = _window_header_to_period_and_range(window_header)
    climate_description = _extract_climate_description(color_label=color_label, commentary=barcello_line)
    status_description = _build_channel_summary_overview_description(
        period_text=period_text,
        range_text=range_text,
        color_label=color_label,
        climate_description=climate_description,
    )
    status_embed = discord.Embed(
        title=format_standard_title("RESOCONTO CANALE · PANORAMICA", emoji="📓"),
        description=status_description,
        color=embed_color,
    )
    status_embed.add_field(name=format_standard_field_name("Punti salute", emoji="🫀"), value=f"{_render_health_bar(barcello_status.score, emoji)} ({barcello_status.score}/100)", inline=False)
    trend_text = trend_value or render_trend_value(barcello_status.trend)
    if trend_text:
        status_embed.add_field(name=format_standard_field_name("Trend", emoji="📈"), value=trend_text, inline=False)
    attach_footer_meta(status_embed, service_name="channel_summary", used_local_processing=True)
    attach_author_meta(status_embed, service_name="channel_summary", canonical_top_level_command="channelsummary")
    attach_embed_images_meta(status_embed, service_name="channel_summary")

    pages: list[discord.Embed] = [
        discord.Embed(
            title=format_standard_title("RESOCONTO CANALE · RIASSUNTO", emoji="📓"),
            description=format_standard_description("Andiamo a leggere cosa è successo..."),
            color=0x95A5A6,
        )
    ]
    themes = [_as_hashtag(theme) for theme in summary_result.themes if str(theme or "").strip()]
    _add_field_chunked(pages, name="🏷️ TEMI", value=", ".join(themes) if themes else "Nessun tema rilevato.", color=0x95A5A6)

    moments = [
        _moment_line(
            moment=it,
            guild_id=guild_id,
            channel_id=channel_id,
            message_index=message_index,
            primary_id=moment_primary.get(id(it)),
            barcello_status=(moment_barcello or {}).get(id(it), barcello_status),
            multi_day=multi_day,
        )
        for it in summary_result.moments[:8]
    ]
    if moments:
        _add_field_chunked(pages, name="📌 MOMENTI SALIENTI", value="\n".join(moments), color=0x95A5A6)

    quotes = [_quote_line(item=it, guild_id=guild_id, channel_id=channel_id, multi_day=multi_day) for it in quote_render_items[:5]]
    if quotes:
        _add_field_chunked(pages, name="💬 FRASI ICONICHE", value="\n".join(quotes), color=0x95A5A6)

    dynamics = [_dynamic_line(dynamic=it, guild_id=guild_id, channel_id=channel_id, message_index=message_index, primary_id=dynamic_primary.get(id(it)), display_names=dynamic_names.get(id(it), []), multi_day=multi_day) for it in summary_result.dynamics]
    dynamics = [_bold_known_names(line, dynamic_names.get(id(it), [])) for it, line in zip(summary_result.dynamics, dynamics)]
    if dynamics:
        _add_field_chunked(pages, name="🔁 DINAMICHE", value="\n".join(dynamics), color=0x95A5A6)

    who_lines = [f"• {_bold_leading_actor(line, known_display_names)}" for line in (who_interacted_lines or []) if str(line or "").strip()][:8]
    if who_lines:
        _add_field_chunked(pages, name="👥 INTERAZIONI", value="\n".join(who_lines), color=0x95A5A6)

    advice_value = "\n".join(f"• {line}" for line in advice_bullets if str(line).strip())
    if advice_value:
        _add_field_chunked(pages, name="🧭 I CONSIGLI DEL BARCELLOMETRO", value=advice_value, color=0x95A5A6)
    if proverbio.strip():
        _add_field_chunked(pages, name="🍀 PROVERBIO", value=proverbio.strip(), color=0x95A5A6)

    for embed in pages:
        embed.title = format_standard_title("RESOCONTO CANALE · RIASSUNTO", emoji="📓")
    attach_footer_meta_to_all(pages, service_name="channel_summary", used_local_processing=True)
    attach_author_meta_to_all(pages, service_name="channel_summary", canonical_top_level_command="channelsummary")
    attach_embed_images_meta_to_all(pages, service_name="channel_summary")

    if aura_embed is not None:
        attach_author_meta(aura_embed, service_name="channel_summary", canonical_top_level_command="channelsummary")
        attach_embed_images_meta(aura_embed, service_name="channel_summary")
        return [status_embed, *pages, aura_embed]

    return [status_embed, *pages]


def build_channel_summary_insufficient_data_embed(*, channel_name: str, window_header: str) -> discord.Embed:
    period_text = _window_header_to_narrative_period(window_header)
    embed = discord.Embed(
        title=format_standard_title("RESOCONTO CANALE · PANORAMICA", emoji="📓"),
        description=format_standard_description(f"{period_text}: dati insufficienti per completare il resoconto del canale nel periodo selezionato."),
        color=0x2F3136,
    )
    attach_footer_meta(embed, service_name="channel_summary", used_local_processing=True)
    attach_author_meta(embed, service_name="channel_summary", canonical_top_level_command="channelsummary")
    attach_embed_images_meta(embed, service_name="channel_summary")
    return embed
