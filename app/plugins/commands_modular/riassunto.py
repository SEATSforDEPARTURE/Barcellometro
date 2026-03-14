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

from app.services.footer import attach_footer_meta
from discord import app_commands

from app.services.footer import attach_footer_meta, copy_footer_meta
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
from app.plugins.commands_modular.time_windows import (
    parse_italian_datetime,
    resolve_ieri_window,
    resolve_oggi_window,
    resolve_range_window,
    resolve_ultimi_window,
)
from app.utils.summary_render import build_summary_detail_embeds

logger = logging.getLogger(__name__)

ROME_TZ = ZoneInfo("Europe/Rome")
MOMENTS_FIELD_NAME = "📌 MOMENTI SALIENTI"


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

    def _bold_header(s: str | None) -> str | None:
        if not s:
            return s
        t = s.strip()
        if t.startswith("**") and t.endswith("**"):
            return t
        return f"**{t}**"

    def _truncate_text(s: str | None, limit: int) -> str:
        if s is None:
            return ""
        if limit <= 0:
            return ""
        if len(s) <= limit:
            return s
        if limit <= 1:
            return s[:limit]
        return s[: max(0, limit - 1)] + "…"

    def _truncate_line_preserve_md_link(line: str, line_limit: int) -> str:
        if len(line) <= line_limit:
            return line
        if line_limit <= 1:
            return _truncate_text(line, line_limit)
        separator = " — "
        if separator in line:
            prefix, _, tail = line.partition(separator)
            fixed_prefix = f"{prefix}{separator}"
            fixed_len = len(fixed_prefix)
            if fixed_len >= line_limit:
                return _truncate_text(line, line_limit)
            return fixed_prefix + _truncate_text(tail, line_limit - fixed_len)

        link_match = re.search(r"\[[^\]]+\]\([^\)]+\)", line)
        if link_match:
            link_end = link_match.end()
            prefix = line[:link_end]
            suffix = line[link_end:]
            if len(prefix) >= line_limit:
                return _truncate_text(line, line_limit)
            return prefix + _truncate_text(suffix, line_limit - len(prefix))
        return _truncate_text(line, line_limit)

    def _truncate_field_value_preserve_lines_preserve_md_links(value: str | None, limit: int = 1024) -> str:
        if value is None:
            return ""
        if len(value) <= limit:
            return value
        lines = value.split("\n")
        if len(lines) == 1:
            return _truncate_line_preserve_md_link(value, limit)
        min_per_line = 20
        per_line = max(min_per_line, (limit - (len(lines) - 1)) // len(lines))
        while per_line >= min_per_line:
            new_lines = []
            for line in lines:
                if len(line) <= per_line:
                    new_lines.append(line)
                else:
                    new_lines.append(_truncate_line_preserve_md_link(line, per_line))
            out = "\n".join(new_lines)
            if len(out) <= limit:
                return out
            per_line -= 5
        return _truncate_line_preserve_md_link(value, limit)

    def _truncate_moments_value_preserve_links(value: str | None, limit: int = 1024) -> str:
        if value is None:
            return ""
        if len(value) <= limit:
            return value
        lines = value.split("\n")
        if not lines:
            return _truncate_text(value, limit)
        available = max(40, limit - (len(lines) - 1))
        per_line_budget = max(40, available // len(lines))
        while per_line_budget >= 40:
            out_lines = [_truncate_line_preserve_md_link(line, per_line_budget) for line in lines]
            out = "\n".join(out_lines)
            if len(out) <= limit:
                return out
            per_line_budget -= 10
        return _truncate_text(value, limit)

    def _format_moments_chunk(lines: list[str], max_tail: int) -> str:
        fitted = [_truncate_moment_line(line, max_tail=max_tail) for line in lines]
        return _format_bullets(fitted)

    def _truncate_moments_value_tail_only(value: str | None, limit: int = 1024) -> str:
        if value is None:
            return ""
        if len(value) <= limit:
            return value
        lines = value.split("\n")
        if not lines:
            return _truncate_text(value, limit)
        available = max(40, limit - (len(lines) - 1))
        per_line_budget = max(40, available // len(lines))
        while per_line_budget >= 40:
            out_lines = [_truncate_line_preserve_md_link(line, per_line_budget) for line in lines]
            out = "\n".join(out_lines)
            if len(out) <= limit:
                return out
            per_line_budget -= 10
        return _truncate_text(value, limit)

    def _split_lines_into_field_values(lines: list[str], limit: int = 1024) -> list[str]:
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0

        def _explode_if_needed(line: str) -> list[str]:
            if len(line) <= limit:
                return [line]
            if " — " in line:
                prefix, tail = line.split(" — ", 1)
                prefix = f"{prefix} — "
                if len(prefix) < limit:
                    first_tail = tail[: max(1, limit - len(prefix))]
                    extra = tail[len(first_tail) :]
                    expanded = [prefix + first_tail]
                    cont_limit = max(1, limit - 2)
                    while extra:
                        expanded.append(f"↳ {extra[:cont_limit]}")
                        extra = extra[cont_limit:]
                    return expanded
            expanded: list[str] = []
            extra = line
            while extra:
                expanded.append(extra[:limit])
                extra = extra[limit:]
            return expanded

        for raw_line in lines:
            line = str(raw_line or "")
            if not line:
                continue
            for expanded_line in _explode_if_needed(line):
                line_len = len(expanded_line) + (1 if current else 0)
                if current and (current_len + line_len) > limit:
                    chunks.append("\n".join(current))
                    current = [expanded_line]
                    current_len = len(expanded_line)
                    continue

                current.append(expanded_line)
                current_len += line_len

        if current:
            chunks.append("\n".join(current))

        return chunks

    def _safe_add_field(embed: discord.Embed, *, name: str, value: str, req_id: str, section: str) -> None:
        original_name = str(name or "")
        original_value = str(value or "")
        safe_name = _truncate_text(original_name, 256)
        if original_name.startswith(MOMENTS_FIELD_NAME):
            safe_value = _truncate_moments_value_preserve_links(original_value, 1024)
        else:
            safe_value = _truncate_field_value_preserve_lines_preserve_md_links(original_value, 1024)
        if original_name != safe_name:
            logger.info(
                "riassunto: field name truncated req_id=%s section=%s before=%s after=%s",
                req_id,
                section,
                len(original_name),
                len(safe_name),
            )
        if original_value != safe_value:
            logger.info(
                "riassunto: field truncated req_id=%s section=%s before=%s after=%s",
                req_id,
                section,
                len(original_value),
                len(safe_value),
            )
        embed.add_field(name=safe_name, value=safe_value, inline=False)

    def _sanitize_embeds_for_discord_limits(embeds: list[discord.Embed], *, req_id: str) -> list[discord.Embed]:
        sanitized: list[discord.Embed] = []
        for embed_idx, embed in enumerate(embeds, start=1):
            description = embed.description or ""
            safe_description = _truncate_text(description, 4096)
            if description != safe_description:
                logger.info(
                    "riassunto: embed description truncated req_id=%s embed_idx=%s before=%s after=%s",
                    req_id,
                    embed_idx,
                    len(description),
                    len(safe_description),
                )
            clone = _clone_embed_shell(embed)
            clone.title = _truncate_text(embed.title or "", 256) or None
            clone.description = safe_description or None
            clone.url = embed.url
            if embed.author and embed.author.name:
                clone.set_author(
                    name=_truncate_text(embed.author.name, 256),
                    url=embed.author.url,
                    icon_url=embed.author.icon_url,
                )
            copy_footer_meta(embed, clone)
            if embed.thumbnail and embed.thumbnail.url:
                clone.set_thumbnail(url=embed.thumbnail.url)
            if embed.image and embed.image.url:
                clone.set_image(url=embed.image.url)
            for field in embed.fields:
                _safe_add_field(
                    clone,
                    name=field.name,
                    value=field.value,
                    req_id=req_id,
                    section=f"embed{embed_idx}:{field.name}",
                )
            sanitized.append(clone)
        return sanitized

    def _add_section(embed: discord.Embed, *, name: str, value: str) -> None:
        chunks = _split_field_chunks(value, 1024)
        available = 25 - len(embed.fields)
        if available <= 0:
            return
        if len(chunks) > available:
            chunks = chunks[:available]
        for idx, chunk in enumerate(chunks):
            field_name = name if idx == 0 else f"{name} (cont.)"
            _safe_add_field(embed, name=field_name, value=chunk, req_id="status", section=field_name)

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

    def _format_italian_time(ts: str | None, *, include_date: bool = False) -> str:
        parsed = _parse_iso_ts(ts)
        if parsed is None:
            return ""
        local = parsed.astimezone(ROME_TZ)
        return local.strftime("%d/%m %H:%M") if include_date else local.strftime("%H:%M")

    def _parse_italian_datetime(value: str) -> datetime | None:
        raw = value.strip()
        for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
            try:
                parsed = datetime.strptime(raw, fmt)
                return parsed.replace(tzinfo=ROME_TZ)
            except ValueError:
                continue
        return None

    def _granularity_hint_for_period(period_label: str, unit: str | None = None) -> str:
        unit_key = (unit or "").lower()
        if period_label == "ultimi":
            if unit_key == "minuti":
                return "minutes"
            if unit_key == "ore":
                return "hours"
            if unit_key == "giorni":
                return "days"
            if unit_key == "settimane":
                return "weeks"
        return "hours"

    async def _validate_coverage_or_adjust(
        interaction: discord.Interaction,
        *,
        start_dt_utc: datetime,
        end_dt_utc: datetime,
    ) -> tuple[datetime | None, datetime | None, str | None]:
        requested_start = start_dt_utc
        requested_end = end_dt_utc
        min_ts, max_ts = await ctx.database.get_channel_coverage(str(interaction.channel_id))
        if max_ts is None:
            await send_ephemeral(interaction, "❌ Dati insufficienti: non ci sono messaggi salvati per questo canale.")
            return None, None, None
        min_dt = _parse_iso_ts(min_ts)
        max_dt = _parse_iso_ts(max_ts)

        async def _send_no_data() -> tuple[None, None, None]:
            await send_ephemeral(
                interaction,
                f"⚠️ Nessun dato nel periodo richiesto. Ultimi dati disponibili: {_format_italian_ts(max_ts)}. "
                "Prova ad aumentare la finestra temporale.",
            )
            logger.info(
                "riassunto: coverage_adjust channel=%s req_start=%s req_end=%s cov_min=%s cov_max=%s status=no-data",
                interaction.channel_id,
                requested_start.isoformat(),
                requested_end.isoformat(),
                min_ts,
                max_ts,
            )
            return None, None, None

        if max_dt and start_dt_utc > max_dt:
            return await _send_no_data()
        if min_dt and end_dt_utc < min_dt:
            await send_ephemeral(
                interaction,
                f"❌ Range fuori dai dati disponibili (dati da {_format_italian_ts(min_ts)}). Riduci la finestra temporale.",
            )
            logger.info(
                "riassunto: coverage_adjust channel=%s req_start=%s req_end=%s cov_min=%s cov_max=%s status=hard-error-before-start",
                interaction.channel_id,
                requested_start.isoformat(),
                requested_end.isoformat(),
                min_ts,
                max_ts,
            )
            return None, None, None

        warning_note: str | None = None
        if min_dt and start_dt_utc < min_dt:
            start_dt_utc = min_dt
            warning_note = f"⚠️ Dati disponibili da {_format_italian_ts(min_ts)}. Riassunto da lì."
        if max_dt and end_dt_utc > max_dt:
            end_dt_utc = max_dt
            note2 = f"⚠️ Dati disponibili fino a {_format_italian_ts(max_ts)}. Riassunto fino a lì."
            warning_note = f"{warning_note}\n{note2}" if warning_note else note2

        if start_dt_utc > end_dt_utc:
            return await _send_no_data()

        logger.info(
            "riassunto: coverage_adjust channel=%s req_start=%s req_end=%s cov_min=%s cov_max=%s adj_start=%s adj_end=%s clamped=%s status=%s",
            interaction.channel_id,
            requested_start.isoformat(),
            requested_end.isoformat(),
            min_ts,
            max_ts,
            start_dt_utc.isoformat(),
            end_dt_utc.isoformat(),
            bool(warning_note),
            "clamped" if warning_note else "ok",
        )
        return start_dt_utc, end_dt_utc, warning_note

    def _jump_link(guild_id: int, channel_id: int, message_id: str) -> str:
        return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"

    def _is_valid_discord_jump_url(url: str | None) -> bool:
        if not url:
            return False
        raw = str(url).strip()
        if not raw.startswith(("https://discord.com/channels/", "https://discordapp.com/channels/")):
            return False
        return bool(
            re.fullmatch(
                r"https://(?:discord\.com|discordapp\.com)/channels/\d{17,20}/\d{17,20}/\d{17,20}",
                raw,
            )
        )

    def _resolve_jump_url(
        *,
        guild_id: int,
        channel_id: int,
        message_ref: str | None,
    ) -> str | None:
        if not message_ref:
            return None
        candidate = str(message_ref).strip()
        if _is_valid_discord_jump_url(candidate):
            return candidate
        if re.fullmatch(r"\d{17,20}", candidate):
            return _jump_link(guild_id, channel_id, candidate)
        logger.debug("riassunto: discarded non-url message_ref for time link ref=%r", candidate[:80])
        return None

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
        message_ref: str | None,
        *,
        guild_id: int,
        channel_id: int,
        placeholder: str = "--:--",
        in_call: bool = False,
        include_date: bool = False,
    ) -> str:
        time_label = _format_italian_time(ts, include_date=include_date) or placeholder
        jump = _resolve_jump_url(guild_id=guild_id, channel_id=channel_id, message_ref=message_ref)
        if jump:
            time_link = f"**[{time_label}]({jump})**"
        else:
            time_link = f"**{time_label}**"
        if in_call:
            return f"{time_link} 📞"
        return time_link

    def _format_summary_moment_line(
        *,
        moment: SummaryItem,
        guild_id: int,
        channel_id: int,
        include_names: bool,
        display_name: str | None,
        link_limit: int,
        primary_id: str | None,
        include_date: bool = False,
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
            in_call=moment.in_call,
            include_date=include_date,
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
        include_date: bool = False,
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
            in_call=quote.in_call,
            include_date=include_date,
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
        include_date: bool = False,
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
            in_call=dynamic.in_call,
            include_date=include_date,
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
        include_date: bool = False,
    ) -> str:
        time_link = _format_summary_time_link(
            impact.ts,
            primary_id,
            guild_id=guild_id,
            channel_id=channel_id,
            include_date=include_date,
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
        granularity_hint: str = "hours",
    ) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Questo comando funziona solo nei canali della guild.")
            return
        if not await check_permission(interaction, "riassunto", ctx):
            return
        req_id = str(uuid4())[:8]
        logger.info(
            "riassunto start req_id=%s guild_id=%s channel_id=%s user_id=%s period=%s start=%s end=%s",
            req_id,
            interaction.guild_id,
            interaction.channel_id,
            interaction.user.id,
            period_label,
            start_dt.isoformat(),
            end_dt.isoformat(),
        )
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            member = interaction.user
            profile, winner_role_id = await ctx.entitlements.resolve_profile_with_role_id(member)
            command_config = await ctx.entitlements.get_command_profile_config(member, "riassunto")
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
            duration_seconds = max(0, int((end_dt_utc - start_dt_utc).total_seconds()))
            tier_cap = await ctx.entitlements.get_command_limit_seconds(member, "riassunto", "max_window_seconds")
            logger.info("riassunto: tier_limit profile=%s duration=%s cap=%s", profile, duration_seconds, tier_cap)
            if tier_cap is not None and duration_seconds > tier_cap:
                suggestion = ""
                if granularity_hint in {"days", "weeks"}:
                    suggestion = " Riduci i giorni richiesti o passa al tier successivo."
                if granularity_hint == "weeks" or duration_seconds >= 14 * 24 * 60 * 60:
                    suggestion = " Prova con `/riassunto ultimi 7 giorni` oppure passa al tier successivo."

                if profile == "role1":
                    await send_ephemeral(
                        interaction,
                        f"❌ Limite PLUS: massimo 24 ore. Per periodi più lunghi serve PRO.{suggestion}",
                    )
                    return
                if profile == "role2":
                    await send_ephemeral(
                        interaction,
                        f"❌ Limite PRO: massimo 7 giorni. Per periodi più lunghi serve PRO MAX.{suggestion}",
                    )
                    return
            start_dt_utc, end_dt_utc, coverage_note = await _validate_coverage_or_adjust(
                interaction,
                start_dt_utc=start_dt_utc,
                end_dt_utc=end_dt_utc,
            )
            if start_dt_utc is None or end_dt_utc is None:
                return

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

            logger.info(
                "riassunto barcello computed req_id=%s color=%s score=%s window_start=%s window_end=%s",
                req_id,
                barcello_result.color,
                barcello_result.score,
                barcello_result.window_start_ts,
                barcello_result.window_end_ts,
            )

            barcello_color = (barcello_result.color or "").lower()
            include_names = barcello_color == "verde"
            if not channel_is_voice and ctx.config.name_policy_text_show_names_always:
                include_names = True
            if profile == "mod":
                include_names = True
                logger.info("riassunto: mod_show_names_override=true color=%s", barcello_result.color)
            logger.info("riassunto: moments policy=role3 for tier=%s", profile)

            period_prefix = _build_period_prefix(
                period_label,
                start_dt=start_dt_utc,
                end_dt=end_dt_utc,
                start_ts=barcello_result.window_start_ts,
                end_ts=barcello_result.window_end_ts,
            )
            period_description = _local_period_description(period_prefix, barcello_result.color)
            if coverage_note:
                period_description = f"{period_description}\n{coverage_note}"
            include_date_in_time = start_dt_utc.astimezone(ROME_TZ).date() != end_dt_utc.astimezone(ROME_TZ).date()

            max_messages = int(summary_config.get("max_messages", 600))
            duration_secs = duration_seconds
            if granularity_hint == "minutes":
                buckets = 3
            elif granularity_hint == "hours":
                buckets = 5
            elif granularity_hint == "days":
                buckets = 7
            elif granularity_hint == "weeks":
                buckets = 8
            elif duration_secs >= 12 * 60 * 60:
                buckets = 8
            elif duration_secs >= 6 * 60 * 60:
                buckets = 6
            elif duration_secs >= 2 * 60 * 60:
                buckets = 4
            else:
                buckets = 1
            per_bucket_limit = max(1, max_messages // max(1, buckets))
            if buckets > 1:
                messages_rows = await ctx.database.fetch_messages_in_range_time_bucketed(
                    channel_id=str(interaction.channel_id),
                    start_ts=start_dt_utc.isoformat(),
                    end_ts=end_dt_utc.isoformat(),
                    buckets=buckets,
                    per_bucket_limit=per_bucket_limit,
                    include_bots=(not ctx.config.ignore_bots),
                )
            else:
                messages_rows = await ctx.database.fetch_messages_in_range(
                    channel_id=str(interaction.channel_id),
                    start_ts=start_dt_utc.isoformat(),
                    end_ts=end_dt_utc.isoformat(),
                    limit=max_messages,
                )
            logger.info(
                "riassunto: range_sampling channel_id=%s duration_secs=%s buckets=%s per_bucket_limit=%s total_rows=%s",
                interaction.channel_id,
                duration_secs,
                buckets,
                per_bucket_limit,
                len(messages_rows),
            )
            latest_row = await ctx.database.fetch_latest_message_in_range(
                channel_id=str(interaction.channel_id),
                start_ts=start_dt_utc.isoformat(),
                end_ts=end_dt_utc.isoformat(),
            )
            max_message_ts = latest_row["ts"] if latest_row else None

            timeline_entries: list[dict[str, Any]] = []

            def _append_event(
                ts_value: datetime | str | None,
                text: str,
                kind: str = "call",
                in_call: bool = True,
                actor_id: str | None = None,
                message_id: str | None = None,
                meta: dict[str, Any] | None = None,
            ) -> None:
                ts_dt: datetime | None
                if isinstance(ts_value, datetime):
                    ts_dt = ts_value
                elif isinstance(ts_value, str):
                    ts_dt = _parse_iso_ts(ts_value)
                else:
                    ts_dt = None
                if ts_dt is None:
                    return
                meta_payload = dict(meta or {})
                meta_payload.setdefault("kind", kind)
                timeline_entries.append(
                    {
                        "ts": ts_dt,
                        "kind": kind,
                        "in_call": in_call,
                        "actor_id": actor_id,
                        "text": text,
                        "message_id": message_id,
                        "meta": meta_payload,
                    }
                )

            voice_segments = 0
            for row in messages_rows:
                if int(row["is_deleted"] or 0) == 1 if "is_deleted" in row.keys() else False:
                    continue
                embeds_raw = row["embeds_json"] if "embeds_json" in row.keys() else None
                embeds = json.loads(embeds_raw) if embeds_raw else []
                if any(isinstance(embed, dict) and embed.get("source") == "voice_ingest_stt" for embed in embeds):
                    voice_segments += 1
                ts_parsed = _parse_iso_ts(row["ts"])
                _append_event(
                    ts_value=ts_parsed,
                    text=str(row["content"] or ""),
                    kind="chat",
                    in_call=False,
                    actor_id=str(row["author_id"] or "") or None,
                    message_id=str(row["message_id"] or "") or None,
                    meta={"kind": "chat", "in_call": False, "embeds": embeds, "ts_raw": row["ts"]},
                )

            voice_minutes = 0
            voice_sessions = 0
            voice_transcripts = 0
            voice_presence = 0
            privacy_entries = 0
            call_entries = 0
            voice_session_ranges: list[tuple[datetime, datetime]] = []
            forced_moments: list[SummaryItem] = []
            supplemental_moments: list[SummaryItem] = []
            privacy_moments: list[SummaryItem] = []
            privacy_events: list[dict[str, Any]] = []
            privacy_intervals: list[tuple[datetime, datetime | None, str | None]] = []
            privacy_disclaimer_lines: list[str] = []
            participant_join_events: list[dict[str, Any]] = []
            participant_leave_events: list[dict[str, Any]] = []
            participant_move_events: list[dict[str, Any]] = []

            def _is_in_privacy_gap_dt(ts_dt: datetime) -> bool:
                if not privacy_intervals:
                    return False
                for start, end, _actor in privacy_intervals:
                    end_bound = end or end_dt_utc
                    if start <= ts_dt <= end_bound:
                        return True
                return False

            def _is_in_privacy_gap(ts_value: str | None) -> bool:
                ts_dt = _parse_iso_ts(ts_value)
                if ts_dt is None:
                    return False
                return _is_in_privacy_gap_dt(ts_dt)

            if channel_is_voice:
                sessions = await ctx.database.fetch_voice_sessions_in_range(
                    guild_id=str(interaction.guild_id),
                    voice_channel_id=str(interaction.channel_id),
                    start_ts=start_dt_utc.isoformat(),
                    end_ts=end_dt_utc.isoformat(),
                )
                voice_sessions = len(sessions)
                participant_events = await ctx.database.fetch_voice_participant_events_in_range(
                    guild_id=str(interaction.guild_id),
                    voice_channel_id=str(interaction.channel_id),
                    start_ts=start_dt_utc.isoformat(),
                    end_ts=end_dt_utc.isoformat(),
                )
                for participant_event in participant_events:
                    event_type = str(participant_event.get("event_type") or "")
                    if event_type == "join":
                        participant_join_events.append(participant_event)
                    elif event_type == "leave":
                        participant_leave_events.append(participant_event)
                    elif event_type == "move":
                        participant_move_events.append(participant_event)
                        participant_join_events.append(participant_event)

                has_non_bot_participant_signals = bool(participant_join_events or participant_leave_events)

                def _describe_duration(seconds: float) -> str:
                    minutes = max(1, int(round(seconds / 60)))
                    hours = minutes // 60
                    if hours >= 1:
                        rem = minutes % 60
                        if rem:
                            return f"{hours}h {rem}m"
                        return f"{hours}h"
                    return f"{minutes}m"

                def _build_privacy_disclaimer(
                    started: datetime,
                    ended: datetime | None,
                    actor_name: str | None,
                ) -> str:
                    start_label = _format_italian_time(started.isoformat())
                    actor_label = actor_name or "un moderatore"
                    if ended:
                        end_label = _format_italian_time(ended.isoformat())
                        return (
                            f"{start_label} 📞 — Contenuti omessi per privacy: modalità privacy "
                            f"attivata da {actor_label} alle {start_label} e disattivata alle {end_label}."
                        )
                    return (
                        f"{start_label} 📞 — Contenuti omessi per privacy: modalità privacy "
                        f"attivata da {actor_label} alle {start_label} ed è ancora attiva."
                    )

                session_lookup: dict[str, dict[str, Any]] = {}
                for session in sessions:
                    started = _parse_iso_ts(session["started_ts"])
                    if not started:
                        continue
                    ended = _parse_iso_ts(session["ended_ts"]) if session["ended_ts"] else None
                    session_id = str(session["voice_session_id"] or "")
                    session_lookup[session_id] = {"started": started, "ended": ended}
                    overlap_start = max(start_dt_utc, started)
                    overlap_end = min(end_dt_utc, ended or end_dt_utc)
                    if overlap_end > overlap_start:
                        voice_minutes += int((overlap_end - overlap_start).total_seconds() / 60)
                    voice_session_ranges.append((started, ended or end_dt_utc))
                    overlap_seconds = max(0.0, (overlap_end - overlap_start).total_seconds())
                    overlap_label = _describe_duration(overlap_seconds) if overlap_seconds else "~1m"
                    started_local = _format_italian_time(started.isoformat())
                    if started < start_dt_utc:
                        text = f"Sessione già in corso (iniziata prima della finestra): iniziata alle {started_local}"
                    else:
                        text = f"Inizia una sessione vocale (durata nella finestra: {overlap_label})."
                    ts_value = started
                    if has_non_bot_participant_signals:
                        supplemental_moments.append(
                            SummaryItem(
                                ts=ts_value.isoformat(),
                                text=text,
                                author_id=None,
                                message_ids=[],
                                in_call=True,
                            )
                        )
                        _append_event(ts_value, text, kind="call")
                        call_entries += 1
                        if ended and start_dt_utc <= ended <= end_dt_utc:
                            end_text = f"Termina la sessione vocale (durata nella finestra: {overlap_label})."
                            supplemental_moments.append(
                                SummaryItem(
                                    ts=ended.isoformat(),
                                    text=end_text,
                                    author_id=None,
                                    message_ids=[],
                                    in_call=True,
                                )
                            )
                            _append_event(ended, end_text, kind="call")
                            call_entries += 1
                        if not ended or ended > end_dt_utc:
                            continue_text = f"La sessione vocale prosegue oltre il periodo (durata nella finestra: {overlap_label})."
                            supplemental_moments.append(
                                SummaryItem(
                                    ts=end_dt_utc.isoformat(),
                                    text=continue_text,
                                    author_id=None,
                                    message_ids=[],
                                    in_call=True,
                                )
                            )
                            _append_event(end_dt_utc, continue_text, kind="call")
                            call_entries += 1

                privacy_events = await ctx.database.fetch_events_in_range(
                    channel_id=str(interaction.channel_id),
                    start_ts=start_dt_utc.isoformat(),
                    end_ts=end_dt_utc.isoformat(),
                    limit=max_messages,
                )
                last_privacy = await ctx.database.fetch_last_privacy_event_before(
                    channel_id=str(interaction.channel_id),
                    ts=start_dt_utc.isoformat(),
                )
                privacy_on = False
                privacy_actor: str | None = None
                if last_privacy is not None:
                    privacy_on = last_privacy["event_type"] == "voice.privacy_on"
                    privacy_actor = str(last_privacy["actor_id"] or "") or None
                privacy_events = sorted(privacy_events, key=lambda item: str(item["ts"] or ""))

                def _parse_event_meta(event: dict[str, Any]) -> dict[str, Any]:
                    raw = event["meta_json"] if "meta_json" in event.keys() else None
                    if raw is None and "meta" in event.keys():
                        raw = event["meta"]
                    if not raw:
                        return {}
                    if isinstance(raw, dict):
                        return raw
                    try:
                        return json.loads(raw)
                    except json.JSONDecodeError:
                        return {}

                gap_start: datetime | None = start_dt_utc if privacy_on else None
                gap_actor: str | None = None
                if gap_start is not None:
                    gap_actor = privacy_actor
                for event in privacy_events:
                    event_type = event["event_type"]
                    event_ts = _parse_iso_ts(event["ts"])
                    if not event_ts:
                        continue
                    event_ts = event_ts.astimezone(timezone.utc)
                    actor_value = str(event["actor_id"] or "") or None
                    if event_type == "voice.privacy_on" and gap_start is None:
                        gap_start = event_ts
                        gap_actor = actor_value
                    if event_type == "voice.privacy_off" and gap_start is not None:
                        privacy_intervals.append((gap_start, event_ts, gap_actor))
                        actor_name = None
                        if include_names and gap_actor:
                            actor_name = await ctx.database.fetch_user_display_name(
                                guild_id=str(interaction.guild_id),
                                user_id=str(gap_actor),
                            )
                        disclaimer_line = _build_privacy_disclaimer(gap_start, event_ts, actor_name)
                        privacy_disclaimer_lines.append(disclaimer_line)
                        privacy_moments.append(
                            SummaryItem(
                                ts=gap_start.isoformat(),
                                text=disclaimer_line,
                                author_id=None,
                                message_ids=[],
                                in_call=True,
                            )
                        )
                        gap_start = None
                        gap_actor = None
                if gap_start is not None:
                    privacy_intervals.append((gap_start, None, gap_actor))
                    actor_name = None
                    if include_names and gap_actor:
                        actor_name = await ctx.database.fetch_user_display_name(
                            guild_id=str(interaction.guild_id),
                            user_id=str(gap_actor),
                        )
                    disclaimer_line = _build_privacy_disclaimer(gap_start, None, actor_name)
                    privacy_disclaimer_lines.append(disclaimer_line)
                    privacy_moments.append(
                        SummaryItem(
                            ts=gap_start.isoformat(),
                            text=disclaimer_line,
                            author_id=None,
                            message_ids=[],
                            in_call=True,
                        )
                    )

                for event in privacy_events:
                    if event["event_type"] != "voice.transcript":
                        continue
                    meta = _parse_event_meta(event)
                    session_id = str(meta.get("voice_session_id") or "")
                    session = session_lookup.get(session_id)
                    offset_ms = meta.get("call_offset_ms")
                    try:
                        offset_ms = int(offset_ms) if offset_ms is not None else None
                    except (TypeError, ValueError):
                        offset_ms = None
                    if session and offset_ms is not None:
                        ts_real = session["started"] + timedelta(milliseconds=offset_ms)
                    else:
                        ts_real = _parse_iso_ts(event["ts"])
                    if not ts_real:
                        continue
                    ts_real = ts_real.astimezone(timezone.utc)
                    if ts_real < start_dt_utc or ts_real > end_dt_utc:
                        continue
                    if _is_in_privacy_gap(ts_real.isoformat()):
                        continue
                    content = event["content"] if "content" in event.keys() else None
                    if not content:
                        content = meta.get("content") or meta.get("text") or ""
                    content = str(content or "").strip()
                    if not content:
                        continue
                    _append_event(
                        ts_value=ts_real,
                        text=content,
                        kind="transcript",
                        in_call=True,
                        actor_id=str(event["actor_id"] or "") or None,
                        message_id=str(meta.get("message_id") or "") or None,
                        meta={
                            "in_call": True,
                            "kind": "transcript",
                            "voice_session_id": session_id,
                        },
                    )
                    voice_transcripts += 1

                for moment in forced_moments:
                    if not moment.ts or not moment.text:
                        continue
                    moment_ts = _parse_iso_ts(moment.ts)
                    if moment_ts is None:
                        continue
                    moment_ts = moment_ts.astimezone(timezone.utc)
                    if _is_in_privacy_gap(moment.ts):
                        continue
                    _append_event(
                        ts_value=moment_ts,
                        text=moment.text,
                        kind="call",
                        in_call=True,
                        actor_id=moment.author_id,
                        message_id=None,
                        meta={"in_call": True, "kind": "call"},
                    )

                if privacy_intervals:
                    voice_activity_candidates = [
                        entry.get("ts")
                        for entry in timeline_entries
                        if entry.get("kind") in {"chat", "transcript", "call"}
                        and isinstance(entry.get("ts"), datetime)
                        and start_dt_utc <= entry["ts"] <= end_dt_utc
                    ]
                    last_voice_activity_ts = max(voice_activity_candidates) if voice_activity_candidates else end_dt_utc
                    capped_intervals: list[tuple[datetime, datetime | None, str | None]] = []
                    for start, end, actor in privacy_intervals:
                        if end is None:
                            capped_end = min(last_voice_activity_ts, end_dt_utc)
                            capped_intervals.append((start, capped_end, actor))
                        else:
                            capped_intervals.append((start, end.astimezone(timezone.utc), actor))
                    privacy_intervals = capped_intervals

                logger.info("riassunto: privacy applied on voice events (no pre-build messages filtering)")

                logger.info(
                    "riassunto: voice_context_merge sessions=%s transcripts=%s presence=%s privacy=%s call=%s",
                    voice_sessions,
                    voice_transcripts,
                    voice_presence,
                    privacy_entries,
                    call_entries,
                )

            normalized_timeline_entries: list[dict[str, Any]] = []
            invalid_ts_samples: list[Any] = []
            for entry in timeline_entries:
                ts_value = entry.get("ts")
                ts_dt: datetime | None
                if isinstance(ts_value, datetime):
                    ts_dt = ts_value
                elif isinstance(ts_value, str):
                    ts_dt = _parse_iso_ts(ts_value)
                else:
                    ts_dt = None
                if ts_dt is None:
                    if len(invalid_ts_samples) < 3:
                        invalid_ts_samples.append(ts_value)
                    continue
                normalized_entry = dict(entry)
                normalized_entry["ts"] = ts_dt
                normalized_timeline_entries.append(normalized_entry)
            if invalid_ts_samples:
                logger.warning("riassunto: dropped timeline entries with invalid ts samples=%s", invalid_ts_samples)
            timeline_entries = normalized_timeline_entries

            timeline_before_privacy = len(timeline_entries)
            if privacy_intervals:
                timeline_entries = [
                    entry
                    for entry in timeline_entries
                    if not (
                        entry.get("kind") in {"chat", "transcript", "call"}
                        and isinstance(entry.get("ts"), datetime)
                        and _is_in_privacy_gap_dt(entry["ts"])
                    )
                ]
            logger.info(
                "riassunto: privacy_intervals=%d timeline_before=%d timeline_after=%d",
                len(privacy_intervals),
                timeline_before_privacy,
                len(timeline_entries),
            )

            timeline_after_privacy = len(timeline_entries)

            timeline_entries.sort(key=lambda item: item["ts"])

            messages = [
                {
                    "message_id": entry.get("message_id"),
                    "author_id": str(entry.get("actor_id") or ""),
                    "ts": entry["ts"].isoformat(),
                    "content": str(entry.get("text") or ""),
                    "meta": {
                        "in_call": bool(entry.get("in_call")),
                        "kind": str(entry.get("kind") or ""),
                        **(
                            {
                                key: value
                                for key, value in (entry.get("meta") or {}).items()
                                if key not in {"in_call", "kind"}
                            }
                        ),
                    },
                }
                for entry in timeline_entries
                if str(entry.get("text") or "").strip()
            ]

            MIN_MSG_TOTAL_CHANNEL = 8
            content_messages = [
                msg
                for msg in messages
                if (msg.get("content") or "").strip()
                and msg.get("meta", {}).get("kind") in {"chat", "transcript"}
            ]
            if len(content_messages) < MIN_MSG_TOTAL_CHANNEL:
                if (
                    channel_is_voice
                    and timeline_before_privacy >= MIN_MSG_TOTAL_CHANNEL
                    and timeline_after_privacy < MIN_MSG_TOTAL_CHANNEL
                ):
                    await interaction.followup.send(
                        (
                            "❗ Molti contenuti nel periodo selezionato sono stati esclusi per Privacy Mode "
                            f"(prima: {timeline_before_privacy} eventi, dopo filtro: {timeline_after_privacy}). "
                            "Prova ad allargare il periodo o verifica che la privacy venga disattivata correttamente."
                        ),
                        ephemeral=True,
                    )
                else:
                    await interaction.followup.send(
                        "❗ Non ci sono dati sufficienti nel periodo selezionato per generare un riassunto.",
                        ephemeral=True,
                    )
                return

            extra_sections: list[tuple[str, str, int]] | None = None
            if channel_is_voice:
                show_participant_names = include_names and not privacy_intervals
                join_names: list[str] = []
                leave_names: list[str] = []
                for event in participant_join_events:
                    name = str(event.get("username") or event.get("user_id") or "utente")
                    if name not in join_names:
                        join_names.append(name)
                for event in participant_leave_events:
                    name = str(event.get("username") or event.get("user_id") or "utente")
                    if name not in leave_names:
                        leave_names.append(name)
                move_count = len(participant_move_events)
                if show_participant_names:
                    join_preview = ", ".join(join_names[:10]) if join_names else "nessuno"
                    leave_preview = ", ".join(leave_names[:10]) if leave_names else "nessuno"
                    participant_lines = [
                        f"• Entrati: {len(participant_join_events)} ({join_preview})",
                        f"• Usciti: {len(participant_leave_events)} ({leave_preview})",
                    ]
                else:
                    participant_lines = [
                        f"• Entrati: {len(participant_join_events)} utenti",
                        f"• Usciti: {len(participant_leave_events)} utenti",
                    ]
                if move_count:
                    participant_lines.append(f"• Spostamenti verso il canale: {move_count}")
                extra_sections = [("👥 PARTECIPANTI (Vocale)", "\n".join(participant_lines), 2)]

            metrics = dict(barcello_result.metrics or {})
            metrics.update(
                {
                    "voice_minutes": voice_minutes,
                    "voice_sessions": voice_sessions,
                    "voice_segments": voice_segments + voice_transcripts,
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

            dm_mode = True

            status_embed = _build_riassunto_status_embed(
                result=barcello_result,
                channel_label=channel_label,
                period_label=period_label,
                period_description=period_description,
            )
            if dm_mode:
                status_embed.title = _bold_header(status_embed.title)
                attach_footer_meta(status_embed, service_name="riassunto", used_local_processing=True)

            model_name = ctx.ai.get_model("summary") if ctx.ai else None
            cache_key = ctx.summary_service.build_cache_key(
                guild_id=str(interaction.guild_id),
                channel_id=str(interaction.channel_id),
                start_ts=start_dt_utc.isoformat(),
                end_ts=end_dt_utc.isoformat(),
                tier=profile,
                evidence_mode=False,
                summary_mode="default",
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
                granularity_hint=granularity_hint,
            )

            if channel_is_voice and (privacy_moments or supplemental_moments):
                existing_texts = {moment.text.lower() for moment in summary.moments}
                filtered_privacy: list[SummaryItem] = []
                filtered_supplemental: list[SummaryItem] = []
                for moment in privacy_moments:
                    if moment.text and moment.text.lower() not in existing_texts:
                        filtered_privacy.append(moment)
                        existing_texts.add(moment.text.lower())
                for moment in supplemental_moments:
                    if moment.text and moment.text.lower() not in existing_texts:
                        filtered_supplemental.append(moment)
                        existing_texts.add(moment.text.lower())
                combined = sorted(
                    summary.moments + filtered_supplemental + filtered_privacy,
                    key=lambda item: (not bool(item.ts), item.ts or ""),
                )
                moment_limit = tier_config.get("limits", {}).get("moments", 10)
                try:
                    moment_limit = int(moment_limit)
                except (TypeError, ValueError):
                    moment_limit = 10
                privacy_set = {id(item) for item in filtered_privacy}
                while len(combined) > moment_limit:
                    idx = next(
                        (i for i in range(len(combined) - 1, -1, -1) if id(combined[i]) not in privacy_set),
                        None,
                    )
                    if idx is None:
                        break
                    combined.pop(idx)
                summary.moments = combined

            if channel_is_voice and voice_session_ranges:
                def _is_ts_in_call(ts: str | None) -> bool:
                    parsed = _parse_iso_ts(ts)
                    if not parsed:
                        return False
                    return any(start <= parsed <= end for start, end in voice_session_ranges)

                for moment in summary.moments:
                    moment.in_call = moment.in_call or _is_ts_in_call(moment.ts)
                for quote in summary.quotes:
                    quote.in_call = quote.in_call or _is_ts_in_call(quote.ts)
                for dynamic in summary.dynamics:
                    dynamic.in_call = dynamic.in_call or _is_ts_in_call(dynamic.ts)

            name_map: dict[str, str] = {}
            if interaction.guild:
                for msg in messages:
                    author_id = msg.get("author_id")
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

            def _should_show_name(content_origin: str) -> bool:
                if not channel_is_voice:
                    return bool(ctx.config.name_policy_text_show_names_always)
                if content_origin == "chat":
                    return bool(ctx.config.name_policy_voice_show_names_for_chat_messages)
                if not bool(ctx.config.name_policy_voice_show_names_for_voice_transcripts_when_green_only):
                    return True
                return barcello_color == "verde"

            async def fetch_message_record(message_id: str) -> dict[str, Any] | None:
                if message_id in message_cache:
                    return message_cache[message_id]
                row = await ctx.database.fetch_message_by_id(
                    channel_id=str(interaction.channel_id),
                    message_id=message_id,
                )
                if row:
                    embeds_raw = row["embeds_json"] if "embeds_json" in row.keys() else None
                    embeds = json.loads(embeds_raw) if embeds_raw else []
                    is_voice_transcript = any(
                        isinstance(embed, dict) and embed.get("source") == "voice_ingest_stt" for embed in embeds
                    )
                    record = {
                        "author_id": row["author_id"],
                        "content": row["content"],
                        "origin": "voice_transcript" if is_voice_transcript else "chat",
                    }
                    message_cache[message_id] = record
                    return record
                return None

            async def resolve_author_display_name(message_id: str | None) -> str | None:
                if not message_id or interaction.guild is None:
                    return None
                record = await fetch_message_record(message_id)
                if not record:
                    return None
                if not _should_show_name(str(record.get("origin") or "chat")):
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
                return build_summary_detail_embeds(
                    profile=profile,
                    summary=summary,
                    include_names=include_names,
                    include_date_in_time=include_date_in_time,
                    guild_id=interaction.guild_id,
                    channel_id=interaction.channel_id,
                    name_map=name_map,
                    moment_primary=moment_primary,
                    quote_primary=quote_primary,
                    dynamic_primary=dynamic_primary,
                    impact_primary=impact_primary,
                    moment_display=moment_display,
                    quote_display=quote_display,
                    dynamic_names=dynamic_names,
                    quote_texts=quote_texts,
                    privacy_intervals=[("", "")] if privacy_intervals else None,
                    privacy_disclaimer_lines=privacy_disclaimer_lines,
                    metrics_report=metrics_report,
                    extra_sections=extra_sections,
                    tier_label=tier_label,
                    tier_config=tier_config,
                    details_color=details_color,
                    req_id=req_id,
                    format_moment_line=_format_summary_moment_line,
                    format_quote_line=_format_summary_quote_line,
                    format_dynamic_line=_format_summary_dynamics_line,
                    format_impact_line=_format_summary_impact_line,
                    format_bullets=_format_bullets,
                    dm_mode=dm_mode,
                )

            embeds = build_embeds()
            if dm_mode and embeds:
                ai_used = bool(summary.ai_status.get("reason") == "ok")
                ai_model_name = str(summary.ai_status.get("model") or model_name or "unknown-model") if ai_used else ""
                attach_footer_meta(
                    embeds[-1],
                    service_name="riassunto",
                    contributors=[ai_model_name] if ai_used else [],
                    used_local_processing=not ai_used,
                )

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
            payload_embeds = _sanitize_embeds_for_discord_limits([*normalized_status, *normalized_details], req_id=req_id)
            payload_embeds = _ensure_embed_limits(payload_embeds, max_chars=5600)
            payload_embeds = _sanitize_embeds_for_discord_limits(payload_embeds, req_id=req_id)
            metrics_file = build_metrics_attachment()
            files = [metrics_file] if metrics_file else None
            logger.info(
                "riassunto send embeds req_id=%s status_embeds=%s detail_embeds=%s",
                req_id,
                len(normalized_status),
                len(normalized_details),
            )
            for embed_idx, embed in enumerate(payload_embeds, start=1):
                for field_idx, field in enumerate(embed.fields, start=1):
                    if len(field.name or "") > 256 or len(field.value or "") > 1024:
                        logger.warning(
                            "riassunto: final hard truncation req_id=%s embed=%s field=%s",
                            req_id,
                            embed_idx,
                            field_idx,
                        )
                        embed.set_field_at(
                            index=field_idx - 1,
                            name=_truncate_text(field.name or "", 256),
                            value=_truncate_text(field.value or "", 1024),
                            inline=field.inline,
                        )
                if embed.description and len(embed.description) > 4096:
                    logger.warning("riassunto: final description hard truncation req_id=%s embed=%s", req_id, embed_idx)
                    embed.description = _truncate_text(embed.description, 4096)
            sent_dm = await send_dm_or_followup(
                interaction,
                embeds=payload_embeds,
                content="⚠️ Non posso inviarti DM, quindi ti mostro il riassunto qui in modalità privata.",
                files=files,
                ephemeral_fallback=True,
            )
            if sent_dm:
                await interaction.followup.send("✅ Ti ho inviato il riassunto in DM.", ephemeral=True)
        except Exception:
            logger.exception("riassunto failed req_id=%s", req_id)
            await send_ephemeral(
                interaction,
                f"❌ Errore durante il riassunto (ID: {req_id}). Controlla i log.",
            )
            return

    @riassunto_group.command(name="ultimi", description="Riassunto ultimi N periodi")
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
        window, error = resolve_ultimi_window(quantita, unita.value, ctx.config)
        if error:
            await send_ephemeral(interaction, error)
            return
        assert window is not None
        await _run_riassunto(
            interaction,
            start_dt=window.start_dt,
            end_dt=window.end_dt,
            period_label="ultimi",
            granularity_hint=_granularity_hint_for_period("ultimi", unita.value),
        )

    @riassunto_group.command(name="oggi", description="Riassunto della giornata di oggi")
    async def riassunto_oggi(interaction: discord.Interaction) -> None:
        window = resolve_oggi_window()
        await _run_riassunto(interaction, start_dt=window.start_dt, end_dt=window.end_dt, period_label="oggi", granularity_hint="hours")

    @riassunto_group.command(name="ieri", description="Riassunto della giornata di ieri")
    async def riassunto_ieri(interaction: discord.Interaction) -> None:
        window = resolve_ieri_window()
        await _run_riassunto(interaction, start_dt=window.start_dt, end_dt=window.end_dt, period_label="ieri", granularity_hint="days")

    @riassunto_group.command(name="range", description="Riassunto per intervallo")
    @app_commands.describe(da="Da (DD/MM/YYYY HH:MM)", a="A (DD/MM/YYYY HH:MM)")
    async def riassunto_range(interaction: discord.Interaction, da: str, a: str) -> None:
        window, error = resolve_range_window(da, a, ctx.config)
        if error:
            await send_ephemeral(interaction, error)
            return
        assert window is not None
        await _run_riassunto(interaction, start_dt=window.start_dt, end_dt=window.end_dt, period_label="range", granularity_hint="days")

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

    def _truncate_moment_line(line: str, *, max_tail: int) -> str:
        raw = str(line).strip()
        if not raw:
            return ""
        prefix, separator, tail = raw.partition(" — ")
        if not separator:
            if len(raw) <= max_tail:
                return raw
            if max_tail <= 1:
                return "…"
            return f"{raw[: max_tail - 1].rstrip()}…"
        tail = tail.strip()
        if len(tail) <= max_tail:
            return f"{prefix}{separator}{tail}"
        if max_tail <= 1:
            return f"{prefix}{separator}…"
        return f"{prefix}{separator}{tail[: max_tail - 1].rstrip()}…"
