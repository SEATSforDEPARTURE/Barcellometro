from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import discord

from app.services.activity_insights import ChannelActivityDetails, UserActivityEntry

ROME_TZ = ZoneInfo("Europe/Rome")
MAX_LIST_ROWS = 10
FIELD_VALUE_MAX = 1024
FIELD_NAME_MAX = 256
CHUNK_SUFFIX = "… (vedi .txt)"
MAX_FIELDS_PER_EMBED = 25


def _bar(score: int, emoji: str) -> str:
    filled = max(0, min(10, int(round(max(0, min(score, 100)) / 10))))
    return f"{emoji * filled}{'⚪' * (10 - filled)}"


def _color_for_label(label: str) -> int:
    mapping = {
        "ASSENTE": 0x2F3136,
        "SCARSA": 0xE74C3C,
        "MEDIOCRE": 0xF1C40F,
        "INTENSA": 0x2ECC71,
    }
    return mapping.get(label, 0x95A5A6)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _fmt_ts(ts: str | None) -> str:
    dt = _parse_iso(ts)
    if not dt:
        return "—"
    return dt.astimezone(ROME_TZ).strftime("%d/%m %H:%M")


def _human_delta(ts: str | None, reference_ts: str | None) -> str:
    dt = _parse_iso(ts)
    ref = _parse_iso(reference_ts)
    if not dt:
        return "n/d"
    if ref is None:
        ref = datetime.now(timezone.utc)
    secs = max(0, int((ref - dt).total_seconds()))
    days = secs // 86400
    if days > 0:
        return f"{days}g fa"
    hours = secs // 3600
    if hours > 0:
        return f"{hours}h fa"
    minutes = max(1, secs // 60)
    return f"{minutes}m fa"


def _jump_link(guild_id: str, channel_id: str, message_id: str | None) -> str | None:
    if not message_id:
        return None
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def _fmt_ts_with_link(ts: str | None, guild_id: str, channel_id: str, message_id: str | None, *, markdown: bool) -> str:
    label = _fmt_ts(ts)
    url = _jump_link(guild_id, channel_id, message_id)
    if url:
        return f"[{label}]({url})" if markdown else f"{label} ({url})"
    return label


def _truncate_line(line: str, max_len: int, suffix: str) -> str:
    if len(line) <= max_len:
        return line
    if max_len <= len(suffix):
        return suffix[:max_len]
    return line[: max_len - len(suffix)].rstrip() + suffix


def _chunk_lines(lines: list[str], *, max_len: int = FIELD_VALUE_MAX, suffix: str = CHUNK_SUFFIX) -> list[str]:
    if not lines:
        return ["—"]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for raw in lines:
        line = _truncate_line(str(raw), max_len, suffix)
        add_len = len(line) + (1 if current else 0)
        if current and current_len + add_len > max_len:
            chunks.append("\n".join(current))
            current = [line]
            current_len = len(line)
            continue
        current.append(line)
        current_len += add_len

    if current:
        chunks.append("\n".join(current))
    return chunks


def _format_active_row(user: UserActivityEntry, *, guild_id: str, channel_id: str, reference_ts: str, markdown: bool) -> str:
    peak_part = f"picco: {user.peak_count} msg alle {_fmt_ts(user.peak_hour_ts)}" if user.peak_count > 0 else "picco: 0 @ —"
    last_part = "ultimo: —"
    if user.last_ts_in_range:
        linked = _fmt_ts_with_link(user.last_ts_in_range, guild_id, channel_id, user.last_message_id_in_range, markdown=markdown)
        last_part = f"ultimo: {linked} — {_human_delta(user.last_ts_in_range, reference_ts)}"
    return f"<@{user.user_id}> — {user.count_in_range} msg | {peak_part} | {last_part}"


def _format_inactive_row(user: UserActivityEntry, *, guild_id: str, channel_id: str, reference_ts: str, markdown: bool) -> str:
    peak_part = f"picco: {user.peak_count} msg alle {_fmt_ts(user.peak_hour_ts)}" if user.peak_count > 0 else "picco: 0 @ —"

    if user.count_in_range >= 1 and user.last_ts_in_range:
        linked = _fmt_ts_with_link(user.last_ts_in_range, guild_id, channel_id, user.last_message_id_in_range, markdown=markdown)
        last_part = f"ultimo nel periodo: {linked} — {_human_delta(user.last_ts_in_range, reference_ts)}"
        return f"<@{user.user_id}> — {user.count_in_range} msg nel periodo | {peak_part} | {last_part}"

    if user.last_ts_channel:
        linked = _fmt_ts_with_link(user.last_ts_channel, guild_id, channel_id, user.last_message_id_channel, markdown=markdown)
        last_part = f"ultimo nel canale: {linked} — {_human_delta(user.last_ts_channel, reference_ts)}"
        return f"<@{user.user_id}> — 0 msg nel periodo | {peak_part} | {last_part}"

    return f"<@{user.user_id}> — 0 msg nel periodo | {peak_part} | ultimo nel canale: mai visto"


def _format_active_row_compact(user: UserActivityEntry, *, guild_id: str, channel_id: str, reference_ts: str) -> str:
    last_part = "ultimo: —"
    if user.last_ts_in_range:
        linked = _fmt_ts_with_link(user.last_ts_in_range, guild_id, channel_id, user.last_message_id_in_range, markdown=True)
        last_part = f"ultimo: {linked} — {_human_delta(user.last_ts_in_range, reference_ts)}"
    return f"<@{user.user_id}> — {user.count_in_range} msg | {last_part} | picco: {user.peak_count}"


def _format_inactive_row_compact(user: UserActivityEntry, *, guild_id: str, channel_id: str, reference_ts: str) -> str:
    if user.count_in_range >= 1 and user.last_ts_in_range:
        linked = _fmt_ts_with_link(user.last_ts_in_range, guild_id, channel_id, user.last_message_id_in_range, markdown=True)
        return (
            f"<@{user.user_id}> — {user.count_in_range} msg nel periodo | "
            f"ultimo nel periodo: {linked} — {_human_delta(user.last_ts_in_range, reference_ts)} | picco: {user.peak_count}"
        )
    if user.last_ts_channel:
        linked = _fmt_ts_with_link(user.last_ts_channel, guild_id, channel_id, user.last_message_id_channel, markdown=True)
        return (
            f"<@{user.user_id}> — 0 msg nel periodo | "
            f"ultimo nel canale: {linked} — {_human_delta(user.last_ts_channel, reference_ts)} | picco: {user.peak_count}"
        )
    return f"<@{user.user_id}> — 0 msg nel periodo | ultimo nel canale: mai visto | picco: {user.peak_count}"


def _apply_limit(lines: list[str]) -> list[str]:
    if len(lines) <= MAX_LIST_ROWS:
        return lines
    return [*lines[:MAX_LIST_ROWS], f"… + altri {len(lines) - MAX_LIST_ROWS} utenti"]


def _ensure_field(embeds: list[discord.Embed], title_base: str, value: str) -> None:
    safe_value = value if len(value) <= FIELD_VALUE_MAX else _truncate_line(value, FIELD_VALUE_MAX, CHUNK_SUFFIX)
    if len(embeds[-1].fields) >= MAX_FIELDS_PER_EMBED:
        idx = len([e for e in embeds if e.title.startswith("📄 DETTAGLI ATTIVITÀ — Staff")]) + 1
        new_embed = discord.Embed(title=f"📄 DETTAGLI ATTIVITÀ — Staff ({idx}/?)", color=discord.Color.dark_grey())
        new_embed.set_footer(text="Barcellometro")
        embeds.append(new_embed)
    embeds[-1].add_field(name=title_base[:FIELD_NAME_MAX], value=safe_value, inline=False)


def _add_chunked_field(embeds: list[discord.Embed], title: str, lines: list[str]) -> None:
    chunks = _chunk_lines(lines)
    if len(chunks) == 1:
        _ensure_field(embeds, title, chunks[0])
        return
    total = len(chunks)
    for idx, chunk in enumerate(chunks, start=1):
        _ensure_field(embeds, f"{title} ({idx}/{total})", chunk)


def _finalize_detail_titles(embeds: list[discord.Embed]) -> None:
    detail_embeds = [e for e in embeds if e.title.startswith("📄 DETTAGLI ATTIVITÀ — Staff")]
    total = len(detail_embeds)
    if total <= 1:
        detail_embeds[0].title = "📄 DETTAGLI ATTIVITÀ — Staff"
        return
    for idx, embed in enumerate(detail_embeds, start=1):
        embed.title = f"📄 DETTAGLI ATTIVITÀ — Staff ({idx}/{total})"


def build_activity_details_txt(
    guild_name: str,
    guild_id: str,
    channel_name: str,
    channel_id: str,
    label_periodo: str,
    start_ts: str,
    end_ts: str,
    details: ChannelActivityDetails,
    *,
    reference_ts: str,
) -> str:
    start_local = _fmt_ts(start_ts)
    end_local = _fmt_ts(end_ts)
    generated = datetime.now(ROME_TZ).strftime("%d/%m/%Y %H:%M")
    lines: list[str] = [
        "BARCELLOMETRO — DETTAGLI ATTIVITÀ",
        f"Server: {guild_name} ({guild_id})",
        f"Canale: #{channel_name} ({channel_id})",
        f"Periodo: {label_periodo}",
        f"Range Europe/Rome: {start_local} -> {end_local}",
        f"Generato il: {generated}",
        "",
        "SEZIONE A — TOP ATTIVI (tutti)",
    ]
    for user in details.top_active_users:
        lines.append(_format_active_row(user, guild_id=guild_id, channel_id=channel_id, reference_ts=reference_ts, markdown=False))

    lines.extend(["", "SEZIONE B — INATTIVI NEL PERIODO (tutti)"])
    for user in details.inactive_users:
        lines.append(_format_inactive_row(user, guild_id=guild_id, channel_id=channel_id, reference_ts=reference_ts, markdown=False))
    lines.append("")
    return "\n".join(lines)


def build_activity_dm_embeds(
    guild_id: str,
    channel_id: str,
    channel_name: str,
    label_periodo: str,
    details: ChannelActivityDetails,
    *,
    reference_ts: str,
) -> list[discord.Embed]:
    s = details.score
    status = discord.Embed(
        title=f"🫛 STATO ATTIVITÀ “#{channel_name}”",
        color=_color_for_label(s.label),
    )
    status.description = (
        f"🕒 **{label_periodo}**\n\n"
        f"{s.emoji} **ATTIVITÀ {s.label}**\n"
        f"*Ritmo del canale valutato su volume, persone attive e continuità.*\n\n"
        f"🫀 **PUNTI ATTIVITÀ**\n"
        f"{_bar(s.score, s.emoji)} **({s.score}/100)**\n"
        f"*{s.trend_text}*"
    )
    status.set_footer(text="Barcellometro")

    detail_1 = discord.Embed(title="📄 DETTAGLI ATTIVITÀ — Staff", color=discord.Color.dark_grey())
    detail_1.set_footer(text="Barcellometro")
    detail_embeds = [detail_1]

    _add_chunked_field(detail_embeds, "📌 STATISTICHE CANALE", details.stats_lines or ["n/d"])
    _add_chunked_field(detail_embeds, "📈 TREND", [details.score.trend_text or "n/d"])

    all_top_lines = [
        _format_active_row_compact(item, guild_id=guild_id, channel_id=channel_id, reference_ts=reference_ts)
        for item in details.top_active_users
    ]
    _add_chunked_field(detail_embeds, "🏆 UTENTI PIÙ ATTIVI", _apply_limit(all_top_lines) if all_top_lines else ["• Nessun dato"])

    all_inactive_lines = [
        _format_inactive_row_compact(item, guild_id=guild_id, channel_id=channel_id, reference_ts=reference_ts)
        for item in details.inactive_users
    ]
    _add_chunked_field(
        detail_embeds,
        "💤 UTENTI INATTIVI",
        _apply_limit(all_inactive_lines) if all_inactive_lines else ["• Nessun inattivo rilevante"],
    )

    advice_lines = [f"• {line}" for line in details.advice_bullets] or ["• Nessun consiglio"]
    _add_chunked_field(detail_embeds, "💡 CONSIGLI", advice_lines)
    _finalize_detail_titles(detail_embeds)

    return [status, *detail_embeds]
