from __future__ import annotations

from datetime import datetime, timezone

import discord

from app.services.activity_insights import ChannelActivityDetails

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


def _display_name(guild: discord.Guild, user_id: int) -> str:
    member = guild.get_member(user_id)
    return member.display_name if member else f"ID {user_id}"


def _active_row(rank: int, user: object) -> str:
    medals = ["🥇", "🥈", "🥉"]
    top = medals[rank - 1] if rank <= 3 else "•"
    last_abs, last_rel = _fmt_discord_ts(user.last_ts_in_range)
    peak_abs, _ = _fmt_discord_ts(user.peak_hour_ts)
    return (
        f"{top} **<@{user.user_id}>** (**{user.count_in_range} msg**) | 💬 Ultimo: {last_abs} 🕒 {last_rel}\n"
        f"  🔥 Picco: {peak_abs} (**{user.peak_count} msg**)"
    )


def _inactive_row(guild: discord.Guild, rank: int, user: object) -> str:
    medals = ["🥇", "🥈", "🥉"]
    top = medals[rank - 1] if rank <= 3 else "•"
    name = _display_name(guild, user.user_id)
    if user.last_ts_channel is None:
        return f"{top} **{name}** (**0 msg**) (mai partecipato dall'ingresso 🥀)"
    last_abs, last_rel = _fmt_discord_ts(user.last_ts_channel)
    return f"{top} **{name}** (**0 msg**) | 💬 Ultimo: {last_abs} 🕒 {last_rel}"


def _truncate_field(value: str) -> str:
    return value if len(value) <= 1024 else value[:1021] + "..."


def build_daily_activity_embeds(
    guild: discord.Guild,
    guild_name: str,
    channel_payloads: list[tuple[discord.abc.GuildChannel | discord.Thread | None, ChannelActivityDetails]],
    *,
    reference_ts: str,
) -> list[discord.Embed]:
    _ = reference_ts
    total_messages = sum(item.score.messages_count for _, item in channel_payloads)
    total_active = sum(item.score.active_users_count for _, item in channel_payloads)
    continuity_server = max((item.score.continuity_hours for _, item in channel_payloads), default=0)
    prev_total_estimate = 0
    for _, item in channel_payloads:
        trend = item.score.trend_text or ""
        if "% vs finestra precedente" in trend:
            try:
                pct = int(trend.split("(")[-1].split("%")[0])
                if pct != -100:
                    prev_total_estimate += int(round(item.score.messages_count / (1 + (pct / 100))))
            except Exception:
                continue
    score_server = 0
    if channel_payloads:
        score_server = int(round(sum(item.score.score for _, item in channel_payloads) / len(channel_payloads)))
    if score_server <= 20:
        server_emoji, server_label = "⚫", "ASSENTE"
    elif score_server <= 40:
        server_emoji, server_label = "🔴", "SCARSA"
    elif score_server <= 60:
        server_emoji, server_label = "🟡", "MEDIOCRE"
    else:
        server_emoji, server_label = "🟢", "INTENSA"

    trend_server = "Messaggi stabili rispetto alla finestra precedente."
    if prev_total_estimate > 0:
        delta = int(round(((total_messages - prev_total_estimate) / prev_total_estimate) * 100))
        direction = "in crescita" if delta > 0 else "in calo" if delta < 0 else "stabili"
        trend_server = f"Messaggi {direction} ({delta:+d}% vs finestra precedente)."

    overview = discord.Embed(
        title=f"🗣️ RESOCONTO ATTIVITÀ “{guild_name}”",
        color=_color_for_emoji(server_emoji),
        description=(
            "🕒 **Oggi**\n\n"
            f"{server_emoji} **ATTIVITÀ {server_label}**\n"
            "*Ritmo del server valutato su volume, persone attive e continuità.*\n\n"
            f"🫀 **PUNTI ATTIVITÀ**\n{_bar(score_server, server_emoji)} **({score_server}/100)**\n"
            f"*{trend_server}*"
        ),
    )
    overview.add_field(
        name="📌 STATISTICHE SERVER",
        value=_truncate_field(
            f"• Messaggi: **{total_messages}**\n"
            f"• Utenti attivi (somma): **{total_active}**\n"
            f"• Continuità oraria: **{continuity_server}** ore con attività\n"
            f"• Canali monitorati: **{len(channel_payloads)}**"
        ),
        inline=False,
    )
    overview.set_footer(text="Barcellometro")

    embeds = [overview]
    for dc, details in channel_payloads:
        channel_name = getattr(dc, "name", "sconosciuto")
        channel_mention = f"#{channel_name}"
        s = details.score
        embed = discord.Embed(
            title=f"📄 DETTAGLI ATTIVITÀ “{channel_mention}”",
            color=_color_for_emoji(s.emoji),
            description=(
                f"{s.emoji} **ATTIVITÀ {s.label}**\n"
                "*Ritmo del canale valutato su volume, persone attive e continuità.*\n\n"
                f"🫀 **PUNTI ATTIVITÀ**\n{_bar(s.score, s.emoji)} **({s.score}/100)**\n"
                f"*{s.trend_text}*"
            ),
        )
        embed.add_field(name="📌 STATISTICHE CANALE", value=_truncate_field("\n".join(details.stats_lines or ["n/d"])), inline=False)
        embed.add_field(name="📈 TREND", value=_truncate_field(s.trend_text or "n/d"), inline=False)

        top3 = details.top_active_users[:3]
        top_value = "\n".join(_active_row(i + 1, u) for i, u in enumerate(top3)) or "—"
        if len(details.top_active_users) > 3:
            top_value += f"\n… + altri {len(details.top_active_users) - 3} utenti (vedere .txt allegato per i dettagli)"
        embed.add_field(name="🏆 TOP 3 UTENTI PIÙ ATTIVI", value=_truncate_field(top_value), inline=False)

        inactive3 = details.inactive_users[:3]
        inactive_value = "\n".join(_inactive_row(guild, i + 1, u) for i, u in enumerate(inactive3)) or "—"
        if len(details.inactive_users) > 3:
            inactive_value += f"\n… + altri {len(details.inactive_users) - 3} utenti (vedere .txt allegato per i dettagli)"
        embed.add_field(name="💤 TOP 3 UTENTI INATTIVI", value=_truncate_field(inactive_value), inline=False)

        advice = "\n".join(f"• {row}" for row in details.advice_bullets) or "• Nessun consiglio"
        embed.add_field(name="💡 CONSIGLI", value=_truncate_field(advice), inline=False)
        embed.set_footer(text="Barcellometro")
        embeds.append(embed)

    return embeds


def build_daily_activity_details_txt(
    guild: discord.Guild,
    guild_name: str,
    channel_payloads: list[tuple[discord.abc.GuildChannel | discord.Thread | None, ChannelActivityDetails]],
    *,
    reference_ts: str,
) -> str:
    _ = reference_ts
    lines = [
        "BARCELLOMETRO — DETTAGLI ATTIVITÀ GIORNALIERA",
        f"Server: {guild_name} ({guild.id})",
        f"Generato il: {datetime.now(timezone.utc).isoformat()}",
        "",
    ]
    for dc, details in channel_payloads:
        channel_name = getattr(dc, "name", "sconosciuto")
        channel_id = getattr(dc, "id", "n/d")
        lines.append(f"=== CANALE #{channel_name} ({channel_id}) ===")
        lines.append(f"Stato: {details.score.emoji} {details.score.label} | Punti: {details.score.score}/100")
        lines.append("TOP 10 ATTIVI")
        for idx, item in enumerate(details.top_active_users[:10], start=1):
            last_abs, _ = _fmt_discord_ts(item.last_ts_in_range)
            peak_abs, _ = _fmt_discord_ts(item.peak_hour_ts)
            lines.append(f"{idx}. <@{item.user_id}> — {item.count_in_range} msg | ultimo: {last_abs} | picco: {peak_abs} ({item.peak_count} msg)")
        lines.append("TOP 10 INATTIVI")
        for idx, item in enumerate(details.inactive_users[:10], start=1):
            name = _display_name(guild, item.user_id)
            if item.last_ts_channel is None:
                lines.append(f"{idx}. {name} (id={item.user_id}) — 0 msg | mai partecipato dall'ingresso")
            else:
                last_abs, _ = _fmt_discord_ts(item.last_ts_channel)
                lines.append(f"{idx}. {name} (id={item.user_id}) — 0 msg | ultimo: {last_abs}")
        lines.append("")
    return "\n".join(lines)
