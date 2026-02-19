from __future__ import annotations

from datetime import datetime, timezone

import discord

from app.services.activity_insights import ChannelActivityDetails
from app.services.inactivity import InactivityEntry


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


def _fmt_inactive(entry: InactivityEntry) -> str:
    if not entry.last_seen_ts:
        return f"<@{entry.user_id}> — mai visto"
    try:
        dt = datetime.fromisoformat(entry.last_seen_ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        label = dt.astimezone().strftime("%d/%m %H:%M")
    except Exception:
        label = entry.last_seen_ts
    return f"<@{entry.user_id}> — ultimo msg {label} ({entry.days_inactive}g)"


def build_activity_dm_embeds(channel_name: str, label_periodo: str, details: ChannelActivityDetails) -> list[discord.Embed]:
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

    details_embed = discord.Embed(title="📄 DETTAGLI ATTIVITÀ — Staff", color=_color_for_label(s.label))
    details_embed.add_field(name="📌 STATISTICHE CANALE", value="\n".join(details.stats_lines) or "n/d", inline=False)
    details_embed.add_field(name="📈 TREND", value=details.score.trend_text, inline=False)

    top_lines = [f"• <@{uid}> — **{cnt}** msg" for uid, cnt in details.top_active_users] or ["• Nessun dato"]
    details_embed.add_field(name="🏆 UTENTI PIÙ ATTIVI", value="\n".join(top_lines), inline=False)

    inactive_lines = [_fmt_inactive(entry) for entry in details.inactive_users] or ["• Nessun inattivo rilevante"]
    details_embed.add_field(name="💤 UTENTI INATTIVI", value="\n".join(inactive_lines), inline=False)
    details_embed.add_field(name="💡 CONSIGLI", value="\n".join(f"• {line}" for line in details.advice_bullets), inline=False)
    details_embed.set_footer(text="Barcellometro")
    return [status, details_embed]
