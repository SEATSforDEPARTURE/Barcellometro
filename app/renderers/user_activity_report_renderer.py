from __future__ import annotations

from datetime import datetime, timezone

import discord

from app.services.author import attach_author_meta
from app.services.embed_images import attach_embed_images_meta
from app.services.footer import attach_footer_meta
from app.shared.discord.embed_body import format_standard_description, format_standard_field_name, format_standard_title



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


def _fmt_jump_line(*, guild_id: str, channel_id: str | None, message_id: str | None, ts: datetime, channel_name: str) -> str:
    label = ts.strftime("%d/%m %H:%M")
    unix_ts = int(ts.timestamp())
    if channel_id and message_id:
        jump_url = f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
        return f"[{label}]({jump_url}) 🕒 <t:{unix_ts}:R> in \"{channel_name}\""
    return f"{label} 🕒 <t:{unix_ts}:R> in \"{channel_name}\""


def build_user_activity_embeds(
    *,
    guild_id: str,
    display_name: str,
    period_label: str,
    activity_label: str,
    activity_emoji: str,
    score: int,
    trend_text: str,
    overview_description: str,
    stats_lines: list[str],
    advice_lines: list[str],
) -> list[discord.Embed]:
    overview = discord.Embed(
        title=format_standard_title(f"STATO ATTIVITÀ “{display_name}”", emoji="🗣️"),
        color=_color_for_label(activity_label),
    )
    overview.description = format_standard_description(
        "Snapshot sintetico dell'attività utente nel periodo selezionato.",
        italic=False,
    )
    overview.add_field(name=format_standard_field_name("Periodo", emoji="🕒"), value=period_label, inline=False)
    overview.add_field(
        name=format_standard_field_name("Stato attività", emoji=activity_emoji),
        value=f"**ATTIVITÀ {activity_label}**\n{overview_description}",
        inline=False,
    )
    overview.add_field(
        name=format_standard_field_name("Punti attività", emoji="🫀"),
        value=f"{_bar(score, activity_emoji)} **({score}/100)**",
        inline=False,
    )
    overview.add_field(name=format_standard_field_name("Trend", emoji="📈"), value=f"• 📨 {trend_text}", inline=False)
    attach_footer_meta(overview, service_name="user_activity", used_local_processing=True)
    attach_author_meta(overview, service_name="user_activity", canonical_top_level_command="serversummary")
    attach_embed_images_meta(overview, service_name="user_activity")

    details = discord.Embed(title=format_standard_title("DETTAGLI ATTIVITÀ — Staff", emoji="📄"), color=discord.Color.dark_grey())
    details.add_field(name=format_standard_field_name("Statistiche utente", emoji="📊"), value="\n".join(stats_lines) if stats_lines else "—", inline=False)
    details.add_field(
        name=format_standard_field_name("Consigli per la moderazione", emoji="💡"),
        value="\n".join(f"• {line}" for line in advice_lines) if advice_lines else "• Nessun consiglio disponibile.",
        inline=False,
    )
    attach_footer_meta(details, service_name="user_activity", used_local_processing=True)
    attach_author_meta(details, service_name="user_activity", canonical_top_level_command="serversummary")
    attach_embed_images_meta(details, service_name="user_activity")
    return [overview, details]


def format_last_message_line(guild_id: str, ts: datetime | None, channel_id: str | None, message_id: str | None, channel_name: str) -> str:
    if ts is None:
        return "• 💬 Ultimo messaggio: —"
    return f"• 💬 Ultimo messaggio: {_fmt_jump_line(guild_id=guild_id, channel_id=channel_id, message_id=message_id, ts=ts.astimezone(timezone.utc), channel_name=channel_name)}"
