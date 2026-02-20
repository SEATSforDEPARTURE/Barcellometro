from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import discord

ITALIAN_WEEKDAYS = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
ITALIAN_MONTHS = [
    "Gennaio",
    "Febbraio",
    "Marzo",
    "Aprile",
    "Maggio",
    "Giugno",
    "Luglio",
    "Agosto",
    "Settembre",
    "Ottobre",
    "Novembre",
    "Dicembre",
]

COLOR_BY_EMOJI = {
    "🟢": 0x57F287,
    "🟡": 0xFEE75C,
    "🔴": 0xED4245,
    "⚫": 0x2F3136,
}


def _color_for_emoji(emoji: str) -> int:
    return COLOR_BY_EMOJI.get(emoji, 0x2F3136)


def _bar(score: int, emoji: str) -> str:
    filled = max(0, min(10, int(round(score / 10))))
    return f"{emoji * filled}{'⚪' * (10 - filled)}"


def _fmt_discord_ts(ts_iso: str | None) -> tuple[str, str]:
    if not ts_iso:
        return "n/d", "n/d"
    dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    unix_ts = int(dt.timestamp())
    return f"<t:{unix_ts}:d> <t:{unix_ts}:t>", f"<t:{unix_ts}:R>"


def _format_italian_date(reference_ts: str) -> str:
    dt = datetime.fromisoformat(reference_ts.replace("Z", "+00:00"))
    weekday = ITALIAN_WEEKDAYS[dt.weekday()]
    month = ITALIAN_MONTHS[dt.month - 1]
    return f"{weekday}, {dt.day} {month} {dt.year}"


def _fmt_duration_hhmm(seconds: int) -> str:
    total_minutes = max(0, seconds // 60)
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _truncate_field(value: str) -> str:
    return value if len(value) <= 1024 else value[:1021] + "..."


def _display_name(guild: discord.Guild, user_id: int) -> str:
    member = guild.get_member(user_id)
    return member.display_name if member else f"ID {user_id}"


def build_daily_activity_embeds(
    guild: discord.Guild,
    guild_name: str,
    channel_payloads: list[dict[str, Any]],
    *,
    server_summary: dict[str, Any],
    reference_ts: str,
) -> list[discord.Embed]:
    total_messages = sum(item["details"].score.messages_count for item in channel_payloads)
    continuity_server = max((item["details"].score.continuity_hours for item in channel_payloads), default=0)
    score_server = int(round(sum(item["details"].score.score for item in channel_payloads) / len(channel_payloads))) if channel_payloads else 0
    if score_server <= 20:
        server_emoji, server_label = "⚫", "ASSENTE"
    elif score_server <= 40:
        server_emoji, server_label = "🔴", "SCARSA"
    elif score_server <= 60:
        server_emoji, server_label = "🟡", "MEDIOCRE"
    else:
        server_emoji, server_label = "🟢", "INTENSA"

    prev_total_estimate = 0
    for item in channel_payloads:
        trend = item["details"].score.trend_text or ""
        if "% vs finestra precedente" in trend:
            try:
                pct = int(trend.split("(")[-1].split("%")[0])
                if pct != -100:
                    prev_total_estimate += int(round(item["details"].score.messages_count / (1 + (pct / 100))))
            except Exception:
                continue

    trend_server = "Messaggi stabili rispetto alla finestra precedente."
    if prev_total_estimate > 0:
        delta = int(round(((total_messages - prev_total_estimate) / prev_total_estimate) * 100))
        direction = "in crescita" if delta > 0 else "in calo" if delta < 0 else "stabili"
        trend_server = f"Messaggi {direction} ({delta:+d}% vs finestra precedente)."

    active_x = server_summary.get("active_non_bot", 0)
    total_y = server_summary.get("total_non_bot_members")
    total_y_label = str(total_y) if total_y is not None else "?"

    advice_pool: list[str] = []
    for item in channel_payloads:
        for row in item["details"].advice_bullets:
            if row not in advice_pool:
                advice_pool.append(row)
    if not advice_pool:
        advice_pool = ["Ritmo regolare: mantenete costanza e coinvolgimento nelle fasce orarie migliori."]

    overview = discord.Embed(
        title=f"🗣️ RESOCONTO ATTIVITÀ “{guild_name}”",
        color=_color_for_emoji(server_emoji),
        description=(
            f"**🗓️ {_format_italian_date(reference_ts)}**\n\n"
            f"{server_emoji} **ATTIVITÀ {server_label}**\n"
            "*Ritmo del server valutato su volume, persone attive e continuità.*\n\n"
            f"🫀 **PUNTI ATTIVITÀ**\n{_bar(score_server, server_emoji)} **({score_server}/100)**"
        ),
    )
    overview.add_field(name="📈 TREND", value=_truncate_field(trend_server), inline=False)
    overview.add_field(
        name="📌 STATISTICHE SERVER",
        value=_truncate_field(
            f"• Messaggi: **{total_messages}**\n"
            f"• Utenti attivi: **{active_x}/{total_y_label}**\n"
            f"• Continuità oraria: **{continuity_server}** ore con attività\n"
            f"• Canali monitorati: **{len(channel_payloads)}**"
        ),
        inline=False,
    )
    overview.add_field(
        name="💡 CONSIGLI",
        value=_truncate_field("\n".join(f"• {tip}" for tip in advice_pool[:4])),
        inline=False,
    )
    overview.set_footer(text="Barcellometro")

    embeds = [overview]
    for item in channel_payloads:
        dc = item["channel"]
        details = item["details"]
        s = details.score
        channel_name = getattr(dc, "name", "sconosciuto")
        b_raw = item.get("members_with_access")
        b_label = str(b_raw) if b_raw is not None else "?"
        stats_lines = [
            f"• Messaggi: **{s.messages_count}**",
            f"• Utenti attivi: **{item.get('active_non_bot', 0)}/{b_label}**",
            f"• Ora di picco: **{s.peak_hour_local:02d}:00**" if s.peak_hour_local is not None else "• Ora di picco: **n/d**",
            f"• Continuità oraria: **{s.continuity_hours}** ore con attività",
        ]
        if item.get("is_voice"):
            c = int(item.get("voice_sessions_count", 0))
            if c > 0:
                stats_lines.append(f"• Chiamate: **{c}** sessioni (Durata totale: **{_fmt_duration_hhmm(int(item.get('voice_total_seconds', 0)))}**) ")
            else:
                stats_lines.append("• Chiamate: **0**")

        embed = discord.Embed(
            title=f"📄 DETTAGLI ATTIVITÀ “#{channel_name}”",
            color=_color_for_emoji(s.emoji),
            description=(
                f"{s.emoji} **ATTIVITÀ {s.label}**\n"
                "*Ritmo del canale valutato su volume, persone attive e continuità.*\n\n"
                f"🫀 **PUNTI ATTIVITÀ**\n{_bar(s.score, s.emoji)} **({s.score}/100)**"
            ),
        )
        embed.add_field(name="📌 STATISTICHE CANALE", value=_truncate_field("\n".join(stats_lines)), inline=False)
        embed.add_field(name="📈 TREND", value=_truncate_field(s.trend_text or "n/d"), inline=False)
        embed.set_footer(text="Barcellometro")
        embeds.append(embed)

    return embeds


def build_daily_activity_details_txt(
    guild: discord.Guild,
    guild_name: str,
    channel_payloads: list[dict[str, Any]],
    *,
    server_summary: dict[str, Any],
    reference_ts: str,
) -> str:
    total_messages = sum(item["details"].score.messages_count for item in channel_payloads)
    active_x = server_summary.get("active_non_bot", 0)
    total_y = server_summary.get("total_non_bot_members")
    total_y_label = str(total_y) if total_y is not None else "?"
    trend_lines = [item["details"].score.trend_text for item in channel_payloads if item["details"].score.trend_text]
    trend_server = trend_lines[0] if trend_lines else "n/d"

    lines = [
        f"RESOCONTO ATTIVITÀ SERVER — {guild_name}",
        f"Data: {_format_italian_date(reference_ts)}",
        f"Finestra: 00:00 → {datetime.fromisoformat(reference_ts.replace('Z', '+00:00')).strftime('%H:%M')}",
        f"Tot messaggi: {total_messages}",
        f"Utenti attivi: {active_x}/{total_y_label}",
        f"Trend: {trend_server}",
        "",
    ]

    for item in channel_payloads:
        dc = item["channel"]
        details = item["details"]
        s = details.score
        channel_name = getattr(dc, "name", "sconosciuto")
        b_raw = item.get("members_with_access")
        b_label = str(b_raw) if b_raw is not None else "?"

        lines.append(f"==== #{channel_name} ====")
        lines.append(f"Messaggi: {s.messages_count}")
        lines.append(f"Utenti attivi: {item.get('active_non_bot', 0)}/{b_label}")
        lines.append(f"Trend: {s.trend_text}")

        if item.get("is_voice"):
            lines.append(f"Chiamate: {int(item.get('voice_sessions_count', 0))}")
            lines.append(f"Durata totale: {_fmt_duration_hhmm(int(item.get('voice_total_seconds', 0)))}")
            lines.append("Dettaglio chiamate:")
            voice_details = item.get("voice_details", [])
            if voice_details:
                lines.extend(voice_details)
            else:
                lines.append("- Nessuna sessione")

        lines.append("TOP UTENTI PIÙ ATTIVI (TOP 10)")
        for idx, user in enumerate(details.top_active_users[:10], start=1):
            last_abs, last_rel = _fmt_discord_ts(user.last_ts_in_range)
            peak_abs, _ = _fmt_discord_ts(user.peak_hour_ts)
            lines.append(
                f"{idx}) <@{user.user_id}> ({_display_name(guild, user.user_id)}) — {user.count_in_range} msg — ultimo {last_abs} {last_rel} — picco {peak_abs} ({user.peak_count} msg)"
            )

        lines.append("TOP UTENTI INATTIVI (TOP 10)")
        for idx, user in enumerate(details.inactive_users[:10], start=1):
            if user.last_ts_channel is None:
                lines.append(f"{idx}) {_display_name(guild, user.user_id)} — 0 msg — mai partecipato")
            else:
                last_abs, last_rel = _fmt_discord_ts(user.last_ts_channel)
                lines.append(f"{idx}) {_display_name(guild, user.user_id)} — 0 msg — ultimo {last_abs} {last_rel}")
        lines.append("")

    return "\n".join(lines)
