from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from zoneinfo import ZoneInfo

import discord

from app.services.barcello import BarcelloResult
from app.services.summary import SummaryItem, SummaryQuote, SummaryResult

ROME_TZ = ZoneInfo("Europe/Rome")
MAX_FIELD_VALUE = 1024
MAX_EMBED_DESCRIPTION = 4096
MAX_FIELDS_PER_EMBED = 24

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MessageMeta:
    message_id: str
    ts: str | None


def _render_health_bar(score: int, color_emoji: str) -> str:
    bounded = max(0, min(100, int(score)))
    filled = int(round(bounded / 10))
    return f"{color_emoji * filled}{'⚪' * max(0, 10 - filled)}"


def _jump_link(guild_id: int, channel_id: int, message_id: str) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def _format_local_time(ts: str | None) -> str:
    if not ts:
        return "--:--"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return "--:--"
    if dt.tzinfo is None:
        return dt.strftime("%d/%m %H:%M")
    return dt.astimezone(ROME_TZ).strftime("%d/%m %H:%M")


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
            logger.info(
                "daily_resoconto renderer truncating_overlong_line original_len=%s limit=%s",
                len(ln),
                limit,
            )
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


def _add_field_chunked(
    pages: list[discord.Embed],
    *,
    name: str,
    value: str,
    color: int,
) -> None:
    chunks = _split_field_value(value, MAX_FIELD_VALUE)
    for idx, chunk in enumerate(chunks):
        field_name = name if idx == 0 else f"{name} (cont.)"
        if len(pages[-1].fields) >= MAX_FIELDS_PER_EMBED:
            logger.info("daily_resoconto renderer new_page reason=max_fields")
            next_page = discord.Embed(title="🗒️ DETTAGLI", color=color)
            next_page.set_footer(text="Barcellometro")
            pages.append(next_page)
        pages[-1].add_field(name=field_name[:256], value=chunk[:MAX_FIELD_VALUE], inline=False)


def _moment_line(
    *,
    moment: SummaryItem,
    guild_id: int,
    channel_id: int,
    message_index: dict[str, MessageMeta],
) -> str:
    ref = _resolve_message_meta(moment.message_ids, message_index)
    text = str(moment.text or "").strip() or "(nessun dettaglio)"
    if ref:
        label = _format_local_time(ref.ts or moment.ts)
        return f"• [{label}]({_jump_link(guild_id, channel_id, ref.message_id)}) — {text}"
    return f"• {_format_local_time(moment.ts)} — {text}"


def _quote_line(
    *,
    quote: SummaryQuote,
    guild_id: int,
    channel_id: int,
    message_index: dict[str, MessageMeta],
) -> str:
    ref = _resolve_message_meta(quote.message_ids, message_index)
    text = str(quote.text or "").strip() or "(nessun testo)"
    if ref:
        label = _format_local_time(ref.ts or quote.ts)
        return f"• [{label}]({_jump_link(guild_id, channel_id, ref.message_id)}) — “{text}”"
    return f"• {_format_local_time(quote.ts)} — “{text}”"


def _dynamic_line(
    *,
    dynamic: SummaryItem,
    guild_id: int,
    channel_id: int,
    message_index: dict[str, MessageMeta],
) -> str:
    ref = _resolve_message_meta(dynamic.message_ids, message_index)
    text = str(dynamic.text or "").strip() or "(nessun dettaglio)"
    if ref:
        label = _format_local_time(ref.ts or dynamic.ts)
        return f"• [{label}]({_jump_link(guild_id, channel_id, ref.message_id)}) — {text}"
    return f"• {_format_local_time(dynamic.ts)} — {text}"


def build_daily_resoconto_embeds(
    *,
    guild_id: int,
    channel_id: int,
    channel_name: str,
    barcello_status: BarcelloResult,
    tones_line: str,
    summary_result: SummaryResult,
    message_index: dict[str, MessageMeta],
    advice_bullets: list[str],
    proverbio: str,
) -> list[discord.Embed]:
    color_label = (barcello_status.color or "nero").lower()
    color_map = {
        "verde": (0x2ECC71, "🟢", "VERDE"),
        "giallo": (0xF1C40F, "🟡", "GIALLA"),
        "rosso": (0xE74C3C, "🔴", "ROSSA"),
        "nero": (0x2F3136, "⚫", "NERA"),
    }
    embed_color, emoji, alert_label = color_map.get(color_label, (0x2F3136, "⚫", color_label.upper()))

    description = f"🕒 **Ultime 24 ore**\n\n**{emoji} ALLERTA {alert_label}**\nAnalisi toni del giorno: {tones_line}"
    if len(description) > MAX_EMBED_DESCRIPTION:
        logger.info(
            "daily_resoconto renderer truncating_description original_len=%s",
            len(description),
        )
        description = description[: MAX_EMBED_DESCRIPTION - 1] + "…"

    status_embed = discord.Embed(
        title=f"📊 RESOCONTO GIORNALIERO — #{channel_name}",
        description=description,
        color=embed_color,
    )
    health_bar = _render_health_bar(barcello_status.score, emoji)
    status_embed.add_field(name="🫀 PUNTI SALUTE", value=f"{health_bar} ({barcello_status.score}/100)", inline=False)
    status_embed.set_footer(text="Barcellometro")

    first_details = discord.Embed(title="🗒️ DETTAGLI", color=0x95A5A6)
    first_details.set_footer(text="Barcellometro")
    pages: list[discord.Embed] = [first_details]

    themes_value = ", ".join(summary_result.themes) if summary_result.themes else "Nessun tema rilevato."
    _add_field_chunked(pages, name="🏷️ TEMI", value=themes_value, color=0x95A5A6)

    moment_lines = [_moment_line(moment=it, guild_id=guild_id, channel_id=channel_id, message_index=message_index) for it in summary_result.moments[:8]]
    if moment_lines:
        _add_field_chunked(pages, name="📌 MOMENTI SALIENTI", value="\n".join(moment_lines), color=0x95A5A6)

    quote_lines = [_quote_line(quote=it, guild_id=guild_id, channel_id=channel_id, message_index=message_index) for it in summary_result.quotes[:5]]
    if quote_lines:
        _add_field_chunked(pages, name="💬 FRASI ICONICHE", value="\n".join(quote_lines), color=0x95A5A6)

    dynamic_lines = [_dynamic_line(dynamic=it, guild_id=guild_id, channel_id=channel_id, message_index=message_index) for it in summary_result.dynamics]
    if dynamic_lines:
        _add_field_chunked(pages, name="🔁 DINAMICHE INTERESSANTI", value="\n".join(dynamic_lines), color=0x95A5A6)

    advice_value = "\n".join(f"• {line}" for line in advice_bullets if str(line).strip())
    if advice_value:
        _add_field_chunked(pages, name="🧭 I CONSIGLI DEL BARCELLOMETRO", value=advice_value, color=0x95A5A6)

    proverbio_value = str(proverbio or "").strip()
    if proverbio_value:
        _add_field_chunked(pages, name="🍀 PROVERBIO DEL GIORNO", value=proverbio_value, color=0x95A5A6)

    total = len(pages)
    for idx, embed in enumerate(pages, start=1):
        embed.title = f"🗒️ DETTAGLI (Pag {idx}/{total})"

    return [status_embed, *pages]
