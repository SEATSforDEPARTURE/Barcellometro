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


def _display_name_for_id(*, guild: discord.Guild, user_id: int) -> str:
    member = guild.get_member(user_id)
    if member is not None:
        if getattr(member, "display_name", None):
            return str(member.display_name)
        if getattr(member, "global_name", None):
            return str(member.global_name)
        if getattr(member, "name", None):
            return str(member.name)
    state = getattr(guild, "_state", None)
    cached_user = state.get_user(user_id) if state and hasattr(state, "get_user") else None
    if cached_user is not None:
        if getattr(cached_user, "global_name", None):
            return str(cached_user.global_name)
        if getattr(cached_user, "name", None):
            return str(cached_user.name)
    return f"ID {user_id}"


def _label_active_dm(*, user_id: int) -> str:
    return f"<@{user_id}>"


def _label_inactive_dm(*, guild: discord.Guild, user_id: int) -> str:
    return _display_name_for_id(guild=guild, user_id=user_id)




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

def _fmt_ts(ts: str | None, *, hour_bucket: bool = False) -> str:
    if not ts:
        return "—"
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(ROME_TZ)
    if hour_bucket:
        local = local.replace(minute=0, second=0, microsecond=0)
    return local.strftime("%d/%m %H:%M")


def _human_delta(ts: str | None, reference_ts: str | None) -> str:
    if not ts:
        return "n/d"
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if reference_ts:
        ref = datetime.fromisoformat(str(reference_ts).replace("Z", "+00:00"))
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
    else:
        ref = datetime.now(timezone.utc)
    secs = max(0, int((ref - dt).total_seconds()))
    if secs >= 86400:
        return f"{secs // 86400}g fa"
    if secs >= 3600:
        return f"{secs // 3600}h fa"
    return f"{max(1, secs // 60)}m fa"


def _jump_link(guild_id: str, channel_id: str, message_id: str | None) -> str | None:
    if not message_id:
        return None
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def _fmt_ts_with_link(ts: str | None, guild_id: str, channel_id: str, message_id: str | None, *, markdown: bool, hour_bucket: bool = False) -> str:
    label = _fmt_ts(ts, hour_bucket=hour_bucket)
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


def _peak_active(user: UserActivityEntry, guild_id: str, channel_id: str, *, include_peak_day: bool) -> str:
    if user.peak_count <= 0 or not user.peak_hour_ts:
        return "🔥 —"
    out = f"🔥 {_fmt_ts_with_link(user.peak_hour_ts, guild_id, channel_id, user.peak_message_id, markdown=True, hour_bucket=True)} ({user.peak_count} msg)"
    if include_peak_day and user.peak_day_date_local and user.peak_day_count > 0:
        out += f" | 📆 {user.peak_day_date_local} ({user.peak_day_count} msg)"
    return out


def _format_active_row(user: UserActivityEntry, *, guild_id: str, channel_id: str, reference_ts: str, include_peak_day: bool) -> str:
    first = _fmt_ts_with_link(user.last_ts_in_range, guild_id, channel_id, user.last_message_id_in_range, markdown=True)
    mention = _label_active_dm(user_id=user.user_id)
    return (
        f"• {first} {mention} — {user.count_in_range} msg | "
        f"{_peak_active(user, guild_id, channel_id, include_peak_day=include_peak_day)} | "
        f"🕒 {_human_delta(user.last_ts_in_range, reference_ts)}"
    )


def _format_inactive_row(user: UserActivityEntry, *, guild: discord.Guild, guild_id: str, channel_id: str, reference_ts: str) -> str:
    name = _label_inactive_dm(guild=guild, user_id=user.user_id)
    if user.last_ts_channel:
        first = _fmt_ts_with_link(user.last_ts_channel, guild_id, channel_id, user.last_message_id_channel, markdown=True)
        return f"• 🧊 {first} {name} — {user.count_in_range} msg | 🕒 {_human_delta(user.last_ts_channel, reference_ts)}"
    return f"• 🧊 (mai visto) {name} — 0 msg"


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
    for idx, chunk in enumerate(chunks, start=1):
        _ensure_field(embeds, f"{title} ({idx}/{len(chunks)})", chunk)


def _finalize_detail_titles(embeds: list[discord.Embed]) -> None:
    detail = [e for e in embeds if e.title.startswith("📄 DETTAGLI ATTIVITÀ — Staff")]
    if len(detail) <= 1:
        detail[0].title = "📄 DETTAGLI ATTIVITÀ — Staff"
        return
    for idx, emb in enumerate(detail, start=1):
        emb.title = f"📄 DETTAGLI ATTIVITÀ — Staff ({idx}/{len(detail)})"


def build_activity_details_txt(
    guild: discord.Guild,
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
    lines = [
        "BARCELLOMETRO — DETTAGLI ATTIVITÀ",
        f"Server: {guild_name} ({guild_id})",
        f"Canale: #{channel_name} ({channel_id})",
        f"Periodo: {label_periodo}",
        f"Range Europe/Rome: {_fmt_ts(start_ts)} -> {_fmt_ts(end_ts)}",
        f"Generato il: {datetime.now(ROME_TZ).strftime('%d/%m/%Y %H:%M')}",
        "",
        "SEZIONE A — TOP ATTIVI (tutti)",
    ]
    for user in details.top_active_users:
        name = _display_name_for_id(guild=guild, user_id=user.user_id)
        mention = f"<@{user.user_id}>"
        lines.append(f"{mention} ({name}, id={user.user_id}) — {user.count_in_range} msg | {_peak_active(user, guild_id, channel_id, include_peak_day=details.range_spans_multiple_days)}")
    lines.extend(["", "SEZIONE B — INATTIVI NEL PERIODO (tutti)"])
    for user in details.inactive_users:
        name = _display_name_for_id(guild=guild, user_id=user.user_id)
        mention = f"<@{user.user_id}>"
        if user.last_ts_channel:
            last = _fmt_ts_with_link(user.last_ts_channel, guild_id, channel_id, user.last_message_id_channel, markdown=False)
            lines.append(f"{mention} ({name}, id={user.user_id}) — {user.count_in_range} msg | ultimo: {last} | 🕒 {_human_delta(user.last_ts_channel, reference_ts)}")
        else:
            lines.append(f"{mention} ({name}, id={user.user_id}) — 0 msg | ultimo: mai visto")
    lines.append("")
    return "\n".join(lines)


def build_activity_dm_embeds(
    guild: discord.Guild,
    guild_id: str,
    channel_id: str,
    channel_name: str,
    label_periodo: str,
    details: ChannelActivityDetails,
    *,
    reference_ts: str,
) -> list[discord.Embed]:
    s = details.score
    status = discord.Embed(title=f"🗣️ STATO ATTIVITÀ “#{channel_name}”", color=_color_for_label(s.label))
    status.description = (
        f"🕒 **{label_periodo}**\n\n{s.emoji} **ATTIVITÀ {s.label}**\n"
        f"*Ritmo del canale valutato su volume, persone attive e continuità.*\n\n"
        f"🫀 **PUNTI ATTIVITÀ**\n{_bar(s.score, s.emoji)} **({s.score}/100)**\n*{s.trend_text}*"
    )
    status.set_footer(text="Barcellometro")

    detail = discord.Embed(title="📄 DETTAGLI ATTIVITÀ — Staff", color=discord.Color.dark_grey())
    detail.set_footer(text="Barcellometro")
    embeds = [detail]

    _add_chunked_field(embeds, "📌 STATISTICHE CANALE", details.stats_lines or ["n/d"])
    _add_chunked_field(embeds, "📈 TREND", [details.score.trend_text or "n/d"])

    top_lines = [
        _format_active_row(item, guild_id=guild_id, channel_id=channel_id, reference_ts=reference_ts, include_peak_day=details.range_spans_multiple_days)
        for item in details.top_active_users
    ]
    _add_chunked_field(embeds, "🏆 UTENTI PIÙ ATTIVI", _apply_limit(top_lines) if top_lines else ["• Nessun dato"])

    inactive_lines = [
        _format_inactive_row(item, guild=guild, guild_id=guild_id, channel_id=channel_id, reference_ts=reference_ts)
        for item in details.inactive_users
    ]
    _add_chunked_field(embeds, "💤 UTENTI INATTIVI", _apply_limit(inactive_lines) if inactive_lines else ["• Nessun inattivo rilevante"])

    _add_chunked_field(embeds, "💡 CONSIGLI", [f"• {line}" for line in details.advice_bullets] or ["• Nessun consiglio"])
    _finalize_detail_titles(embeds)
    return [status, *embeds]
