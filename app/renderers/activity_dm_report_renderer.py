from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import discord

from app.services.author import attach_author_meta, attach_author_meta_to_all
from app.services.embed_images import attach_embed_images_meta, attach_embed_images_meta_to_all
from app.services.footer import attach_footer_meta
from app.shared.discord.embed_body import format_standard_field_name, format_standard_title

from app.services.activity_insights import ChannelActivityDetails, UserActivityEntry

ROME_TZ = ZoneInfo("Europe/Rome")
MAX_LIST_ROWS = 10
FIELD_VALUE_MAX = 1024
FIELD_NAME_MAX = 256
CHUNK_SUFFIX = "… (vedi .txt)"
MAX_FIELDS_PER_EMBED = 25
ZWSP = "​"
DETAIL_TITLE = format_standard_title("DETTAGLI ATTIVITÀ — Staff", emoji="📄")


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


def _label_inactive_dm(*, guild: discord.Guild, user_id: int) -> str:
    return _display_name_for_id(guild=guild, user_id=user_id)


def _rank_badge(i: int) -> str:
    if i == 1:
        return "🥇"
    if i == 2:
        return "🥈"
    if i == 3:
        return "🥉"
    mapping = {4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟"}
    return mapping.get(i, f"{i}.")


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
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _fmt_ts(ts: str | None, *, hour_bucket: bool = False) -> str:
    dt = _parse_iso(ts)
    if not dt:
        return "—"
    local = dt.astimezone(ROME_TZ)
    if hour_bucket:
        local = local.replace(minute=0, second=0, microsecond=0)
    return local.strftime("%d/%m %H:%M")


def _human_delta(ts: str | None, reference_ts: str | None) -> str:
    dt = _parse_iso(ts)
    if not dt:
        return "n/d"
    ref = _parse_iso(reference_ts) if reference_ts else datetime.now(timezone.utc)
    if ref is None:
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


def _chunk_blocks(blocks: list[str], *, max_len: int = FIELD_VALUE_MAX) -> list[str]:
    if not blocks:
        return ["—"]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for block in blocks:
        safe_block = _truncate_line(block, max_len, CHUNK_SUFFIX)
        add_len = len(safe_block) + (2 if current else 0)
        if current and current_len + add_len > max_len:
            chunks.append("\n\n".join(current))
            current = [safe_block]
            current_len = len(safe_block)
            continue
        current.append(safe_block)
        current_len += add_len
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _format_active_block(
    idx: int,
    user: UserActivityEntry,
    *,
    guild: discord.Guild,
    guild_id: str,
    channel_id: str,
    reference_ts: str,
    include_peak_day: bool,
) -> str:
    badge = _rank_badge(idx)
    first = _fmt_ts_with_link(user.last_ts_in_range, guild_id, channel_id, user.last_message_id_in_range, markdown=True)
    row1 = f"{badge} **<@{user.user_id}>** (**{user.count_in_range} msg**) | 💬 Ultimo: {first} 🕒 {_human_delta(user.last_ts_in_range, reference_ts)}"

    peak_link = _fmt_ts_with_link(user.peak_hour_ts, guild_id, channel_id, user.peak_message_id, markdown=True, hour_bucket=True)
    row2 = f"  🔥 Picco: {peak_link} ({user.peak_count} msg)"
    if include_peak_day and user.peak_day_date_local and user.peak_day_count > 0:
        row2 += f" | 📆 Giorno: {user.peak_day_date_local} ({user.peak_day_count} msg)"
    return f"{row1}\n{row2}"


def _format_inactive_line(
    idx: int,
    user: UserActivityEntry,
    *,
    guild: discord.Guild,
    guild_id: str,
    channel_id: str,
    reference_ts: str,
) -> str:
    name = _display_name_for_id(guild=guild, user_id=user.user_id)
    badge = _rank_badge(idx)
    if user.last_ts_channel:
        last = _fmt_ts_with_link(user.last_ts_channel, guild_id, channel_id, user.last_message_id_channel, markdown=True)
        return f"{badge} **{name}** (**0 msg**) | 💬 Ultimo: {last} 🕒 {_human_delta(user.last_ts_channel, reference_ts)}"
    return f"{badge} **{name}** (**0 msg**) (mai partecipato dall'ingresso 🥀)"


def _apply_limit(items: list[UserActivityEntry]) -> tuple[list[UserActivityEntry], int]:
    if len(items) <= MAX_LIST_ROWS:
        return items, 0
    return items[:MAX_LIST_ROWS], len(items) - MAX_LIST_ROWS


def _ensure_field(embeds: list[discord.Embed], title_base: str, value: str) -> None:
    safe_value = value if len(value) <= FIELD_VALUE_MAX else _truncate_line(value, FIELD_VALUE_MAX, CHUNK_SUFFIX)
    if len(embeds[-1].fields) >= MAX_FIELDS_PER_EMBED:
        idx = len([e for e in embeds if e.title.startswith(format_standard_title("DETTAGLI ATTIVITÀ — Staff", emoji="📄"))]) + 1
        new_embed = discord.Embed(title=format_standard_title(f"DETTAGLI ATTIVITÀ — Staff ({idx}/?)", emoji="📄"), color=discord.Color.dark_grey())
        attach_footer_meta(new_embed, service_name="activity_dm", used_local_processing=True)
        embeds.append(new_embed)
    embeds[-1].add_field(name=format_standard_field_name(title_base)[:FIELD_NAME_MAX], value=safe_value, inline=False)


def _add_chunked_field(
    embeds: list[discord.Embed],
    title: str,
    value: str,
    *,
    continuation_name: str | None = None,
    leading_blank_first: bool = False,
) -> None:
    parts = _chunk_lines([value]) if len(value) > FIELD_VALUE_MAX else [value]
    if leading_blank_first and parts:
        parts[0] = "\n" + parts[0]
    if len(parts) == 1:
        _ensure_field(embeds, title, parts[0])
        return
    cont = continuation_name if continuation_name is not None else title
    _ensure_field(embeds, title, parts[0])
    for part in parts[1:]:
        _ensure_field(embeds, cont, part)


def _add_block_field(
    embeds: list[discord.Embed],
    title: str,
    blocks: list[str],
    *,
    continuation_name: str | None = None,
    leading_blank_first: bool = False,
) -> None:
    chunks = _chunk_blocks(blocks)
    if leading_blank_first and chunks:
        chunks[0] = "\n" + chunks[0]
    if len(chunks) == 1:
        _ensure_field(embeds, title, chunks[0])
        return
    cont = continuation_name if continuation_name is not None else title
    _ensure_field(embeds, title, chunks[0])
    for chunk in chunks[1:]:
        _ensure_field(embeds, cont, chunk)


def _finalize_detail_titles(embeds: list[discord.Embed]) -> None:
    detail = [e for e in embeds if e.title.startswith(format_standard_title("DETTAGLI ATTIVITÀ — Staff", emoji="📄"))]
    if not detail:
        return
    for emb in detail:
        emb.title = DETAIL_TITLE


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
        f"SEZIONE A — TOP ATTIVI ({details.score.active_users_count} attivi su {details.candidates_total} utenti totali)",
    ]
    for idx, user in enumerate(details.top_active_users, start=1):
        name = _display_name_for_id(guild=guild, user_id=user.user_id)
        lines.append(
            f"{idx}. <@{user.user_id}> ({name}, id={user.user_id}) — {user.count_in_range} msg | "
            f"ultimo: {_fmt_ts_with_link(user.last_ts_in_range, guild_id, channel_id, user.last_message_id_in_range, markdown=False)} | "
            f"picco: {_fmt_ts_with_link(user.peak_hour_ts, guild_id, channel_id, user.peak_message_id, markdown=False, hour_bucket=True)} ({user.peak_count} msg)"
        )
    inactive_total = max(0, details.candidates_total - details.score.active_users_count)
    lines.extend(["", f"SEZIONE B — INATTIVI NEL PERIODO ({inactive_total} inattivi su {details.candidates_total} utenti totali)"])
    for idx, user in enumerate(details.inactive_users, start=1):
        name = _display_name_for_id(guild=guild, user_id=user.user_id)
        if user.last_ts_channel:
            lines.append(
                f"{idx}. <@{user.user_id}> ({name}, id={user.user_id}) — 0 msg | "
                f"ultimo: {_fmt_ts_with_link(user.last_ts_channel, guild_id, channel_id, user.last_message_id_channel, markdown=False)} | "
                f"{_human_delta(user.last_ts_channel, reference_ts)}"
            )
        else:
            lines.append(f"{idx}. <@{user.user_id}> ({name}, id={user.user_id}) — 0 msg | mai visto")
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
    status = discord.Embed(title=format_standard_title(f"STATO ATTIVITÀ “#{channel_name}”", emoji="🗣️"), color=_color_for_label(s.label))
    status.description = "Snapshot sintetico dell'attività canale nel periodo selezionato."
    status.add_field(name=format_standard_field_name("Periodo", emoji="🕒"), value=label_periodo, inline=False)
    status.add_field(
        name=format_standard_field_name("Stato attività", emoji=s.emoji),
        value=f"**ATTIVITÀ {s.label}**\nRitmo del canale valutato su volume, persone attive e continuità.",
        inline=False,
    )
    status.add_field(
        name=format_standard_field_name("Punti attività", emoji="🫀"),
        value=f"{_bar(s.score, s.emoji)} **({s.score}/100)**",
        inline=False,
    )
    status.add_field(name=format_standard_field_name("Trend", emoji="📈"), value=s.trend_text or "n/d", inline=False)
    attach_footer_meta(status, service_name="activity_dm", used_local_processing=True)
    attach_author_meta(status, service_name="activity_dm", canonical_top_level_command="dmsummary")
    attach_embed_images_meta(status, service_name="activity_dm")

    detail = discord.Embed(title=DETAIL_TITLE, color=discord.Color.dark_grey())
    attach_footer_meta(detail, service_name="activity_dm", used_local_processing=True)
    attach_author_meta(detail, service_name="activity_dm", canonical_top_level_command="dmsummary")
    attach_embed_images_meta(detail, service_name="activity_dm")
    embeds = [detail]

    _add_chunked_field(embeds, "📌 STATISTICHE CANALE", "\n".join(details.stats_lines or ["n/d"]))
    _add_chunked_field(embeds, "📈 TREND", details.score.trend_text or "n/d")

    top_items, top_over = _apply_limit(details.top_active_users)
    top_blocks = [
        _format_active_block(i + 1, item, guild=guild, guild_id=guild_id, channel_id=channel_id, reference_ts=reference_ts, include_peak_day=details.range_spans_multiple_days)
        for i, item in enumerate(top_items)
    ]
    if top_over > 0:
        top_blocks.append(f"… + altri {top_over} utenti")
    _add_block_field(embeds, "🏆 TOP 10 UTENTI PIÙ ATTIVI", top_blocks or ["—"], continuation_name=ZWSP, leading_blank_first=True)

    inactive_items, inactive_over = _apply_limit(details.inactive_users)
    never_seen = [item for item in inactive_items if item.last_ts_channel is None]
    seen = [item for item in inactive_items if item.last_ts_channel is not None]
    inactive_lines: list[str] = []
    if never_seen:
        names = ", ".join(_label_inactive_dm(guild=guild, user_id=item.user_id) for item in never_seen)
        inactive_lines.append(f"{_rank_badge(1)} {names}\n(**0 msg**) (mai partecipato dall'ingresso 🥀)")
        base_idx = 2
    else:
        base_idx = 1
    for idx, item in enumerate(seen, start=base_idx):
        inactive_lines.append(
            _format_inactive_line(idx, item, guild=guild, guild_id=guild_id, channel_id=channel_id, reference_ts=reference_ts)
        )
    if inactive_over > 0:
        inactive_lines.append(f"… + altri {inactive_over} utenti")
    _add_chunked_field(embeds, "💤 TOP 10 UTENTI INATTIVI", "\n\n".join(inactive_lines or ["—"]), continuation_name=ZWSP, leading_blank_first=True)

    _add_chunked_field(embeds, "💡 CONSIGLI", "\n".join(f"• {line}" for line in details.advice_bullets) or "• Nessun consiglio")
    _finalize_detail_titles(embeds)
    attach_author_meta_to_all(embeds, service_name="activity_dm", canonical_top_level_command="dmsummary")
    attach_embed_images_meta_to_all(embeds, service_name="activity_dm")
    return [status, *embeds]
