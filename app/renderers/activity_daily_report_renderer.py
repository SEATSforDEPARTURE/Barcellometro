from __future__ import annotations

import discord

from app.services.activity_insights import ChannelActivityDetails


def build_daily_activity_embeds(guild_name: str, channel_payloads: list[tuple[str, ChannelActivityDetails]]) -> list[discord.Embed]:
    total_messages = sum(item.score.messages_count for _, item in channel_payloads)
    total_active = sum(item.score.active_users_count for _, item in channel_payloads)
    overview = discord.Embed(
        title=f"📊 RESOCONTO ATTIVITÀ GIORNALIERA — {guild_name}",
        description=f"Canali monitorati: **{len(channel_payloads)}**\nMessaggi totali: **{total_messages}**\nUtenti attivi (somma): **{total_active}**",
        color=0x5865F2,
    )
    overview.set_footer(text="Barcellometro")
    embeds = [overview]
    for channel_name, details in channel_payloads:
        s = details.score
        bar = f"{s.emoji * max(0, min(10, int(round(s.score/10))))}{'⚪' * (10 - max(0, min(10, int(round(s.score/10)))))}"
        embed = discord.Embed(title=f"#{channel_name} — Attività {s.label}", color=0x5865F2)
        embed.add_field(name="🫀 PUNTI ATTIVITÀ", value=f"{bar} **({s.score}/100)**", inline=False)
        embed.add_field(name="📈 TREND", value=s.trend_text, inline=False)
        embed.add_field(name="📌 STATISTICHE", value="\n".join(details.stats_lines) or "n/d", inline=False)
        top = [f"• <@{item.user_id}> — {item.count_in_range} msg" for item in details.top_active_users] or ["• Nessun dato"]
        embed.add_field(name="🏆 UTENTI PIÙ ATTIVI", value="\n".join(top), inline=False)
        sleepy = [f"• <@{item.user_id}> — {item.count_in_range} msg" for item in details.inactive_users] or ["• Nessun inattivo"]
        embed.add_field(name="💤 UTENTI INATTIVI", value="\n".join(sleepy), inline=False)
        embed.add_field(name="💡 CONSIGLI", value="\n".join(f"• {row}" for row in details.advice_bullets), inline=False)
        embed.set_footer(text="Barcellometro")
        embeds.append(embed)
    return embeds
