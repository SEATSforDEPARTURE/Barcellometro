from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import discord

from app.services.activity_insights import ChannelActivityDetails, UserActivityEntry

ROME_TZ = ZoneInfo("Europe/Rome")


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


def _format_active_row(user: UserActivityEntry, *, guild_id: str, channel_id: str, reference_ts: str) -> str:
    peak_part = "picco: —"
    if user.peak_count > 0 and user.peak_hour_ts:
        peak_part = f"picco: {user.peak_count} msg alle {_fmt_ts(user.peak_hour_ts)}"
    elif user.peak_count == 0:
        peak_part = "picco: 0"

    last_ts = user.last_ts_in_range
    last_mid = user.last_message_id_in_range
    if last_ts:
        label = _fmt_ts(last_ts)
        url = _jump_link(guild_id, channel_id, last_mid)
        if url:
            last_part = f"ultimo: [{label}]({url}) — {_human_delta(last_ts, reference_ts)}"
        else:
            last_part = f"ultimo: {label} — {_human_delta(last_ts, reference_ts)}"
    else:
        last_part = "ultimo: —"
    return f"<@{user.user_id}> — {user.count_in_range} msg | {peak_part} | {last_part}"


def _format_inactive_row(user: UserActivityEntry, *, guild_id: str, channel_id: str, reference_ts: str) -> str:
    peak_part = "picco: —"
    if user.peak_count > 0 and user.peak_hour_ts:
        peak_part = f"picco: {user.peak_count} msg alle {_fmt_ts(user.peak_hour_ts)}"
    elif user.peak_count == 0:
        peak_part = "picco: 0"

    if user.count_in_range > 0 and user.last_ts_in_range:
        label = _fmt_ts(user.last_ts_in_range)
        url = _jump_link(guild_id, channel_id, user.last_message_id_in_range)
        if url:
            last_part = f"ultimo: [{label}]({url}) — {_human_delta(user.last_ts_in_range, reference_ts)}"
        else:
            last_part = f"ultimo: {label} — {_human_delta(user.last_ts_in_range, reference_ts)}"
        return f"<@{user.user_id}> — {user.count_in_range} msg | {peak_part} | {last_part}"

    if user.last_ts_channel:
        label = _fmt_ts(user.last_ts_channel)
        url = _jump_link(guild_id, channel_id, user.last_message_id_channel)
        if url:
            last_channel = f"ultimo nel canale: [{label}]({url}) — {_human_delta(user.last_ts_channel, reference_ts)}"
        else:
            last_channel = f"ultimo nel canale: {label} — {_human_delta(user.last_ts_channel, reference_ts)}"
        return f"<@{user.user_id}> — nel periodo: 0 msg | {peak_part} | {last_channel}"

    return f"<@{user.user_id}> — nel periodo: 0 msg | {peak_part} | ultimo nel canale: mai visto"


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
        title=f"🗣️ STATO ATTIVITÀ “#{channel_name}”",
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

    details_embed = discord.Embed(title="📄 DETTAGLI ATTIVITÀ — Staff", color=discord.Color.dark_grey())
    details_embed.add_field(name="📌 STATISTICHE CANALE", value="\n".join(details.stats_lines) or "n/d", inline=False)
    details_embed.add_field(name="📈 TREND", value=details.score.trend_text, inline=False)

    top_lines = [
        _format_active_row(item, guild_id=guild_id, channel_id=channel_id, reference_ts=reference_ts)
        for item in details.top_active_users
    ] or ["• Nessun dato"]
    details_embed.add_field(name="🏆 UTENTI PIÙ ATTIVI", value="\n".join(top_lines), inline=False)

    inactive_lines = [
        _format_inactive_row(item, guild_id=guild_id, channel_id=channel_id, reference_ts=reference_ts)
        for item in details.inactive_users
    ] or ["• Nessun inattivo rilevante"]
    details_embed.add_field(name="💤 UTENTI INATTIVI", value="\n".join(inactive_lines), inline=False)
    details_embed.add_field(name="💡 CONSIGLI", value="\n".join(f"• {line}" for line in details.advice_bullets), inline=False)
    details_embed.set_footer(text="Barcellometro")
    return [status, details_embed]
