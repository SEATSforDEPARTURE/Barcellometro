from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from zoneinfo import ZoneInfo

import discord

from app.services.barcello import BarcelloResult
from app.services.summary import SummaryItem, SummaryQuote, SummaryResult
from app.utils.embed_limits import normalize_embeds_for_discord

ROME_TZ = ZoneInfo("Europe/Rome")


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

    status_embed = discord.Embed(
        title=f"📊 RESOCONTO GIORNALIERO — #{channel_name}",
        description=f"🕒 **Ultime 24 ore**\n\n**{emoji} ALLERTA {alert_label}**\nAnalisi toni del giorno: {tones_line}",
        color=embed_color,
    )
    health_bar = _render_health_bar(barcello_status.score, emoji)
    status_embed.add_field(name="🫀 PUNTI SALUTE", value=f"{health_bar} ({barcello_status.score}/100)", inline=False)
    status_embed.set_footer(text="Barcellometro")

    details_embed = discord.Embed(title="🗒️ DETTAGLI", color=0x95A5A6)
    details_embed.set_footer(text="Barcellometro")

    themes_value = ", ".join(summary_result.themes) if summary_result.themes else "Nessun tema rilevato."
    details_embed.add_field(name="🏷️ TEMI", value=themes_value, inline=False)

    moment_lines = [_moment_line(moment=it, guild_id=guild_id, channel_id=channel_id, message_index=message_index) for it in summary_result.moments]
    if moment_lines:
        details_embed.add_field(name="📌 MOMENTI SALIENTI", value="\n".join(moment_lines[:10]), inline=False)

    quote_lines = [_quote_line(quote=it, guild_id=guild_id, channel_id=channel_id, message_index=message_index) for it in summary_result.quotes]
    if quote_lines:
        details_embed.add_field(name="💬 FRASI ICONICHE", value="\n".join(quote_lines[:6]), inline=False)

    dynamic_lines = [_dynamic_line(dynamic=it, guild_id=guild_id, channel_id=channel_id, message_index=message_index) for it in summary_result.dynamics]
    if dynamic_lines:
        details_embed.add_field(name="🔁 DINAMICHE INTERESSANTI", value="\n".join(dynamic_lines[:6]), inline=False)

    advice_value = "\n".join(f"• {line}" for line in advice_bullets if str(line).strip())
    if advice_value:
        details_embed.add_field(name="🧭 I CONSIGLI DEL BARCELLOMETRO", value=advice_value, inline=False)

    proverbio_value = str(proverbio or "").strip()
    if proverbio_value:
        details_embed.add_field(name="🍀 PROVERBIO DEL GIORNO", value=proverbio_value, inline=False)

    paged_details = normalize_embeds_for_discord([details_embed])
    total = len(paged_details)
    for idx, embed in enumerate(paged_details, start=1):
        embed.title = f"🗒️ DETTAGLI (Pag {idx}/{total})"

    return [status_embed, *paged_details]
