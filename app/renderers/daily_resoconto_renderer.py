from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from zoneinfo import ZoneInfo

import discord

from app.services.footer import attach_footer_meta, attach_footer_meta_to_all

from app.services.barcello import BarcelloResult
from app.services.summary import SummaryItem, SummaryResult
from app.domain.reporting.trend import render_trend_value

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


def _jump_link(guild_id: int, channel_id: int, message_id: str) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def _format_local_time_hhmm(ts: str | None) -> str:
    if not ts:
        return "--:--"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return "--:--"
    if dt.tzinfo is None:
        return dt.strftime("%H:%M")
    return dt.astimezone(ROME_TZ).strftime("%H:%M")


def format_time_link(guild_id: int, channel_id: int, message_id: str | None, ts: str | None) -> str:
    hhmm = _format_local_time_hhmm(ts)
    if message_id:
        return f"[**{hhmm}**]({_jump_link(guild_id, channel_id, message_id)})"
    return f"**{hhmm}**"


def format_day_label(dt_local: datetime) -> str:
    return f"{WEEKDAY_IT[dt_local.weekday()]}, {dt_local.day} {MONTH_IT[dt_local.month]} {dt_local.year}"


def _as_hashtag(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    return clean if clean.startswith("#") else f"#{clean}"


def _resolve_message_meta(message_ids: Iterable[str], message_index: dict[str, MessageMeta]) -> MessageMeta | None:
    for mid in message_ids:
        key = str(mid or "").strip()
        if not key:
            continue
        resolved = message_index.get(key)
        if resolved:
            return resolved
    return None


def _split_field_value(text: str, limit: int = MAX_FIELD_VALUE) -> list[str]:
    raw = str(text or "")
    if not raw:
        return [" "]
    lines = raw.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        ln = str(line)
        if len(ln) > limit:
            logger.info("daily_resoconto renderer truncating_overlong_line original_len=%s limit=%s", len(ln), limit)
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
    if len(chunks) > 1:
        logger.info("daily_resoconto renderer field chunked chunks=%s", len(chunks))
    return chunks or [" "]


def _add_field_chunked(pages: list[discord.Embed], *, name: str, value: str, color: int) -> None:
    chunks = _split_field_value(value, MAX_FIELD_VALUE)
    for idx, chunk in enumerate(chunks):
        field_name = name if idx == 0 else f"{name} (cont.)"
        if len(pages[-1].fields) >= MAX_FIELDS_PER_EMBED:
            logger.info("daily_resoconto renderer new_page reason=max_fields")
            pages.append(discord.Embed(title="🗒️ DETTAGLI", color=color))
        pages[-1].add_field(name=field_name[:256], value=chunk[:MAX_FIELD_VALUE], inline=False)


def _moment_line(*, moment: SummaryItem, guild_id: int, channel_id: int, message_index: dict[str, MessageMeta], primary_id: str | None) -> str:
    ref = message_index.get(primary_id) if primary_id else _resolve_message_meta(moment.message_ids, message_index)
    ts = (ref.ts if ref else None) or moment.ts
    text = str(moment.text or "").replace("{AUTHOR}", "").strip() or "(nessun dettaglio)"
    return f"• {format_time_link(guild_id, channel_id, primary_id or (ref.message_id if ref else None), ts)} — {text}"


def _quote_line(*, item: QuoteRenderItem, guild_id: int, channel_id: int) -> str:
    line = f"• {format_time_link(guild_id, channel_id, item.message_id, item.ts)} — “{item.quote_text}”"
    if item.author_display:
        line += f" — {item.author_display}"
    return line


def _dynamic_line(*, dynamic: SummaryItem, guild_id: int, channel_id: int, message_index: dict[str, MessageMeta], primary_id: str | None, display_names: list[str]) -> str:
    ref = message_index.get(primary_id) if primary_id else _resolve_message_meta(dynamic.message_ids, message_index)
    ts = (ref.ts if ref else None) or dynamic.ts
    text = str(dynamic.text or "").replace("{AUTHOR}", "").strip() or "(nessun dettaglio)"
    line = f"• {format_time_link(guild_id, channel_id, primary_id or (ref.message_id if ref else None), ts)} — {text}"
    clean_names = [n for n in display_names if str(n or "").strip()]
    if clean_names:
        line += f" — Coinvolti: {', '.join(clean_names)}"
    return line


def build_daily_resoconto_embeds(
    *,
    guild_id: int,
    channel_id: int,
    channel_name: str,
    barcello_status: BarcelloResult,
    barcello_line: str,
    summary_result: SummaryResult,
    message_index: dict[str, MessageMeta],
    advice_bullets: list[str],
    proverbio: str,
    day_label: str,
    moment_primary: dict[int, str | None],
    dynamic_primary: dict[int, str | None],
    dynamic_names: dict[int, list[str]],
    quote_render_items: list[QuoteRenderItem],
    who_interacted_lines: list[str] | None = None,
    trend_value: str | None = None,
) -> list[discord.Embed]:
    color_label = (barcello_status.color or "nero").lower()
    color_map = {"verde": (0x2ECC71, "🟢", "VERDE"), "giallo": (0xF1C40F, "🟡", "GIALLA"), "rosso": (0xE74C3C, "🔴", "ROSSA"), "nero": (0x2F3136, "⚫", "NERA")}
    embed_color, emoji, alert_label = color_map.get(color_label, (0x2F3136, "⚫", color_label.upper()))

    description = f"🗓️ **{day_label}**\n\n**{emoji} ALLERTA {alert_label}**\n{barcello_line}"
    if len(description) > MAX_EMBED_DESCRIPTION:
        logger.info("daily_resoconto renderer truncating_description original_len=%s", len(description))
        description = description[: MAX_EMBED_DESCRIPTION - 1] + "…"

    status_embed = discord.Embed(title=f"📊 RESOCONTO GIORNALIERO — #{channel_name}", description=description, color=embed_color)
    health_bar = _render_health_bar(barcello_status.score, emoji)
    status_embed.add_field(name="🫀 PUNTI SALUTE", value=f"{health_bar} ({barcello_status.score}/100)", inline=False)
    trend_text = trend_value or render_trend_value(barcello_status.trend)
    if trend_text:
        status_embed.add_field(name="📈 TREND", value=trend_text, inline=False)
    attach_footer_meta(status_embed, service_name="daily_resoconto", used_local_processing=True)

    pages: list[discord.Embed] = [discord.Embed(title="🗒️ DETTAGLI", color=0x95A5A6)]
    themes = [_as_hashtag(theme) for theme in summary_result.themes if str(theme or "").strip()]
    themes_value = ", ".join(themes) if themes else "Nessun tema rilevato."
    _add_field_chunked(pages, name="🏷️ TEMI", value=themes_value, color=0x95A5A6)

    moment_lines = [
        _moment_line(moment=it, guild_id=guild_id, channel_id=channel_id, message_index=message_index, primary_id=moment_primary.get(id(it)))
        for it in summary_result.moments[:8]
    ]
    if moment_lines:
        _add_field_chunked(pages, name="📌 MOMENTI SALIENTI", value="\n".join(moment_lines), color=0x95A5A6)

    quote_lines = [_quote_line(item=it, guild_id=guild_id, channel_id=channel_id) for it in quote_render_items[:5]]
    if quote_lines:
        _add_field_chunked(pages, name="💬 FRASI ICONICHE", value="\n".join(quote_lines), color=0x95A5A6)

    dynamic_lines = [
        _dynamic_line(
            dynamic=it,
            guild_id=guild_id,
            channel_id=channel_id,
            message_index=message_index,
            primary_id=dynamic_primary.get(id(it)),
            display_names=dynamic_names.get(id(it), []),
        )
        for it in summary_result.dynamics
    ]
    if dynamic_lines:
        _add_field_chunked(pages, name="🔁 DINAMICHE INTERESSANTI", value="\n".join(dynamic_lines), color=0x95A5A6)

    who_lines = [f"• {line}" for line in (who_interacted_lines or []) if str(line or "").strip()][:8]
    if who_lines:
        _add_field_chunked(pages, name="👥 CHI HA INTERAGITO OGGI", value="\n".join(who_lines), color=0x95A5A6)

    advice_value = "\n".join(f"• {line}" for line in advice_bullets if str(line).strip())
    if advice_value:
        _add_field_chunked(pages, name="🧭 I CONSIGLI DEL BARCELLOMETRO", value=advice_value, color=0x95A5A6)

    proverbio_value = str(proverbio or "").strip()
    if proverbio_value:
        _add_field_chunked(pages, name="🍀 PROVERBIO DEL GIORNO", value=proverbio_value, color=0x95A5A6)

    total = len(pages)
    for idx, embed in enumerate(pages, start=1):
        embed.title = f"🗒️ DETTAGLI (Pag {idx}/{total})"
    attach_footer_meta_to_all(pages, service_name="daily_resoconto", used_local_processing=True)

    return [status_embed, *pages]
