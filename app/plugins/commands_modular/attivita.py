from __future__ import annotations

import io
import json
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
from discord import Forbidden, app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.time_windows import resolve_ieri_window, resolve_oggi_window, resolve_range_window, resolve_ultimi_window
from app.renderers.activity_dm_renderer import build_activity_details_txt, build_activity_dm_embeds
from app.renderers.user_activity_renderer import build_user_activity_embeds

logger = logging.getLogger(__name__)
ROME_TZ = ZoneInfo("Europe/Rome")
MENTION_RE = re.compile(r"<@!?(\d+)>")
STOPWORDS_IT = {
    "che", "per", "con", "non", "una", "del", "della", "delle", "degli", "sono", "alla", "dopo", "come", "anche", "solo", "sono",
    "nel", "nella", "nelle", "degli", "gli", "dei", "dai", "dalle", "all", "questo", "quello", "quella", "oggi", "ieri", "domani",
}


def _safe_filename(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.lower())
    return safe.strip("_") or "canale"


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
    return f"Messaggi {direction} ({percent:+d}% vs finestra precedente)."


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
    for m in messages:
        content = (m.get("content") or "").lower()
        tokens = re.findall(r"[a-zàèéìòù0-9]{3,}", content)
        for tok in tokens:
            if tok in STOPWORDS_IT:
                continue
            words[tok] += 1
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


def _format_interactions(interactions: dict[int, dict[str, object]], guild: discord.Guild, bottom: bool = False) -> str:
    if not interactions:
        return "—"
    ordered = sorted(interactions.items(), key=lambda item: (item[1]["count"], item[0]))
    if not bottom:
        ordered = sorted(interactions.items(), key=lambda item: (-item[1]["count"], item[0]))
    lines: list[str] = []
    for uid, payload in ordered[:3]:
        channels = payload["channels"].most_common(2)  # type: ignore[union-attr]
        channel_names = []
        for ch_id, _ in channels:
            ch = guild.get_channel(int(ch_id)) if str(ch_id).isdigit() else None
            channel_names.append(f"#{getattr(ch, 'name', ch_id)}")
        lines.append(f"{payload['count']} msg → <@{uid}> (in {', '.join(channel_names) if channel_names else '—'})")
    return ", ".join(lines)


def register_attivita(attivita_group: app_commands.Group, ctx: CommandContext) -> None:
    async def _send_activity_report(interaction: discord.Interaction, window, utente: discord.Member | None = None) -> None:
        if not await check_permission(interaction, "attivita.dm", ctx):
            return
        if not interaction.guild_id or not interaction.channel_id or not interaction.guild or not interaction.channel:
            await interaction.response.send_message("Comando disponibile solo nei server.", ephemeral=True)
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
            embeds = build_activity_dm_embeds(
                interaction.guild,
                str(interaction.guild_id),
                str(interaction.channel_id),
                channel_name,
                window.label_periodo,
                details,
                reference_ts=end_ts,
            )
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
                await interaction.response.send_message("Ti ho inviato il resoconto attività in DM ✅", ephemeral=True)
            except Forbidden:
                await interaction.response.send_message("❌ Non posso inviarti DM. Abilita i DM dal server e riprova.", ephemeral=True)
            return

        enabled_channels = await ctx.database.list_enabled_activity_channels(str(interaction.guild_id))
        channel_ids = enabled_channels or None
        messages = await ctx.database.fetch_user_messages_in_range(str(interaction.guild_id), str(utente.id), start_ts, end_ts, channel_ids=channel_ids)
        prev_start = (window.start_dt - (window.end_dt - window.start_dt)).astimezone(timezone.utc).isoformat()
        curr_count = len(messages)
        prev_count = await ctx.database.count_user_messages_in_range(
            str(interaction.guild_id), str(utente.id), prev_start, start_ts, channel_ids=channel_ids
        )
        distinct_hours = len({_parse_ts(m["ts"]).astimezone(ROME_TZ).replace(minute=0, second=0, microsecond=0) for m in messages if _parse_ts(m["ts"])})
        distinct_channels = len({m["channel_id"] for m in messages if m.get("channel_id")})
        score = min(100, int(round(min(1.0, curr_count / max(1, prev_count or 10)) * 60 + min(1.0, distinct_hours / 24) * 30 + min(1.0, distinct_channels / 5) * 10)))
        emoji, label = _score_label(score)
        trend_text = _trend(curr_count, prev_count)

        last = messages[-1] if messages else None
        last_dt = _parse_ts(last["ts"]) if last else None
        last_channel = interaction.guild.get_channel(int(last["channel_id"])) if last and last.get("channel_id") else None

        multi_day = window.start_dt.astimezone(ROME_TZ).date() != window.end_dt.astimezone(ROME_TZ).date()
        peak_label, peak_channel_id, peak_message_id = _compute_peak(messages, multi_day)
        peak_channel = interaction.guild.get_channel(int(peak_channel_id)) if peak_channel_id and peak_channel_id.isdigit() else None

        channel_counts = Counter([m["channel_id"] for m in messages if m.get("channel_id")])
        top_channel_id = sorted(channel_counts.items(), key=lambda item: (-item[1], item[0]))[0][0] if channel_counts else None
        top_channel = interaction.guild.get_channel(int(top_channel_id)) if top_channel_id and top_channel_id.isdigit() else None

        channel_hours: dict[str, set[str]] = defaultdict(set)
        for m in messages:
            dt = _parse_ts(m["ts"])
            if dt and m.get("channel_id"):
                channel_hours[m["channel_id"]].add(dt.astimezone(ROME_TZ).strftime("%Y-%m-%d %H"))

        combo_channel_id, combo_hours = (None, 0)
        if channel_hours:
            combo_channel_id, combo_set = sorted(channel_hours.items(), key=lambda item: (-len(item[1]), item[0]))[0]
            combo_hours = len(combo_set)
        combo_channel = interaction.guild.get_channel(int(combo_channel_id)) if combo_channel_id and combo_channel_id.isdigit() else None

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
        top_interactions = _format_interactions(interactions, interaction.guild, bottom=False)
        bottom_interactions = _format_interactions(interactions, interaction.guild, bottom=True)

        themes, top_words = _words_and_themes(messages)
        advice = [
            f"Punta su {getattr(top_channel, 'name', '—')} nelle fasce in cui è più attivo.",
            "Stimola reply/mention verso utenti poco coinvolti per ampliare il network.",
            f"Trend attuale: {trend_text.lower()}",
        ][:3]

        def jump(channel_id: str | None, message_id: str | None) -> str | None:
            if not channel_id or not message_id:
                return None
            return f"https://discord.com/channels/{interaction.guild_id}/{channel_id}/{message_id}"

        stats = [
            (
                f"• 💬 Ultimo messaggio: [{last_dt.astimezone(ROME_TZ).strftime('%d/%m %H:%M')}]({jump(last.get('channel_id') if last else None, last.get('message_id') if last else None)}) "
                f"🕒 <t:{int(last_dt.timestamp())}:R> in \"{getattr(last_channel, 'name', '—')}\""
            )
            if last and last_dt
            else "• 💬 Ultimo messaggio: —",
            (
                f"• 🔥 Momento di maggiore attività: [{peak_label}]({jump(peak_channel_id, peak_message_id)}) in \"{getattr(peak_channel, 'name', '—')}\""
                if peak_label != "—"
                else "• 🔥 Momento di maggiore attività: —"
            ),
            f"• 💤 Momento di maggior silenzio: {_silent_hour(messages)}",
            f"• 👥 Canale in cui partecipa maggiormente: \"{getattr(top_channel, 'name', '—')}\"",
            f"• 🌡️ Combo oraria: {combo_hours} ore di attività in \"{getattr(combo_channel, 'name', '—')}\"",
            f"• 💘 Preferisce maggiormente: \"{getattr(top_channel, 'name', '—')}\" + frequenta {len(channel_hours.get(top_channel_id, set())) if top_channel_id else 0} ore",
            f"• 💔 Frequenta di meno: \"{getattr(interaction.guild.get_channel(int(bottom_channel_id)), 'name', '—') if bottom_channel_id and bottom_channel_id.isdigit() else '—'}\"",
            f"• 🧑‍🤝‍🧑 Con chi interagisce di più: {top_interactions}",
            f"• 🤼 Con chi interagisce di meno: {bottom_interactions}",
            f"• 🔍 Temi discussi di più: {', '.join(themes[:5]) if themes else '—'}",
            f"• 👁️‍🗨️ Parole usate di più: {', '.join(top_words[:10]) if top_words else '—'}",
        ]

        embeds = build_user_activity_embeds(
            guild_id=str(interaction.guild_id),
            display_name=utente.display_name,
            period_label=window.label_periodo,
            activity_label=label,
            activity_emoji=emoji,
            score=score,
            trend_text=trend_text,
            overview_description="Ritmo dell'utente valutato su volume, continuità e presenza nei canali.",
            stats_lines=stats,
            advice_lines=advice,
        )
        try:
            await interaction.user.send(embeds=embeds)
            await interaction.response.send_message("Ti ho inviato il resoconto attività in DM ✅", ephemeral=True)
        except Forbidden:
            await interaction.response.send_message("❌ Non posso inviarti DM. Abilita i DM dal server e riprova.", ephemeral=True)

    @attivita_group.command(name="oggi", description="Report attività di oggi (DM staff)")
    @app_commands.describe(utente="Utente da analizzare (opzionale)")
    async def attivita_oggi(interaction: discord.Interaction, utente: discord.Member | None = None) -> None:
        await _send_activity_report(interaction, resolve_oggi_window(), utente)

    @attivita_group.command(name="ieri", description="Report attività di ieri (DM staff)")
    @app_commands.describe(utente="Utente da analizzare (opzionale)")
    async def attivita_ieri(interaction: discord.Interaction, utente: discord.Member | None = None) -> None:
        await _send_activity_report(interaction, resolve_ieri_window(), utente)

    @attivita_group.command(name="ultimi", description="Report attività ultimi N minuti/ore/giorni/settimane")
    @app_commands.describe(quantita="Numero di unità", unita="Unità di tempo", utente="Utente da analizzare (opzionale)")
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
            await interaction.response.send_message(error, ephemeral=True)
            return
        assert window is not None
        await _send_activity_report(interaction, window, utente)

    @attivita_group.command(name="range", description="Report attività per range custom")
    @app_commands.describe(da="Da (DD/MM/YYYY HH:MM)", a="A (DD/MM/YYYY HH:MM)", utente="Utente da analizzare (opzionale)")
    async def attivita_range(interaction: discord.Interaction, da: str, a: str, utente: discord.Member | None = None) -> None:
        window, error = resolve_range_window(da, a, ctx.config)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        assert window is not None
        await _send_activity_report(interaction, window, utente)
