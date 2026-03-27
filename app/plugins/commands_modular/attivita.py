from __future__ import annotations

import io
import json
import logging
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import discord

from app.services.footer import attach_footer_meta
from app.shared.discord.embed_body import format_standard_field_name, format_standard_title
from discord import Forbidden, app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.time_windows import resolve_ieri_window, resolve_oggi_window, resolve_range_window, resolve_ultimi_window
from app.renderers.activity_dm_report_renderer import build_activity_details_txt, build_activity_dm_embeds
from app.renderers.user_activity_report_renderer import build_user_activity_embeds
from app.shared.discord.command_embeds import CommandEmbedSection, send_standard_response
from app.shared.discord.report_embeds import apply_standard_report_style

logger = logging.getLogger(__name__)
ROME_TZ = ZoneInfo("Europe/Rome")
MENTION_RE = re.compile(r"<@!?(\d+)>")
STOPWORDS_IT = {
    "che", "per", "con", "non", "una", "del", "della", "delle", "degli", "sono", "alla", "dopo", "come", "anche", "solo", "sono",
    "nel", "nella", "nelle", "degli", "gli", "dei", "dai", "dalle", "all", "questo", "quello", "quella", "oggi", "ieri", "domani",
    "era", "pero", "però", "mia", "mio", "miei", "mie", "tuo", "tua", "tuoi", "tue", "suoi", "loro", "noi", "voi", "lui", "lei",
    "quindi", "allora", "sempre", "mai", "gia", "già", "poi", "qui", "lì", "li", "ciao", "buongiorno", "buonasera", "ok", "si", "sì",
    "no", "ah", "eh", "boh", "e", "o", "ma", "di", "a", "da", "in", "su", "per", "tra", "fra", "un", "una", "uno", "sei", "è",
    "ero", "sara", "sarà", "essere", "avere", "ho", "hai", "ha", "hanno", "avevo", "sono", "come", "solo", "anche",
    "dalla", "dallo", "dagli", "delle", "della", "dello", "dell", "alla", "alle", "allo", "al", "tutto", "tutti", "tutta", "tutte",
    "cosi", "così", "cioe", "cioè", "tipo", "suo", "sua", "suo", "sue", "sui",
}
STOPWORDS_IT_NORMALIZED = {re.sub(r"[^a-z0-9]", "", "".join(ch for ch in unicodedata.normalize("NFKD", w.lower()) if not unicodedata.combining(ch))) for w in STOPWORDS_IT}
MAX_FIELD_VALUE = 1024
MAX_FIELD_NAME = 256
MAX_EMBED_TOTAL = 6000
MAX_EMBED_FIELDS = 25
FALLBACK_EMBED_THRESHOLD = 5500


def _safe_filename(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.lower())
    return safe.strip("_") or "canale"


def b(value: str) -> str:
    return f"**{value}**"


def fmt_channel_compact(guild: discord.Guild, channel_id: str | None) -> str:
    if not channel_id or not str(channel_id).isdigit():
        return "—"
    channel = guild.get_channel(int(channel_id))
    if channel is None:
        return "—"
    name = getattr(channel, "name", None)
    if not name:
        return "—"
    channel_type = str(getattr(channel, "type", ""))
    if channel_type in {"text", "news", "forum"}:
        return f"#{name}"
    return str(name).upper() if str(name).islower() else str(name)


def _normalize_token(token: str) -> str:
    normalized = unicodedata.normalize("NFKD", token.lower())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = re.sub(r"[^a-z0-9]", "", normalized)
    return normalized


def _with_blank_lines(lines: list[str]) -> str:
    out: list[str] = []
    for line in lines:
        out.append(line)
        out.append("")
    return "\n".join(out).rstrip()


def _truncate(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _split_chunks(text: str, limit: int) -> list[str]:
    if not text:
        return ["—"]
    lines = text.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        safe_line = _truncate(line, limit)
        add_len = len(safe_line) + (1 if current else 0)
        if current and current_len + add_len > limit:
            chunks.append("\n".join(current))
            current = [safe_line]
            current_len = len(safe_line)
            continue
        current.append(safe_line)
        current_len += add_len
    if current:
        chunks.append("\n".join(current))
    return chunks or ["—"]


def add_field_safe(embed: discord.Embed, *, name: str, value: str, inline: bool = False) -> None:
    safe_name = _truncate(name, MAX_FIELD_NAME)

    def _normalize_field_name(raw: str) -> str:
        text = _truncate(raw, MAX_FIELD_NAME)
        if "__**" in text:
            return text
        return _truncate(format_standard_field_name(text), MAX_FIELD_NAME)

    chunks = _split_chunks(value, MAX_FIELD_VALUE)
    for idx, chunk in enumerate(chunks):
        if len(embed.fields) >= MAX_EMBED_FIELDS:
            break
        field_name = _normalize_field_name(safe_name if idx == 0 else f"{safe_name} (cont.)")
        embed.add_field(name=field_name, value=_truncate(chunk or "—", MAX_FIELD_VALUE), inline=inline)


def embed_total_len(embed: discord.Embed) -> int:
    total = len(embed.title or "") + len(embed.description or "")
    total += len(embed.footer.text) if embed.footer and embed.footer.text else 0
    total += len(embed.author.name) if embed.author and embed.author.name else 0
    for field in embed.fields:
        total += len(field.name or "") + len(field.value or "")
    return total


def _join_limited(items: list[str], *, max_items: int, max_chars: int) -> str:
    raw = [str(item).strip() for item in items if str(item).strip()][:max_items]
    if not raw:
        return "—"
    return _truncate(", ".join(raw), max_chars)


def _make_user_report_txt(display_name: str, period_label: str, stats: list[str], interactions: list[str], topics: list[str], advice: list[str]) -> str:
    return "\n".join(
        [
            f"BARCELLOMETRO — REPORT ATTIVITÀ UTENTE ({display_name})",
            f"Periodo: {period_label}",
            "",
            "[STATISTICHE]",
            *stats,
            "",
            "[INTERAZIONI]",
            *interactions,
            "",
            "[TEMI E PAROLE]",
            *topics,
            "",
            "[CONSIGLI]",
            *[f"• {line}" for line in advice],
        ]
    )


def _build_user_activity_embeds_safe(
    *,
    display_name: str,
    period_label: str,
    emoji: str,
    label: str,
    score: int,
    trend_text: str,
    stats_lines: list[str],
    interaction_lines: list[str],
    topics_lines: list[str],
    advice_lines: list[str],
) -> tuple[list[discord.Embed], bool]:
    color_map = {"ASSENTE": 0x2F3136, "SCARSA": 0xE74C3C, "MEDIOCRE": 0xF1C40F, "INTENSA": 0x2ECC71}
    filled = max(0, min(10, int(round(max(0, min(score, 100)) / 10))))
    bar = f"{emoji * filled}{'⚪' * (10 - filled)}"

    embed1 = discord.Embed(title=format_standard_title(f"STATO ATTIVITÀ “{display_name}”", emoji="🗣️"), color=color_map.get(label, 0x95A5A6))
    embed1.description = _truncate("Snapshot sintetico dell'attività utente nel periodo selezionato.", 4000)
    add_field_safe(embed1, name=format_standard_field_name("Periodo", emoji="🕒"), value=period_label)
    add_field_safe(
        embed1,
        name=format_standard_field_name("Stato attività", emoji=emoji),
        value=f"**ATTIVITÀ {label}**\nRitmo dell'utente valutato su volume, continuità e presenza nei canali.",
    )
    add_field_safe(embed1, name=format_standard_field_name("Punti attività", emoji="🫀"), value=f"{bar} {b(f'({score}/100)')}")
    add_field_safe(embed1, name=format_standard_field_name("Trend", emoji="📈"), value=f"• 📨 {trend_text}")
    attach_footer_meta(embed1, service_name="attivita", used_local_processing=True)

    embed2 = discord.Embed(title=format_standard_title("DETTAGLI ATTIVITÀ — Staff", emoji="📄"), color=discord.Color.dark_grey())
    add_field_safe(embed2, name=format_standard_field_name("Statistiche utente", emoji="📊"), value=_with_blank_lines(stats_lines))
    add_field_safe(embed2, name=format_standard_field_name("Interazioni maggiori", emoji="🧑‍🤝‍🧑"), value="\n".join(interaction_lines))
    add_field_safe(embed2, name=format_standard_field_name("Temi e parole più usate", emoji="🔎"), value="\n".join(topics_lines))
    add_field_safe(embed2, name=format_standard_field_name("Consigli per la moderazione", emoji="💡"), value="\n".join(f"• {line}" for line in advice_lines[:4]))
    attach_footer_meta(embed2, service_name="attivita", used_local_processing=True)

    too_long = (
        embed_total_len(embed1) > MAX_EMBED_TOTAL
        or embed_total_len(embed2) > MAX_EMBED_TOTAL
        or embed_total_len(embed1) + embed_total_len(embed2) > FALLBACK_EMBED_THRESHOLD
        or len(embed1.fields) > MAX_EMBED_FIELDS
        or len(embed2.fields) > MAX_EMBED_FIELDS
    )
    if too_long:
        embed2.clear_fields()
        add_field_safe(embed2, name=format_standard_field_name("Statistiche utente", emoji="📊"), value=_with_blank_lines(stats_lines[:6]))
        add_field_safe(embed2, name=format_standard_field_name("Interazioni maggiori", emoji="🧑‍🤝‍🧑"), value="\n".join(interaction_lines))
        add_field_safe(embed2, name=format_standard_field_name("Temi e parole più usate", emoji="🔎"), value="Dettagli completi nel file allegato.")
        add_field_safe(embed2, name=format_standard_field_name("Consigli per la moderazione", emoji="💡"), value="Dettagli completi nel file allegato.")
    return [embed1, embed2], too_long


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _score_label(score: int) -> tuple[str, str]:
    if score <= 20:
        return "⚫", "ASSENTE"
    if score <= 40:
        return "🔴", "SCARSA"
    if score <= 60:
        return "🟡", "MEDIOCRE"
    return "🟢", "INTENSA"


def _trend(curr: int, prev: int) -> str:
    percent = int(round(((curr - prev) / max(prev, 1)) * 100))
    if abs(percent) < 5:
        direction = "stabile"
    elif percent > 0:
        direction = "in crescita"
    else:
        direction = "in calo"
    return f"Messaggi {direction} ({b(f'{percent:+d}%')} vs finestra precedente)."


def _extract_mentions(mentions_json: str | None, content: str) -> set[int]:
    out: set[int] = set()
    if mentions_json:
        try:
            raw = json.loads(mentions_json)
            if isinstance(raw, list):
                for item in raw:
                    out.add(int(item))
        except Exception:
            pass
    for match in MENTION_RE.findall(content or ""):
        try:
            out.add(int(match))
        except Exception:
            continue
    return out


def _compute_peak(messages: list[dict[str, str | None]], multi_day: bool) -> tuple[str, str | None, str | None]:
    if not messages:
        return "—", None, None
    if multi_day:
        grouped: dict[str, list[dict[str, str | None]]] = defaultdict(list)
        for m in messages:
            dt = _parse_ts(m["ts"])
            if dt is None:
                continue
            grouped[dt.astimezone(ROME_TZ).strftime("%d/%m")].append(m)
        if not grouped:
            return "—", None, None
        day, rows = max(grouped.items(), key=lambda item: (len(item[1]), item[0]))
        channel_counts = Counter([r["channel_id"] for r in rows if r.get("channel_id")])
        best_channel = sorted(channel_counts.items(), key=lambda item: (-item[1], item[0]))[0][0] if channel_counts else None
        msg = next((r for r in rows if r.get("channel_id") == best_channel), rows[0])
        return f"{day} ({len(rows)} msg)", best_channel, msg.get("message_id")

    hourly: dict[int, list[dict[str, str | None]]] = defaultdict(list)
    for m in messages:
        dt = _parse_ts(m["ts"])
        if dt is None:
            continue
        hourly[dt.astimezone(ROME_TZ).hour].append(m)
    if not hourly:
        return "—", None, None
    hour, rows = max(hourly.items(), key=lambda item: (len(item[1]), -item[0]))
    channel_counts = Counter([r["channel_id"] for r in rows if r.get("channel_id")])
    best_channel = sorted(channel_counts.items(), key=lambda item: (-item[1], item[0]))[0][0] if channel_counts else None
    msg = next((r for r in rows if r.get("channel_id") == best_channel), rows[0])
    return f"{hour:02d}:00 ({len(rows)} msg)", best_channel, msg.get("message_id")


def _silent_hour(messages: list[dict[str, str | None]]) -> str:
    if not messages:
        return "—"
    counts = {h: 0 for h in range(24)}
    for m in messages:
        dt = _parse_ts(m["ts"])
        if dt is None:
            continue
        counts[dt.astimezone(ROME_TZ).hour] += 1
    return f"{min(counts.items(), key=lambda item: (item[1], item[0]))[0]:02d}:00"


def _words_and_themes(messages: list[dict[str, str | None]]) -> tuple[list[str], list[str]]:
    words: Counter[str] = Counter()
    presence: Counter[str] = Counter()
    msg_count = max(1, len(messages))
    for m in messages:
        content = (m.get("content") or "").lower()
        tokens = re.findall(r"[a-zàèéìòù0-9']{2,}", content)
        seen_in_message: set[str] = set()
        for tok in tokens:
            tok_n = _normalize_token(tok)
            if not tok_n or tok_n.isnumeric() or len(tok_n) < 4:
                continue
            if tok_n in STOPWORDS_IT_NORMALIZED:
                continue
            if tok.startswith("'"):
                continue
            if len(set(tok_n)) == 1:
                continue
            words[tok_n] += 1
            seen_in_message.add(tok_n)
        for tok in seen_in_message:
            presence[tok] += 1
    for tok in list(words.keys()):
        if presence.get(tok, 0) / msg_count > 0.6:
            words.pop(tok, None)
    top_words = [w for w, _ in words.most_common(10)]
    themes = [w.title() for w, _ in words.most_common(5)]
    return themes, top_words


def _build_interactions(messages: list[dict[str, str | None]], reply_author_map: dict[str, int], bot_ids: set[int], self_id: int) -> dict[int, dict[str, object]]:
    interactions: dict[int, dict[str, object]] = {}
    for m in messages:
        channel_id = m.get("channel_id")
        if m.get("reply_to_message_id"):
            reply_id = m["reply_to_message_id"]
            if reply_id and reply_id in reply_author_map:
                other = reply_author_map[reply_id]
                if other != self_id and other not in bot_ids:
                    rec = interactions.setdefault(other, {"count": 0, "channels": Counter()})
                    rec["count"] = int(rec["count"]) + 1
                    if channel_id:
                        rec["channels"][channel_id] += 1  # type: ignore[index]
        for uid in _extract_mentions(m.get("mentions_json"), m.get("content") or ""):
            if uid == self_id or uid in bot_ids:
                continue
            rec = interactions.setdefault(uid, {"count": 0, "channels": Counter()})
            rec["count"] = int(rec["count"]) + 1
            if channel_id:
                rec["channels"][channel_id] += 1  # type: ignore[index]
    return interactions


def _format_interactions(interactions: dict[int, dict[str, object]]) -> str:
    if not interactions:
        return "—"
    ordered = sorted(interactions.items(), key=lambda item: (-item[1]["count"], item[0]))
    lines: list[str] = []
    for uid, payload in ordered[:3]:
        count_label = b(f"{payload['count']} msg")
        lines.append(f"• {count_label} → <@{uid}>")
    return "\n".join(lines)


def register_attivita(
    attivita_group: app_commands.Group,
    ctx: CommandContext,
    *,
    root_top_level: str = "attivita",
    locale: str = "it",
) -> None:
    is_english = locale == "en"
    command_names = {
        "today": "today" if is_english else "oggi",
        "yesterday": "yesterday" if is_english else "ieri",
        "last": "last" if is_english else "ultimi",
        "range": "range",
    }
    async def _send_standard(
        interaction: discord.Interaction,
        *,
        subcommand_path: str,
        subtitle_args: list[object] | None = None,
        lines: list[tuple[str, object]] | None = None,
        sections: list[CommandEmbedSection] | None = None,
        kind: str = "info",
        files: list[discord.File] | None = None,
    ) -> None:
        await send_standard_response(
            interaction,
            top_level=root_top_level,
            subcommand_path=subcommand_path,
            visual_top_level=root_top_level,
            subtitle_args=subtitle_args,
            lines=lines,
            sections=sections,
            kind=kind,
            footer_service=ctx.footer,
            files=files,
        )

    async def _send_dm_status(interaction: discord.Interaction, *, subcommand_path: str, status: str) -> None:
        messages = {
            "guild_only": ("error", [("error", "Comando disponibile solo nei server.")]),
            "dm_sent": ("success", [("result", "Ti ho inviato il resoconto attività in DM ✅")]),
            "dm_forbidden": ("error", [("error", "Non posso inviarti DM. Abilita i DM dal server e riprova.")]),
            "dm_unavailable": ("error", [("error", "Non riesco a inviarti il report in DM al momento. Riprova tra poco.")]),
        }
        kind, lines = messages[status]
        await _send_standard(interaction, subcommand_path=subcommand_path, lines=lines, kind=kind)

    async def _send_activity_report(
        interaction: discord.Interaction,
        window,
        utente: discord.Member | None = None,
        *,
        subcommand_path: str,
        subtitle_args: list[object] | None = None,
    ) -> None:
        if not await check_permission(interaction, "attivita.dm", ctx):
            return
        if not interaction.guild_id or not interaction.channel_id or not interaction.guild or not interaction.channel:
            await _send_standard(interaction, subcommand_path=subcommand_path, subtitle_args=subtitle_args, lines=[("error", "Comando disponibile solo nei server.")], kind="error")
            return

        start_ts = window.start_dt.astimezone(timezone.utc).isoformat()
        end_ts = window.end_dt.astimezone(timezone.utc).isoformat()
        if utente is None:
            channel = interaction.channel
            candidate_user_ids: list[int] = []
            for member in interaction.guild.members:
                if member.bot:
                    continue
                if channel.permissions_for(member).view_channel:
                    candidate_user_ids.append(member.id)
            details = await ctx.activity_insights.compute_activity_for_channel(
                str(interaction.guild_id),
                str(interaction.channel_id),
                start_ts,
                end_ts,
                candidate_user_ids=candidate_user_ids,
                inactive_threshold=1,
            )
            channel_name = getattr(interaction.channel, "name", str(interaction.channel_id))
            embeds = apply_standard_report_style(build_activity_dm_embeds(
                interaction.guild,
                str(interaction.guild_id),
                str(interaction.channel_id),
                channel_name,
                window.label_periodo,
                details,
                reference_ts=end_ts,
            ), service_name="attivita", canonical_top_level_command="dmserversummary", cover_title="📈 REPORT ATTIVITÀ")
            txt_payload = build_activity_details_txt(
                interaction.guild,
                interaction.guild.name,
                str(interaction.guild_id),
                channel_name,
                str(interaction.channel_id),
                window.label_periodo,
                start_ts,
                end_ts,
                details,
                reference_ts=end_ts,
            )
            filename = f"attivita_dettagli_{_safe_filename(channel_name)}_{window.start_dt.strftime('%Y%m%d_%H%M')}_{window.end_dt.strftime('%Y%m%d_%H%M')}.txt"
            txt_file = discord.File(io.BytesIO(txt_payload.encode("utf-8")), filename=filename)
            try:
                await interaction.user.send(embeds=embeds, file=txt_file)
                await _send_standard(interaction, subcommand_path=subcommand_path, subtitle_args=subtitle_args, lines=[("result", "Ti ho inviato il resoconto attività in DM ✅")], kind="success")
            except Forbidden:
                await _send_standard(interaction, subcommand_path=subcommand_path, subtitle_args=subtitle_args, lines=[("error", "Non posso inviarti DM. Abilita i DM dal server e riprova.")], kind="error")
            return

        enabled_channels = await ctx.database.list_enabled_activity_channels(str(interaction.guild_id))
        channel_ids = enabled_channels or None
        messages = await ctx.database.fetch_user_messages_in_range(str(interaction.guild_id), str(utente.id), start_ts, end_ts, channel_ids=channel_ids)
        prev_start = (window.start_dt - (window.end_dt - window.start_dt)).astimezone(timezone.utc).isoformat()
        curr_count = len(messages)
        prev_count = await ctx.database.count_user_messages_in_range(str(interaction.guild_id), str(utente.id), prev_start, start_ts, channel_ids=channel_ids)
        distinct_hours = len({_parse_ts(m["ts"]).astimezone(ROME_TZ).replace(minute=0, second=0, microsecond=0) for m in messages if _parse_ts(m["ts"])})
        distinct_channels = len({m["channel_id"] for m in messages if m.get("channel_id")})
        score = min(100, int(round(min(1.0, curr_count / max(1, prev_count or 10)) * 60 + min(1.0, distinct_hours / 24) * 30 + min(1.0, distinct_channels / 5) * 10)))
        emoji, label = _score_label(score)
        trend_text = _trend(curr_count, prev_count)

        last = messages[-1] if messages else None
        last_dt = _parse_ts(last["ts"]) if last else None

        multi_day = window.start_dt.astimezone(ROME_TZ).date() != window.end_dt.astimezone(ROME_TZ).date()
        peak_label, peak_channel_id, peak_message_id = _compute_peak(messages, multi_day)

        channel_counts = Counter([m["channel_id"] for m in messages if m.get("channel_id")])
        top_channel_id = sorted(channel_counts.items(), key=lambda item: (-item[1], item[0]))[0][0] if channel_counts else None

        channel_hours: dict[str, set[str]] = defaultdict(set)
        for m in messages:
            dt = _parse_ts(m["ts"])
            if dt and m.get("channel_id"):
                channel_hours[m["channel_id"]].add(dt.astimezone(ROME_TZ).strftime("%Y-%m-%d %H"))

        combo_channel_id, combo_hours = (None, 0)
        if channel_hours:
            combo_channel_id, combo_set = sorted(channel_hours.items(), key=lambda item: (-len(item[1]), item[0]))[0]
            combo_hours = len(combo_set)

        visible_ids: set[str] = set()
        for channel in interaction.guild.channels:
            if isinstance(channel, discord.abc.GuildChannel) and not isinstance(channel, discord.Thread) and channel.permissions_for(utente).view_channel:
                visible_ids.add(str(channel.id))
        visible_counts = {cid: count for cid, count in channel_counts.items() if cid in visible_ids and count > 0}
        bottom_channel_id = sorted(visible_counts.items(), key=lambda item: (item[1], item[0]))[0][0] if visible_counts else None

        bot_ids = {m.id for m in interaction.guild.members if m.bot}
        refs = {m["reply_to_message_id"] for m in messages if m.get("reply_to_message_id")}
        reply_author_map: dict[str, int] = {}
        for ref in refs:
            if not ref:
                continue
            author = await ctx.database.fetch_message_author_id(str(interaction.guild_id), ref)
            if author and str(author).isdigit():
                reply_author_map[ref] = int(author)
        interactions = _build_interactions(messages, reply_author_map, bot_ids, utente.id)
        top_interactions = _format_interactions(interactions)

        themes, top_words = _words_and_themes(messages)
        advice = [
            f"Punta su {fmt_channel_compact(interaction.guild, top_channel_id)} nelle fasce in cui è più attivo." if top_channel_id else "Punta sui canali in cui è già più attivo.",
            "Stimola reply/mention verso utenti poco coinvolti per ampliare il network.",
            f"Trend attuale: {trend_text.lower()}",
        ][:4]
        advice = [_truncate(line, 500) for line in advice]

        def jump(channel_id: str | None, message_id: str | None) -> str | None:
            if not channel_id or not message_id:
                return None
            return f"https://discord.com/channels/{interaction.guild_id}/{channel_id}/{message_id}"

        stats_lines = [
            (
                f"• 💬 Ultimo messaggio: [{b(last_dt.astimezone(ROME_TZ).strftime('%d/%m %H:%M'))}]({jump(last.get('channel_id') if last else None, last.get('message_id') if last else None)}) "
                f"🕒 <t:{int(last_dt.timestamp())}:R> in {fmt_channel_compact(interaction.guild, last.get('channel_id') if last else None)}"
            )
            if last and last_dt
            else "• 💬 Ultimo messaggio: —",
            (
                f"• 🔥 Momento di maggiore attività: [{b(peak_label)}]({jump(peak_channel_id, peak_message_id)}) in {fmt_channel_compact(interaction.guild, peak_channel_id)}"
                if peak_label != "—"
                else "• 🔥 Momento di maggiore attività: —"
            ),
            f"• 💤 Momento di maggior silenzio: {b(_silent_hour(messages))}",
            f"• 👥 Canale in cui partecipa maggiormente: {fmt_channel_compact(interaction.guild, top_channel_id)}" if top_channel_id else "• 👥 Canale in cui partecipa maggiormente: —",
            f"• 🌡️ Combo oraria: {b(f'{combo_hours} ore')} di attività in {fmt_channel_compact(interaction.guild, combo_channel_id)}" if combo_channel_id else "• 🌡️ Combo oraria: —",
            f"• 💘 Preferisce maggiormente: {fmt_channel_compact(interaction.guild, top_channel_id)} + frequenta {b(f'{len(channel_hours.get(top_channel_id, set())) if top_channel_id else 0} ore')}" if top_channel_id else "• 💘 Preferisce maggiormente: —",
            f"• 💔 Frequenta di meno: {fmt_channel_compact(interaction.guild, bottom_channel_id)}" if bottom_channel_id else "• 💔 Frequenta di meno: —",
        ]
        interaction_lines = [_truncate(top_interactions, 700)]
        topics_lines = [
            f"- Temi: {_join_limited(themes, max_items=5, max_chars=250)}",
            f"- Parole: {_join_limited(top_words, max_items=10, max_chars=200)}",
        ]

        embeds, should_attach_txt = _build_user_activity_embeds_safe(
            display_name=utente.display_name,
            period_label=window.label_periodo,
            emoji=emoji,
            label=label,
            score=score,
            trend_text=trend_text,
            stats_lines=stats_lines,
            interaction_lines=interaction_lines,
            topics_lines=topics_lines,
            advice_lines=advice,
        )
        embeds = apply_standard_report_style(
            embeds,
            service_name="attivita",
            canonical_top_level_command="dmserversummary",
            cover_title=f"📈 REPORT ATTIVITÀ — {utente.display_name}",
        )
        txt_payload = _make_user_report_txt(utente.display_name, window.label_periodo, stats_lines, interaction_lines, topics_lines, advice)
        txt_file = None
        if should_attach_txt:
            period_slug = _safe_filename(window.label_periodo)
            txt_file = discord.File(io.BytesIO(txt_payload.encode("utf-8")), filename=f"attivita_{utente.id}_{period_slug}.txt")

        try:
            await interaction.user.send(embeds=embeds)
            await _send_standard(interaction, subcommand_path=subcommand_path, subtitle_args=subtitle_args, lines=[("result", "Ti ho inviato il resoconto attività in DM ✅")], kind="success")
        except Forbidden:
            await _send_standard(interaction, subcommand_path=subcommand_path, subtitle_args=subtitle_args, lines=[("error", "Non posso inviarti DM. Abilita i DM dal server e riprova.")], kind="error")
        except discord.HTTPException as exc:
            logger.exception("Errore invio DM report utente attivita guild=%s user=%s", interaction.guild_id, utente.id)
            if exc.status == 400 and ("50035" in str(exc) or "Invalid Form Body" in str(exc)):
                fallback = discord.Embed(title=format_standard_title(f"STATO ATTIVITÀ “{utente.display_name}”", emoji="🗣️"), color=discord.Color.dark_grey())
                fallback.description = _truncate(
                    f"🕒 **{window.label_periodo}**\n\n{emoji} **ATTIVITÀ {label}**\n🫀 **PUNTI ATTIVITÀ** {b(f'{score}/100')}\n📈 {trend_text}\n\nDettagli completi nel file allegato.",
                    3000,
                )
                attach_footer_meta(fallback, service_name="attivita", used_local_processing=True)
                try:
                    period_slug = _safe_filename(window.label_periodo)
                    fallback_file = discord.File(io.BytesIO(txt_payload.encode("utf-8")), filename=f"attivita_{utente.id}_{period_slug}.txt")
                    await interaction.user.send(embed=fallback, file=fallback_file)
                    await _send_standard(interaction, subcommand_path=subcommand_path, subtitle_args=subtitle_args, lines=[("result", "Ti ho inviato il resoconto attività in DM ✅")], kind="success")
                except Forbidden:
                    await _send_standard(interaction, subcommand_path=subcommand_path, subtitle_args=subtitle_args, lines=[("error", "Non posso inviarti DM. Abilita i DM dal server e riprova.")], kind="error")
                except discord.HTTPException:
                    await _send_standard(interaction, subcommand_path=subcommand_path, subtitle_args=subtitle_args, lines=[("error", "Non riesco a inviarti il report in DM al momento. Riprova tra poco.")], kind="error")
            else:
                await _send_standard(interaction, subcommand_path=subcommand_path, subtitle_args=subtitle_args, lines=[("error", "Non riesco a inviarti il report in DM al momento. Riprova tra poco.")], kind="error")

    if is_english:
        async def _set_activity_toggle(interaction: discord.Interaction, action: str) -> None:
            if not await check_permission(interaction, f"admin.{root_top_level}.activity.{action}", ctx):
                return
            if interaction.guild_id is None or interaction.channel_id is None:
                await _send_standard(interaction, subcommand_path=f"{root_top_level} activity {action}", lines=[("error", "Comando disponibile solo nei server.")], kind="error")
                return
            guild_id = str(interaction.guild_id)
            channel_id = str(interaction.channel_id)
            if action == "status":
                enabled = await ctx.database.get_activity_channel_status(guild_id, channel_id)
                await _send_standard(interaction, subcommand_path=f"{root_top_level} activity status", lines=[("status", "on" if enabled else "off")], kind="info")
                return
            enabled = action == "on"
            await ctx.database.set_activity_channel_enabled(guild_id, channel_id, enabled)
            await _send_standard(
                interaction,
                subcommand_path=f"{root_top_level} activity {action}",
                lines=[("result", f"Activity summary {'enabled' if enabled else 'disabled'} for this channel.")],
                kind="success",
            )

        @attivita_group.command(name="on", description="Enable activity summary in this channel.")
        async def attivita_on(interaction: discord.Interaction) -> None:
            await _set_activity_toggle(interaction, "on")

        @attivita_group.command(name="off", description="Disable activity summary in this channel.")
        async def attivita_off(interaction: discord.Interaction) -> None:
            await _set_activity_toggle(interaction, "off")

        @attivita_group.command(name="status", description="Show activity summary status in this channel.")
        async def attivita_status(interaction: discord.Interaction) -> None:
            await _set_activity_toggle(interaction, "status")

    @attivita_group.command(name=command_names["today"], description="Report attività di oggi (DM staff)")
    @app_commands.describe(utente="Utente da analizzare (opzionale)")
    @app_commands.rename(utente="user" if is_english else "utente")
    async def attivita_oggi(interaction: discord.Interaction, utente: discord.Member | None = None) -> None:
        await _send_activity_report(interaction, resolve_oggi_window(), utente, subcommand_path="attivita oggi", subtitle_args=[utente] if utente is not None else None)

    @attivita_group.command(name=command_names["yesterday"], description="Report attività di ieri (DM staff)")
    @app_commands.describe(utente="Utente da analizzare (opzionale)")
    @app_commands.rename(utente="user" if is_english else "utente")
    async def attivita_ieri(interaction: discord.Interaction, utente: discord.Member | None = None) -> None:
        await _send_activity_report(interaction, resolve_ieri_window(), utente, subcommand_path="attivita ieri", subtitle_args=[utente] if utente is not None else None)

    @attivita_group.command(name=command_names["last"], description="Report attività ultimi N periodi")
    @app_commands.describe(quantita="Numero di unità", unita="Unità di tempo", utente="Utente da analizzare (opzionale)")
    @app_commands.rename(
        quantita="quantity" if is_english else "quantità",
        unita="unit" if is_english else "unità",
        utente="user" if is_english else "utente",
    )
    @app_commands.choices(
        unita=[
            app_commands.Choice(name="minuti", value="minuti"),
            app_commands.Choice(name="ore", value="ore"),
            app_commands.Choice(name="giorni", value="giorni"),
            app_commands.Choice(name="settimane", value="settimane"),
        ]
    )
    async def attivita_ultimi(
        interaction: discord.Interaction, quantita: int, unita: app_commands.Choice[str], utente: discord.Member | None = None
    ) -> None:
        window, error = resolve_ultimi_window(quantita, unita.value, ctx.config)
        if error:
            await _send_standard(interaction, subcommand_path="attivita ultimi", subtitle_args=[quantita, unita], lines=[("error", error)], kind="error")
            return
        assert window is not None
        subtitle_args = [quantita, unita]
        if utente is not None:
            subtitle_args.append(utente)
        await _send_activity_report(interaction, window, utente, subcommand_path="attivita ultimi", subtitle_args=subtitle_args)

    @attivita_group.command(name=command_names["range"], description="Report attività per range custom")
    @app_commands.describe(da="Da (DD/MM/YYYY HH:MM)", a="A (DD/MM/YYYY HH:MM)", utente="Utente da analizzare (opzionale)")
    @app_commands.rename(da="from" if is_english else "da", a="to" if is_english else "a", utente="user" if is_english else "utente")
    async def attivita_range(interaction: discord.Interaction, da: str, a: str, utente: discord.Member | None = None) -> None:
        window, error = resolve_range_window(da, a, ctx.config)
        if error:
            await _send_standard(interaction, subcommand_path="attivita range", subtitle_args=[da, a], lines=[("error", error)], kind="error")
            return
        assert window is not None
        subtitle_args = [da, a]
        if utente is not None:
            subtitle_args.append(utente)
        await _send_activity_report(interaction, window, utente, subcommand_path="attivita range", subtitle_args=subtitle_args)
