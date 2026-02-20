from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import discord

ITALIAN_WEEKDAYS = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
ITALIAN_MONTHS = ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno", "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]

COLOR_BY_EMOJI = {"🟢": 0x57F287, "🟡": 0xFEE75C, "🔴": 0xED4245, "⚫": 0x2F3136}


def _color_for_emoji(emoji: str) -> int:
    return COLOR_BY_EMOJI.get(emoji, 0x2F3136)


def _bar(score: int, emoji: str) -> str:
    filled = max(0, min(10, int(round(score / 10))))
    return f"{emoji * filled}{'⚪' * (10 - filled)}"


def _format_italian_date(reference_ts: str) -> str:
    dt = datetime.fromisoformat(reference_ts.replace("Z", "+00:00"))
    return f"{ITALIAN_WEEKDAYS[dt.weekday()]}, {dt.day} {ITALIAN_MONTHS[dt.month - 1]} {dt.year}"


def _fmt_hour(hour: int | None) -> str:
    return f"{hour:02d}:00" if hour is not None else "—"


def _truncate_field(value: str) -> str:
    return value if len(value) <= 1024 else value[:1021] + "..."


def _fmt_duration_hhmm(seconds: int) -> str:
    minutes = max(0, seconds // 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def build_daily_activity_embeds(
    guild: discord.Guild,
    guild_name: str,
    channel_payloads: list[dict[str, Any]],
    *,
    server_summary: dict[str, Any],
    reference_ts: str,
) -> list[discord.Embed]:
    _ = guild
    total_messages = sum(item["details"].score.messages_count for item in channel_payloads)
    active_x = int(server_summary.get("active_non_bot", 0))
    total_y = server_summary.get("total_non_bot_members")
    total_y_label = str(total_y) if total_y is not None else "?"

    label = str(server_summary.get("label", "ASSENTE"))
    score = int(server_summary.get("score", 0))
    trend = str(server_summary.get("trend_text", "n/d"))
    emoji = "⚫" if score <= 20 else "🔴" if score <= 40 else "🟡" if score <= 60 else "🟢"

    advice = []
    for item in channel_payloads:
        for row in item["details"].advice_bullets:
            if row not in advice:
                advice.append(row)
    if not advice:
        advice = ["Ritmo regolare: mantenete costanza e coinvolgimento."]

    overview = discord.Embed(
        title=f"🗣️ RESOCONTO ATTIVITÀ “{guild_name}”",
        color=_color_for_emoji(emoji),
        description=(
            f"**🗓️ {_format_italian_date(reference_ts)}**\n\n"
            f"{emoji} **ATTIVITÀ {label}**\n"
            "*Ritmo del server valutato su volume, persone attive e continuità.*\n\n"
            f"🫀 **PUNTI ATTIVITÀ**\n{_bar(score, emoji)} **({score}/100)**"
        ),
    )
    overview.add_field(name="📈 TREND", value=_truncate_field(trend), inline=False)
    overview.add_field(
        name="📌 STATISTICHE SERVER",
        value=_truncate_field(
            f"• Messaggi: **{total_messages}**\n"
            f"• Utenti attivi: **{active_x}/{total_y_label}**\n"
            f"• Ora di picco generale: **{_fmt_hour(server_summary.get('peak_hour'))}**\n"
            f"• Ora di silenzio generale: **{_fmt_hour(server_summary.get('silence_hour'))}**\n"
            f"• Continuità oraria generale: **{int(server_summary.get('continuity_hours', 0))}** ore con attività\n"
            f"• Canali monitorati: **{len(channel_payloads)}**"
        ),
        inline=False,
    )
    overview.add_field(name="💡 CONSIGLI", value=_truncate_field("\n".join(f"• {x}" for x in advice[:4])), inline=False)
    overview.set_footer(text="Barcellometro")

    embeds = [overview]
    for item in channel_payloads:
        dc = item["channel"]
        details = item["details"]
        s = details.score
        b = item.get("members_with_access")
        b_label = str(b) if b is not None else "?"
        stats_lines = [
            f"• Messaggi: **{s.messages_count}**",
            f"• Utenti attivi: **{item.get('active_non_bot', 0)}/{b_label}**",
            f"• Ora di picco: **{_fmt_hour(item.get('peak_hour'))}**",
            f"• Ora di silenzio: **{_fmt_hour(item.get('silence_hour'))}**",
            f"• Continuità oraria: **{item.get('continuity_hours', s.continuity_hours)}** ore con attività",
        ]
        if item.get("is_voice"):
            c = int(item.get("voice_sessions_count", 0))
            if c > 0:
                stats_lines.append(f"• Chiamate: **{c}** sessioni (Durata totale: **{_fmt_duration_hhmm(int(item.get('voice_total_seconds', 0)))}**) ")
            else:
                stats_lines.append("• Chiamate: **0**")
        embed = discord.Embed(
            title=f"📄 DETTAGLI ATTIVITÀ “#{getattr(dc, 'name', 'sconosciuto')}”",
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
    total_members = server_summary.get("total_non_bot_members")
    total_members_label = str(total_members) if total_members is not None else "?"
    active_total = int(server_summary.get("active_non_bot", 0))
    inactive_total = server_summary.get("inactive_non_bot")
    inactive_total_label = str(inactive_total) if inactive_total is not None else "?"

    lines = [
        f"RESOCONTO ATTIVITÀ SERVER — 🗝 {guild_name}",
        "",
        f"Data: {_format_italian_date(reference_ts)}",
        f"Finestra temporale: 00:00 → {server_summary.get('window_end_local', datetime.fromisoformat(reference_ts.replace('Z', '+00:00')).strftime('%H:%M'))}",
        "",
        f"• Attività generale: {server_summary.get('label', 'ASSENTE')}",
        f"• Punti attività generali: {server_summary.get('score', 0)}/100",
        f"• Trend generale: {server_summary.get('trend_text', 'n/d')}",
        f"• Messaggi totali: {total_messages}",
        f"• Utenti attivi totali: {active_total}/{total_members_label}",
        f"• Utenti inattivi totali: {inactive_total_label}/{total_members_label}",
        f"• Ora di picco generale: {_fmt_hour(server_summary.get('peak_hour'))}",
        f"• Ora di silenzio generale: {_fmt_hour(server_summary.get('silence_hour'))}",
        f"• Continuità oraria generale: {server_summary.get('continuity_hours', 0)} ore con attività",
        "",
        "🏆 UTENTI ATTIVI GENERALI:",
    ]
    global_active_rows = server_summary.get("global_active_rows", [])
    if global_active_rows:
        lines.extend(global_active_rows)
    else:
        lines.append("Nessun utente attivo nel periodo.")

    lines.extend(["", "💤 UTENTI INATTIVI GENERALI:"])
    global_inactive_rows = server_summary.get("global_inactive_rows", [])
    if global_inactive_rows:
        lines.extend(global_inactive_rows)
    else:
        lines.append("Nessun utente inattivo nel periodo.")

    for item in channel_payloads:
        details = item["details"]
        s = details.score
        channel = item["channel"]
        ch_name = f"#{getattr(channel, 'name', 'sconosciuto')}"
        b = item.get("members_with_access")
        b_label = str(b) if b is not None else (str(total_members) if total_members is not None else "?")
        inactive_ch = item.get("inactive_non_bot")
        inactive_ch_label = str(inactive_ch) if inactive_ch is not None else "?"

        lines.extend(
            [
                "",
                f"==== {ch_name} ====",
                "",
                f"• Attività: {s.label}",
                f"• Punti attività: {s.score}/100",
                f"• Trend: {s.trend_text}",
                f"• Messaggi: {s.messages_count}",
                f"• Utenti attivi: {item.get('active_non_bot', 0)}/{b_label}",
                f"• Utenti inattivi: {inactive_ch_label}/{b_label}",
                f"• Ora di picco: {_fmt_hour(item.get('peak_hour'))}",
                f"• Ora di silenzio: {_fmt_hour(item.get('silence_hour'))}",
                f"• Continuità oraria: {item.get('continuity_hours', s.continuity_hours)} ore con attività",
            ]
        )

        if item.get("is_voice"):
            lines.extend(
                [
                    f"• Chiamate: {int(item.get('voice_sessions_count', 0))} (Durata totale: {_fmt_duration_hhmm(int(item.get('voice_total_seconds', 0)))})",
                    "Dettaglio chiamate:",
                ]
            )
            voice_details = item.get("voice_details", [])
            lines.extend(voice_details or ["- Nessuna sessione"])

        lines.append("")
        lines.append("UTENTI PIÙ ATTIVI:")
        lines.extend(item.get("active_lines", ["Nessun utente attivo nel canale nel periodo."]))

        lines.append("")
        lines.append("UTENTI MENO ATTIVI:")
        lines.extend(item.get("inactive_lines", ["Nessun utente inattivo rilevato."]))

    _ = guild
    return "\n".join(lines)
