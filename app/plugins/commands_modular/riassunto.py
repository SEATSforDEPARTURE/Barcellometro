from __future__ import annotations

import io
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import discord
from discord import app_commands

from app.services.summary import SummaryImpact, SummaryItem, SummaryQuote
from app.utils.discord_send import send_dm_or_followup
from app.utils.embed_limits import (
    MAX_EMBED_CHARS,
    _clone_embed_shell,
    _ensure_embed_limits,
    _estimate_embed_size,
    _split_field_chunks,
    normalize_embeds_for_discord,
)
from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.settings import get_setting

logger = logging.getLogger(__name__)

ROME_TZ = ZoneInfo("Europe/Rome")


def register_riassunto(riassunto_group: app_commands.Group, ctx: CommandContext) -> None:
    async def send_ephemeral(interaction: discord.Interaction, message: str) -> None:
        ephemeral = interaction.guild_id is not None
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(message, ephemeral=ephemeral)

    def _render_health_bar(score: int, color_emoji: str) -> str:
        score = max(0, min(100, score))
        filled = int(round(score / 10))
        empty = max(0, 10 - filled)
        return f"{color_emoji * filled}{'⚪' * empty}"

    def _build_period_prefix(
        period_label: str,
        *,
        start_dt: datetime,
        end_dt: datetime,
        start_ts: str,
        end_ts: str,
    ) -> str:
        if period_label == "ieri":
            return "Ieri"
        if period_label == "oggi":
            return "Oggi"
        if period_label == "ultimi":
            delta = end_dt - start_dt
            if delta.days >= 7:
                weeks = max(1, int(round(delta.days / 7)))
                unit = "settimane" if weeks > 1 else "settimana"
                return f"Negli ultimi {weeks} {unit}"
            if delta.days >= 1:
                days = max(1, delta.days)
                unit = "giorni" if days > 1 else "giorno"
                return f"Negli ultimi {days} {unit}"
            hours = max(1, int(delta.total_seconds() // 3600))
            if hours >= 1:
                unit = "ore" if hours > 1 else "ora"
                return f"Negli ultimi {hours} {unit}"
            minutes = max(1, int(delta.total_seconds() // 60))
            unit = "minuti" if minutes > 1 else "minuto"
            return f"Negli ultimi {minutes} {unit}"
        if period_label == "range":
            start_label = _format_italian_ts(start_ts)
            end_label = _format_italian_ts(end_ts)
            return f"Tra {start_label} e {end_label}"
        return "Nel periodo indicato"

    def _local_period_description(prefix: str, color_label: str) -> str:
        color = (color_label or "nero").lower()
        mapping = {
            "verde": ("sano", "🙂"),
            "giallo": ("delicato", "😐"),
            "rosso": ("teso", "😟"),
            "nero": ("critico", "😨"),
        }
        adjective, emoji = mapping.get(color, ("critico", "😨"))
        return f"{prefix} il barcello è stato {adjective} {emoji}."

    def _with_spacing(text: str) -> str:
        return text

    def _add_section(embed: discord.Embed, *, name: str, value: str) -> None:
        chunks = _split_field_chunks(value, 1024)
        available = 25 - len(embed.fields)
        if available <= 0:
            return
        if len(chunks) > available:
            chunks = chunks[:available]
        for idx, chunk in enumerate(chunks):
            field_name = name if idx == 0 else f"{name} (cont.)"
            embed.add_field(name=field_name, value=chunk, inline=False)

    def _parse_hex_color(raw: str | None) -> int | None:
        if not raw:
            return None
        value = raw.strip().lower()
        if value.startswith("#"):
            value = value[1:]
        if value.startswith("0x"):
            value = value[2:]
        try:
            return int(value, 16)
        except ValueError:
            return None

    async def _get_details_embed_color(profile: str) -> int:
        default_color = 0x95A5A6
        mod_color = 0x5865F2
        admin_color = 0x9B59B6
        if profile == "admin":
            stored = await get_setting(ctx, "barcello.details_color_admin", "")
            return _parse_hex_color(stored) or admin_color
        if profile == "mod":
            stored = await get_setting(ctx, "barcello.details_color_mod", "")
            return _parse_hex_color(stored) or mod_color
        stored = await get_setting(ctx, "barcello.details_color_default", "")
        return _parse_hex_color(stored) or default_color

    def _parse_iso_ts(ts: str | None) -> datetime | None:
        if not ts or not str(ts).strip():
            return None
        raw = str(ts).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _format_italian_ts(ts: str | None) -> str:
        parsed = _parse_iso_ts(ts)
        if parsed is None:
            return ""
        local = parsed.astimezone(ROME_TZ)
        return local.strftime("%d/%m/%Y %H:%M")

    def _format_italian_time(ts: str | None) -> str:
        parsed = _parse_iso_ts(ts)
        if parsed is None:
            return ""
        local = parsed.astimezone(ROME_TZ)
        return local.strftime("%H:%M")

    def _parse_italian_datetime(value: str) -> datetime | None:
        raw = value.strip()
        for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
            try:
                parsed = datetime.strptime(raw, fmt)
                return parsed.replace(tzinfo=ROME_TZ)
            except ValueError:
                continue
        return None

    def _jump_link(guild_id: int, channel_id: int, message_id: str) -> str:
        return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"

    def _build_riassunto_status_embed(
        *,
        result: Any,
        channel_label: str,
        period_label: str,
        period_description: str,
    ) -> discord.Embed:
        color_label = (result.color or "nero").lower()
        color_map = {
            "verde": (0x2ECC71, "🟢", "verde"),
            "giallo": (0xF1C40F, "🟡", "giallo"),
            "rosso": (0xE74C3C, "🔴", "rosso"),
            "nero": (0x2C2F33, "⚫", "nero"),
        }
        embed_color, emoji, label = color_map.get(color_label, (0x2C2F33, "⚫", color_label))
        title = f"🫛 RESOCONTO BARCELLO “{channel_label}”"
        window_start = _format_italian_ts(result.window_start_ts)
        window_end = _format_italian_ts(result.window_end_ts)
        range_prefix = ""
        if period_label == "ieri":
            range_prefix = "Ieri "
        elif period_label == "oggi":
            range_prefix = "Oggi "
        window_label = f"🕒 **{range_prefix}{window_start} → {window_end}**"
        alert_line = f"**{emoji} ALLERTA {label.upper()}**"
        description_lines = [
            window_label,
            "",
            alert_line,
        ]
        embed = discord.Embed(
            title=title,
            description="\n".join(description_lines),
            color=embed_color,
        )
        bar = _render_health_bar(result.score, emoji)
        _add_section(
            embed,
            name="🫀 PUNTI SALUTE",
            value=_with_spacing(f"{bar} ({result.score}/100)\n{period_description}"),
        )
        return embed

    def _format_summary_time_link(
        ts: str | None,
        message_id: str | None,
        *,
        guild_id: int,
        channel_id: int,
        placeholder: str = "--:--",
    ) -> str:
        time_label = _format_italian_time(ts) or placeholder
        if message_id:
            jump = _jump_link(guild_id, channel_id, message_id)
            return f"**[{time_label}]({jump})**"
        return f"**{time_label}**"

    def _format_summary_moment_line(
        *,
        moment: SummaryItem,
        guild_id: int,
        channel_id: int,
        include_names: bool,
        display_name: str | None,
        link_limit: int,
        primary_id: str | None,
    ) -> str:
        text = moment.text
        if include_names:
            name = display_name
            if name and name.lower() in {"un utente", "utente", "unknown"}:
                name = None
            if name:
                placeholders = {"un utente", "una persona", "un membro", "qualcuno", "una persona"}
                lowered = text.lower()
                if any(token in lowered for token in placeholders):
                    for token in placeholders:
                        if token in lowered:
                            text = re.sub(re.escape(token), name, text, count=1, flags=re.IGNORECASE)
                            break
        time_link = _format_summary_time_link(
            moment.ts,
            primary_id,
            guild_id=guild_id,
            channel_id=channel_id,
        )
        return f"{time_link} — {text}"

    def _format_summary_quote_line(
        *,
        quote: SummaryQuote,
        guild_id: int,
        channel_id: int,
        primary_id: str | None,
        display_name: str | None,
        text_override: str | None,
    ) -> str:
        text = text_override or quote.text
        if display_name and display_name.lower() in {"un utente", "utente", "unknown"}:
            display_name = None
        speaker = display_name or ""
        time_link = _format_summary_time_link(
            quote.ts,
            primary_id,
            guild_id=guild_id,
            channel_id=channel_id,
        )
        line = f"{time_link} — “{text}”"
        if speaker:
            line += f" — {speaker}"
        return line

    def _format_summary_dynamics_line(
        *,
        dynamic: SummaryItem,
        guild_id: int,
        channel_id: int,
        primary_id: str | None,
        include_names: bool,
        display_names: list[str],
    ) -> str:
        text = dynamic.text
        suffix = ""
        if include_names and display_names:
            clean_names = [
                name for name in display_names if name.lower() not in {"un utente", "utente", "unknown"}
            ]
            if clean_names:
                suffix = f" — Coinvolti: {', '.join(clean_names)}"
        time_link = _format_summary_time_link(
            dynamic.ts,
            primary_id,
            guild_id=guild_id,
            channel_id=channel_id,
        )
        return f"{time_link} — {text}{suffix}"

    def _select_quote_text(content: str, max_len: int = 220) -> str:
        cleaned = " ".join((content or "").split())
        if not cleaned:
            return ""
        sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        candidates = [sentence for sentence in sentences if sentence]
        if not candidates:
            return cleaned
        within_limit = [sentence for sentence in candidates if len(sentence) <= max_len]
        if within_limit:
            return min(within_limit, key=len)
        return min(candidates, key=len)

    def _format_summary_impact_line(
        *,
        impact: SummaryImpact,
        guild_id: int,
        channel_id: int,
        display_name: str | None,
        link_limit: int,
        prefix: str,
        primary_id: str | None,
    ) -> str:
        time_link = _format_summary_time_link(
            impact.ts,
            primary_id,
            guild_id=guild_id,
            channel_id=channel_id,
        )
        if display_name:
            return f"{time_link} — {prefix} {display_name} — {impact.reason}"
        return f"{time_link} — {prefix} {impact.reason}"

    def _build_metrics_report(metrics: dict[str, Any]) -> str:
        keys = [
            "message_count",
            "window_minutes",
            "msg_per_min",
            "caps_ratio",
            "negativity_hits",
            "mention_count",
            "mention_per_min",
            "reply_war",
            "top1_author_share",
            "top3_author_share",
            "max_msgs_per_minute",
            "std_msgs_per_minute",
            "burst_ratio",
            "contrast_per_msg",
            "challenge_per_msg",
            "playful_emoji_ratio",
            "passive_aggressive_emoji_ratio",
            "sarcasm_marker_hits",
            "msg_count_user_a",
            "msg_count_user_b",
            "balance_ratio",
            "mentions_a_to_b",
            "mentions_b_to_a",
            "avg_msg_len_a",
            "avg_msg_len_b",
        ]
        lines = [f"{key}: {metrics.get(key)}" for key in keys]
        return "\n".join(lines)

    def _resolve_display_name(member: discord.Member) -> str:
        return (
            getattr(member, "display_name", None)
            or getattr(member, "global_name", None)
            or getattr(member, "name", None)
            or "Utente"
        )

    async def _run_riassunto(
        interaction: discord.Interaction,
        *,
        start_dt: datetime,
        end_dt: datetime,
        period_label: str,
    ) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Questo comando funziona solo nei canali della guild.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)

        command_config = await ctx.entitlements.get_command_profile_config(interaction.user, "riassunto")
        profile, winner_role_id = await ctx.entitlements.resolve_profile_with_role_id(interaction.user)
        if not command_config["allowed"]:
            dm_text = command_config["messages"].get("dm_text", "Serve almeno PLUS per usare /riassunto.")
            await send_ephemeral(interaction, dm_text)
            return

        summary_config = await ctx.summary_service.get_config()
        tier_config = summary_config.get("tiers", {}).get(profile, summary_config.get("tiers", {}).get("role1", {}))
        tier_label = tier_config.get("label", "PLUS")

        start_dt_utc = start_dt.astimezone(timezone.utc)
        end_dt_utc = end_dt.astimezone(timezone.utc)
        if end_dt_utc < start_dt_utc:
            start_dt_utc, end_dt_utc = end_dt_utc, start_dt_utc

        channel = interaction.channel
        if channel is None or not isinstance(channel, discord.abc.GuildChannel):
            await send_ephemeral(interaction, "Canale non valido.")
            return

        channel_is_voice = isinstance(channel, (discord.VoiceChannel, discord.StageChannel))
        channel_label = getattr(channel, "name", "canale")

        barcello_result = await ctx.barcello_service.compute_channel_range(
            str(interaction.guild_id),
            str(interaction.channel_id),
            start_dt_utc.isoformat(),
            end_dt_utc.isoformat(),
        )

        include_names = False
        if profile == "mod":
            include_names = True
        else:
            include_names = (barcello_result.color or "").lower() == "verde"

        period_prefix = _build_period_prefix(
            period_label,
            start_dt=start_dt_utc,
            end_dt=end_dt_utc,
            start_ts=barcello_result.window_start_ts,
            end_ts=barcello_result.window_end_ts,
        )
        period_description = _local_period_description(period_prefix, barcello_result.color)

        max_messages = int(summary_config.get("max_messages", 600))
        messages_rows = await ctx.database.fetch_messages_in_range(
            channel_id=str(interaction.channel_id),
            start_ts=start_dt_utc.isoformat(),
            end_ts=end_dt_utc.isoformat(),
            limit=max_messages,
        )
        latest_row = await ctx.database.fetch_latest_message_in_range(
            channel_id=str(interaction.channel_id),
            start_ts=start_dt_utc.isoformat(),
            end_ts=end_dt_utc.isoformat(),
        )
        max_message_ts = latest_row["ts"] if latest_row else None

        messages: list[dict[str, Any]] = []
        voice_segments = 0
        for row in messages_rows:
            embeds_raw = row["embeds_json"] if "embeds_json" in row.keys() else None
            embeds = json.loads(embeds_raw) if embeds_raw else []
            if any(isinstance(embed, dict) and embed.get("source") == "voice_ingest_stt" for embed in embeds):
                voice_segments += 1
            messages.append(
                {
                    "message_id": row["message_id"],
                    "author_id": row["author_id"],
                    "ts": row["ts"],
                    "content": row["content"],
                    "embeds": embeds,
                }
            )

        voice_lines: list[str] = []
        privacy_gaps: list[tuple[datetime, datetime]] = []
        voice_minutes = 0
        voice_sessions = 0
        if channel_is_voice:
            sessions = await ctx.database.fetch_voice_sessions_in_range(
                guild_id=str(interaction.guild_id),
                voice_channel_id=str(interaction.channel_id),
                start_ts=start_dt_utc.isoformat(),
                end_ts=end_dt_utc.isoformat(),
            )
            voice_sessions = len(sessions)
            for idx, session in enumerate(sessions, start=1):
                started = _parse_iso_ts(session["started_ts"])
                ended_raw = session["ended_ts"]
                if ended_raw:
                    ended = _parse_iso_ts(ended_raw)
                    duration = int((ended - started).total_seconds() / 60)
                    label = f"CHIAMATA {idx}: {duration}m" if voice_sessions > 1 else f"CHIAMATA: {duration}m"
                    voice_lines.append(label)
                    overlap_start = max(start_dt_utc, started)
                    overlap_end = min(end_dt_utc, ended)
                    if overlap_end > overlap_start:
                        voice_minutes += int((overlap_end - overlap_start).total_seconds() / 60)
                else:
                    label = (
                        f"CHIAMATA {idx}: chiamata in corso" if voice_sessions > 1 else "CHIAMATA: chiamata in corso"
                    )
                    voice_lines.append(label)
                    overlap_start = max(start_dt_utc, started)
                    overlap_end = end_dt_utc
                    if overlap_end > overlap_start:
                        voice_minutes += int((overlap_end - overlap_start).total_seconds() / 60)

            last_privacy = await ctx.database.fetch_last_privacy_event_before(
                channel_id=str(interaction.channel_id),
                ts=start_dt_utc.isoformat(),
            )
            privacy_on = False
            if last_privacy is not None:
                privacy_on = last_privacy["event_type"] == "voice.privacy_on"
            privacy_events = await ctx.database.fetch_events_in_range(
                channel_id=str(interaction.channel_id),
                start_ts=start_dt_utc.isoformat(),
                end_ts=end_dt_utc.isoformat(),
                limit=200,
            )
            gap_start: datetime | None = start_dt_utc if privacy_on else None
            for event in privacy_events:
                if event["event_type"] not in {"voice.privacy_on", "voice.privacy_off"}:
                    continue
                event_ts = _parse_iso_ts(event["ts"])
                if event["event_type"] == "voice.privacy_on" and gap_start is None:
                    gap_start = event_ts
                if event["event_type"] == "voice.privacy_off" and gap_start is not None:
                    privacy_gaps.append((gap_start, event_ts))
                    gap_start = None
            if gap_start is not None:
                privacy_gaps.append((gap_start, end_dt_utc))

        metrics = dict(barcello_result.metrics or {})
        metrics.update(
            {
                "voice_minutes": voice_minutes,
                "voice_sessions": voice_sessions,
                "voice_segments": voice_segments,
            }
        )

        ai_allowed = False
        ai_reason = "entitlements.policies.features.ai.allowed_profiles"
        ai_enabled = await ctx.entitlements.is_feature_allowed(interaction.user, "ai")
        ai_service_enabled = ctx.ai.is_enabled() if ctx.ai else False
        if ai_enabled and ai_service_enabled:
            ai_allowed = True
            ai_reason = "entitlements.policies.features.ai.allowed_profiles:ok"
        elif not ai_enabled:
            ai_reason = "entitlements.policies.features.ai.allowed_profiles:denied"
        else:
            ai_reason = "entitlements.policies.features.ai.allowed_profiles:ok;ai_service_disabled"

        ai_description = await ctx.summary_service.build_period_description(
            tier=profile,
            period_prefix=period_prefix,
            score=barcello_result.score,
            color=barcello_result.color,
            metrics=metrics,
            trend=barcello_result.trend,
            ai_allowed=ai_allowed,
            config=summary_config,
        )
        if ai_description:
            period_description = ai_description

        status_embed = _build_riassunto_status_embed(
            result=barcello_result,
            channel_label=channel_label,
            period_label=period_label,
            period_description=period_description,
        )

        model_name = ctx.ai.get_model("summary") if ctx.ai else None
        cache_key = ctx.summary_service.build_cache_key(
            guild_id=str(interaction.guild_id),
            channel_id=str(interaction.channel_id),
            start_ts=start_dt_utc.isoformat(),
            end_ts=end_dt_utc.isoformat(),
            tier=profile,
            evidence_mode=False,
            voice_context=channel_is_voice,
            ai_allowed=ai_allowed,
            model_name=model_name,
        )
        cache_hit = ctx.summary_service.peek_cache(cache_key, max_message_ts)
        logger.info(
            "riassunto: resolved_profile=%s tier=%s ai_allowed=%s ai_reason=%s cache_key=%s cache_hit=%s",
            profile,
            tier_label,
            ai_allowed,
            ai_reason,
            cache_key,
            cache_hit,
        )

        summary = await ctx.summary_service.build_summary(
            guild_id=str(interaction.guild_id),
            channel_id=str(interaction.channel_id),
            start_ts=start_dt_utc.isoformat(),
            end_ts=end_dt_utc.isoformat(),
            tier=profile,
            include_names=include_names,
            ai_allowed=ai_allowed,
            evidence_mode=False,
            voice_context=channel_is_voice,
            config=summary_config,
            barcello_metrics=metrics,
            max_message_ts=max_message_ts,
            messages=messages,
        )

        name_map: dict[str, str] = {}
        if interaction.guild:
            for message in messages:
                author_id = message.get("author_id")
                if not author_id or author_id in name_map:
                    continue
                member = interaction.guild.get_member(int(author_id))
                if member:
                    name_map[author_id] = _resolve_display_name(member)

        if name_map:
            lower_names = {name.lower() for name in name_map.values()}
            summary.themes = [theme for theme in summary.themes if theme.lower() not in lower_names]

        details_color = await _get_details_embed_color(profile)

        def is_valid_snowflake(value: str) -> bool:
            return bool(re.fullmatch(r"\d{17,20}", value))

        async def resolve_primary_ref(ts: str | None, message_ids: list[str]) -> str | None:
            for mid in message_ids:
                mid_str = str(mid)
                if not is_valid_snowflake(mid_str):
                    continue
                if await ctx.database.message_exists_in_channel(
                    channel_id=str(interaction.channel_id),
                    message_id=mid_str,
                ):
                    return mid_str
            parsed = _parse_iso_ts(ts)
            start_ts = start_dt_utc.isoformat()
            end_ts = end_dt_utc.isoformat()
            if parsed is not None:
                return await ctx.database.fetch_nearest_message_id_in_range(
                    channel_id=str(interaction.channel_id),
                    start_ts=start_ts,
                    end_ts=end_ts,
                    ts=parsed.isoformat(),
                )
            midpoint = start_dt_utc + (end_dt_utc - start_dt_utc) / 2
            return await ctx.database.fetch_nearest_message_id_in_range(
                channel_id=str(interaction.channel_id),
                start_ts=start_ts,
                end_ts=end_ts,
                ts=midpoint.isoformat(),
            )

        message_cache: dict[str, dict[str, Any]] = {}

        async def fetch_message_record(message_id: str) -> dict[str, Any] | None:
            if message_id in message_cache:
                return message_cache[message_id]
            row = await ctx.database.fetch_message_by_id(
                channel_id=str(interaction.channel_id),
                message_id=message_id,
            )
            if row:
                record = {"author_id": row["author_id"], "content": row["content"]}
                message_cache[message_id] = record
                return record
            return None

        async def resolve_author_display_name(message_id: str | None) -> str | None:
            if not message_id or interaction.guild is None:
                return None
            record = await fetch_message_record(message_id)
            if not record:
                return None
            author_id = record.get("author_id")
            if not author_id:
                return None
            display_name = await ctx.database.fetch_user_display_name(
                guild_id=str(interaction.guild_id),
                user_id=str(author_id),
            )
            if display_name:
                return display_name
            member = interaction.guild.get_member(int(author_id))
            if member:
                return _resolve_display_name(member)
            return None

        moment_primary: dict[int, str | None] = {}
        for moment in summary.moments:
            moment_primary[id(moment)] = await resolve_primary_ref(moment.ts, moment.message_ids)

        quote_primary: dict[int, str | None] = {}
        for quote in summary.quotes:
            quote_primary[id(quote)] = await resolve_primary_ref(quote.ts, quote.message_ids)

        dynamic_primary: dict[int, str | None] = {}
        for dynamic in summary.dynamics:
            dynamic_primary[id(dynamic)] = await resolve_primary_ref(dynamic.ts, dynamic.message_ids)

        impact_primary: dict[int, str | None] = {}
        for impact in summary.degrade + summary.invigorate:
            candidate_ids = [impact.message_id] if impact.message_id else []
            impact_primary[id(impact)] = await resolve_primary_ref(impact.ts, candidate_ids)

        moment_display: dict[int, str | None] = {}
        for moment in summary.moments:
            moment_display[id(moment)] = await resolve_author_display_name(moment_primary.get(id(moment)))

        quote_display: dict[int, str | None] = {}
        quote_texts: dict[int, str] = {}
        for quote in summary.quotes:
            primary_id = quote_primary.get(id(quote))
            quote_display[id(quote)] = await resolve_author_display_name(primary_id)
            if primary_id:
                record = await fetch_message_record(primary_id)
                if record and record.get("content"):
                    quote_texts[id(quote)] = _select_quote_text(record["content"])

        dynamic_names: dict[int, list[str]] = {}
        for dynamic in summary.dynamics:
            refs = [str(mid) for mid in (dynamic.message_ids or []) if str(mid)]
            valid_refs: list[str] = []
            for ref in refs:
                if not is_valid_snowflake(ref):
                    continue
                if await ctx.database.message_exists_in_channel(
                    channel_id=str(interaction.channel_id),
                    message_id=ref,
                ):
                    valid_refs.append(ref)
            if not valid_refs:
                primary_id = dynamic_primary.get(id(dynamic))
                if primary_id:
                    valid_refs = [primary_id]
            if include_names:
                names: list[str] = []
                for ref in valid_refs[:3]:
                    name = await resolve_author_display_name(ref)
                    if name and name not in names:
                        names.append(name)
                dynamic_names[id(dynamic)] = names

        report_id = str(uuid4())
        metrics_report: str | None = None
        if profile == "mod":
            metrics_report = _build_metrics_report(metrics)

        def build_embeds() -> list[discord.Embed]:
            sections_map: dict[str, list[tuple[str, str, int]]] = {}

            themes_value = ", ".join(summary.themes) if summary.themes else "Nessun tema rilevato."
            sections_map["themes"] = [("🏷️ TEMI", themes_value, 1)]

            moment_header = "📌 MOMENTI SALIENTI"
            moment_lines = [
                _format_summary_moment_line(
                    moment=moment,
                    guild_id=interaction.guild_id,
                    channel_id=interaction.channel_id,
                    include_names=include_names,
                    display_name=moment_display.get(id(moment)),
                    link_limit=1,
                    primary_id=moment_primary.get(id(moment)),
                )
                for moment in summary.moments
            ]
            if moment_lines:
                moment_lines = moment_lines[:10]
                sections_map["moments"] = [(moment_header, _format_bullets(moment_lines), 1)]

            if channel_is_voice and voice_lines:
                sections_map["voice"] = [("🎙️ CHIAMATA", "\n".join(voice_lines), 1)]

            quote_lines = [
                _format_summary_quote_line(
                    quote=quote,
                    guild_id=interaction.guild_id,
                    channel_id=interaction.channel_id,
                    primary_id=quote_primary.get(id(quote)),
                    display_name=quote_display.get(id(quote)),
                    text_override=quote_texts.get(id(quote)),
                )
                for quote in summary.quotes
            ]
            if quote_lines and profile in {"role2", "role3", "mod"}:
                sections_map["quotes"] = [("💬 FRASI ICONICHE", _format_bullets(quote_lines), 2)]

            dynamic_lines = [
                _format_summary_dynamics_line(
                    dynamic=dynamic,
                    guild_id=interaction.guild_id,
                    channel_id=interaction.channel_id,
                    primary_id=dynamic_primary.get(id(dynamic)),
                    include_names=include_names,
                    display_names=dynamic_names.get(id(dynamic), []),
                )
                for dynamic in summary.dynamics
            ]
            if dynamic_lines and profile in {"role3", "mod"}:
                sections_map["dynamics"] = [("🧠 DINAMICHE INTERESSANTI", _format_bullets(dynamic_lines), 2)]

            if profile == "mod":
                degrade_lines = []
                for impact in summary.degrade:
                    line = _format_summary_impact_line(
                        impact=impact,
                        guild_id=interaction.guild_id,
                        channel_id=interaction.channel_id,
                        display_name=name_map.get(impact.author_id or ""),
                        link_limit=1,
                        prefix="🔥",
                        primary_id=impact_primary.get(id(impact)),
                    )
                    degrade_lines.append(line)
                invigorate_lines = []
                for impact in summary.invigorate:
                    line = _format_summary_impact_line(
                        impact=impact,
                        guild_id=interaction.guild_id,
                        channel_id=interaction.channel_id,
                        display_name=name_map.get(impact.author_id or ""),
                        link_limit=1,
                        prefix="🌿",
                        primary_id=impact_primary.get(id(impact)),
                    )
                    invigorate_lines.append(line)
                impact_sections: list[tuple[str, str, int]] = []
                if degrade_lines:
                    impact_sections.append(("🔥 CHI DEGRADA", _format_bullets(degrade_lines), 3))
                if invigorate_lines:
                    impact_sections.append(("🌿 CHI RINVIGORISCE", _format_bullets(invigorate_lines), 3))
                if impact_sections:
                    sections_map["impact"] = impact_sections

                advice_lines = summary.advice
                if advice_lines:
                    sections_map["advice"] = [("🧭 CONSIGLI PERSONALIZZATI", _format_bullets(advice_lines), 3)]

                sections_map["metrics"] = [
                    ("🧱 METRICHE AGGREGATE", _with_spacing("Dettagli completi nel file allegato."), 3)
                ]

                ai_note = summary.ai_status
                if ai_note.get("enabled"):
                    ai_line = f"AI: ON ({ai_note.get('model')})"
                else:
                    fallback = "fallback locale attivo" if ai_note.get("fallback") or not ai_allowed else ""
                    ai_line = f"AI: OFF" + (f" — {fallback}" if fallback else "")
                sections_map["ai"] = [("🤖 AI", ai_line, 3)]

            note_by_profile = {
                "role1": "🔒 Per un riassunto più approfondito e le frasi iconiche, passa a PRO o a PRO MAX per vedere anche le dinamiche.",
                "role2": "🔒 Per vedere anche le dinamiche interessanti passa a PRO MAX.",
            }
            note_text = note_by_profile.get(profile)
            if note_text:
                sections_map["note"] = [("📌 NOTE", note_text, 3)]

            if privacy_gaps:
                lines = [
                    f"⚠️ PRIVACY NOTE: buchi rilevati dalle {_format_italian_time(start.isoformat())} alle {_format_italian_time(end.isoformat())}."
                    for start, end in privacy_gaps
                ]
                sections_map["privacy"] = [("⚠️ PRIVACY NOTE", "\n".join(lines), 3)]

            section_order = tier_config.get("sections") or list(sections_map.keys())
            sections: list[tuple[str, str, int]] = []
            for section_id in section_order:
                if section_id in sections_map:
                    sections.extend(sections_map[section_id])
            for extra_id in ("voice", "privacy", "note"):
                if extra_id in sections_map and extra_id not in section_order:
                    sections.extend(sections_map[extra_id])

            groups = sorted({group for _, _, group in sections})
            embed_color = details_color
            embeds: list[discord.Embed] = []

            def build_embed_shell(title_suffix: str) -> discord.Embed:
                title = f"🗒️ DETTAGLI RIASSUNTO — {tier_label}{title_suffix}"
                embed = discord.Embed(title=title, color=embed_color)
                embed.set_footer(text="Barcellometro")
                return embed

            def chunk_sections(section_list: list[tuple[str, str, int]]) -> list[discord.Embed]:
                target_max = MAX_EMBED_CHARS
                chunks: list[discord.Embed] = []
                current = build_embed_shell("")

                def fit_moment_value(field_name: str, current_embed: discord.Embed) -> str:
                    nonlocal moment_lines
                    lines = list(moment_lines)
                    value = _format_bullets(lines)
                    while lines and len(value) > 1024:
                        lines = lines[:-1]
                        value = _format_bullets(lines)
                    while lines:
                        candidate = _clone_embed_shell(current_embed)
                        for existing in current_embed.fields:
                            candidate.add_field(name=existing.name, value=existing.value, inline=existing.inline)
                        candidate.add_field(name=field_name, value=value, inline=False)
                        if _estimate_embed_size(candidate) < target_max and len(candidate.fields) <= 25:
                            break
                        lines = lines[:-1]
                        value = _format_bullets(lines)
                    moment_lines = lines
                    return value

                def add_field(field_name: str, field_value: str) -> None:
                    nonlocal current
                    candidate = _clone_embed_shell(current)
                    for existing in current.fields:
                        candidate.add_field(name=existing.name, value=existing.value, inline=existing.inline)
                    candidate.add_field(name=field_name, value=field_value, inline=False)
                    if _estimate_embed_size(candidate) >= target_max or len(candidate.fields) > 25:
                        if current.fields:
                            chunks.append(current)
                        current = build_embed_shell("")
                        current.add_field(name=field_name, value=field_value, inline=False)
                    else:
                        current = candidate

                for name, value, _group in section_list:
                    if name == moment_header:
                        moment_value = fit_moment_value(name, current)
                        if moment_value:
                            add_field(name, _with_spacing(moment_value))
                        continue
                    chunks_list = _split_field_chunks(_with_spacing(value), 1024)
                    for idx, chunk in enumerate(chunks_list):
                        field_name = name if idx == 0 else f"{name} (cont.)"
                        add_field(field_name, chunk)

                if current.fields:
                    chunks.append(current)
                return chunks

            if len(groups) <= 1:
                embeds = chunk_sections(sections)
            else:
                for group in groups:
                    group_sections = [item for item in sections if item[2] == group]
                    if group_sections:
                        embeds.extend(chunk_sections(group_sections))

            embeds = _ensure_embed_limits(embeds, max_chars=MAX_EMBED_CHARS)
            if any(_estimate_embed_size(embed) >= 6000 for embed in embeds):
                embeds = _ensure_embed_limits(embeds, max_chars=5600)

            total = max(len(embeds), 1)
            for idx, embed in enumerate(embeds, start=1):
                embed.title = f"🗒️ DETTAGLI RIASSUNTO — {tier_label} (Pag {idx}/{total})"
            return embeds

        embeds = build_embeds()

        logger.info(
            "riassunto: report id=%s user=%s channel=%s range=%s-%s tier=%s ai=%s cache=%s voice=%s",
            report_id,
            interaction.user.id,
            interaction.channel_id,
            start_dt_utc.isoformat(),
            end_dt_utc.isoformat(),
            tier_label,
            ai_reason,
            summary.cache_hit,
            channel_is_voice,
        )

        def build_metrics_attachment() -> discord.File | None:
            if not metrics_report:
                return None
            buffer = io.BytesIO(metrics_report.encode("utf-8"))
            return discord.File(buffer, filename=f"metriche-riassunto-{report_id}.txt")

        normalized_status = normalize_embeds_for_discord([status_embed])
        normalized_details = normalize_embeds_for_discord(embeds)
        metrics_file = build_metrics_attachment()
        files = [metrics_file] if metrics_file else None
        sent_dm = await send_dm_or_followup(
            interaction,
            embeds=[*normalized_status, *normalized_details],
            content="⚠️ Non posso inviarti DM, quindi ti mostro il riassunto qui in modalità privata.",
            files=files,
            ephemeral_fallback=True,
        )
        if sent_dm:
            await interaction.followup.send("✅ Ti ho inviato il riassunto in DM.", ephemeral=True)

    @riassunto_group.command(name="ultimi", description="Riassunto degli ultimi N minuti/ore/giorni/settimane")
    @app_commands.describe(quantita="Numero di unità", unita="Unità di tempo")
    @app_commands.choices(
        unita=[
            app_commands.Choice(name="minuti", value="minuti"),
            app_commands.Choice(name="ore", value="ore"),
            app_commands.Choice(name="giorni", value="giorni"),
            app_commands.Choice(name="settimane", value="settimane"),
        ]
    )
    async def riassunto_ultimi(
        interaction: discord.Interaction,
        quantita: int,
        unita: app_commands.Choice[str],
    ) -> None:
        if quantita <= 0:
            await send_ephemeral(interaction, "Specifica una quantità valida.")
            return
        now = datetime.now(ROME_TZ)
        delta_map = {
            "minuti": timedelta(minutes=quantita),
            "ore": timedelta(hours=quantita),
            "giorni": timedelta(days=quantita),
            "settimane": timedelta(weeks=quantita),
        }
        start_dt = now - delta_map.get(unita.value, timedelta(minutes=quantita))
        await _run_riassunto(interaction, start_dt=start_dt, end_dt=now, period_label="ultimi")

    @riassunto_group.command(name="oggi", description="Riassunto della giornata di oggi")
    async def riassunto_oggi(interaction: discord.Interaction) -> None:
        now = datetime.now(ROME_TZ)
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        await _run_riassunto(interaction, start_dt=start_dt, end_dt=now, period_label="oggi")

    @riassunto_group.command(name="ieri", description="Riassunto della giornata di ieri")
    async def riassunto_ieri(interaction: discord.Interaction) -> None:
        now = datetime.now(ROME_TZ)
        end_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_dt = end_dt - timedelta(days=1)
        await _run_riassunto(interaction, start_dt=start_dt, end_dt=end_dt, period_label="ieri")

    @riassunto_group.command(name="range", description="Riassunto di un range custom (data+ora italiane)")
    @app_commands.describe(da="Da (DD/MM/YYYY HH:MM)", a="A (DD/MM/YYYY HH:MM)")
    async def riassunto_range(interaction: discord.Interaction, da: str, a: str) -> None:
        start_dt = _parse_italian_datetime(da)
        end_dt = _parse_italian_datetime(a)
        if not start_dt or not end_dt:
            await send_ephemeral(interaction, "Formato data/ora non valido. Usa DD/MM/YYYY HH:MM.")
            return
        await _run_riassunto(interaction, start_dt=start_dt, end_dt=end_dt, period_label="range")

    def _clean_bullets(lines: list[str] | None) -> list[str]:
        if not lines:
            return []
        cleaned: list[str] = []
        for line in lines:
            text = str(line).strip()
            if not text:
                continue
            normalized = text.lstrip("-• ").strip().lower()
            if normalized in {"(nessuna)", "nessuna", "• (nessuna)", "• nessuna"}:
                continue
            cleaned.append(text)
        return cleaned

    def _format_bullets(lines: list[str]) -> str:
        cleaned = _clean_bullets(lines)
        if not cleaned:
            return ""
        formatted: list[str] = []
        for line in cleaned:
            text = line.strip()
            if text.startswith(("- ", "* ")):
                text = text[2:].strip()
            if text.startswith("•"):
                text = text.lstrip("•").strip()
            if text.startswith("•"):
                text = text.lstrip("•").strip()
            if text.startswith("• •"):
                text = text.replace("• •", "•", 1).strip()
            formatted.append(f"• {text}")
        return "\n".join(formatted)
