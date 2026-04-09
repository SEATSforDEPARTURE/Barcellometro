from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Callable, Optional
import unicodedata

import discord
from discord import app_commands

from app.plugins.commands_modular.registration import add_group_once, count_child_commands
from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.time_windows import parse_italian_datetime
from app.services.campaign_content_fetchers import (
    NEWS_CATEGORY_ALIASES,
    NEWS_CATEGORY_CATALOG,
    NEWS_SOURCE_ALIASES,
    NEWS_SOURCE_CATALOG,
)
from app.services.scheduler_utils import calculate_initial_next_run
from app.shared.discord.command_embeds import CommandEmbedSection, CommandKind, send_standard_response

QUIET_DEFAULT_START = "01:00"
QUIET_DEFAULT_END = "08:30"
CAP_DEFAULT = 6

logger = logging.getLogger(__name__)

MOOD_CHOICES = [
    app_commands.Choice(name="AUTO", value="AUTO"),
    app_commands.Choice(name="IGNORE_BARCELLO", value="IGNORE_BARCELLO"),
    app_commands.Choice(name="GREEN_ONLY", value="GREEN_ONLY"),
    app_commands.Choice(name="YELLOW_ONLY", value="YELLOW_ONLY"),
    app_commands.Choice(name="RED_ONLY", value="RED_ONLY"),
    app_commands.Choice(name="BLACK_ONLY", value="BLACK_ONLY"),
]

NEWS_SOURCE_CHOICES = [str(entry["value"]).strip().lower() for entry in NEWS_SOURCE_CATALOG]
NEWS_SOURCE_LABELS = {str(entry["value"]).strip().lower(): str(entry["label"]).strip() for entry in NEWS_SOURCE_CATALOG}
NEWS_CATEGORY_CHOICES = [str(entry["value"]).strip().lower() for entry in NEWS_CATEGORY_CATALOG]
NEWS_CATEGORY_LABELS = {str(entry["value"]).strip().lower(): str(entry["label"]).strip() for entry in NEWS_CATEGORY_CATALOG}
NEWS_EXTRA_CHOICES = ["barzelletta", "aforisma", "canzone", "meme"]
NEWS_EXTRA_LABELS = {
    "barzelletta": "barzelletta",
    "aforisma": "aforisma",
    "canzone": "canzone",
    "meme": "meme",
}


def _fold_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in normalized if not unicodedata.combining(char)).strip().lower()


async def _ensure_setting(ctx: CommandContext, key: str, default: str) -> str:
    stored = await ctx.database.get_setting(key)
    if stored is None:
        await ctx.database.set_setting(key, default)
        return default
    return stored


def _truncate(text: str, limit: int = 100) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _resolve_schedule(*, publish_at: Optional[str], every: Optional[int], now_utc: datetime, tz) -> tuple[datetime, str, int]:
    resolved_every = int(every or 0)
    if resolved_every < 0:
        raise ValueError("every must be greater than or equal to 0")
    raw_publish = str(publish_at or "").strip()
    publish_dt = parse_italian_datetime(raw_publish) if raw_publish else None
    if raw_publish and publish_dt is None:
        raise ValueError("Invalid publish_at format. Use DD/MM/YYYY HH:MM")
    if publish_dt is None:
        publish_dt = now_utc.astimezone(tz)
    return publish_dt.astimezone(timezone.utc), publish_dt.astimezone(tz).strftime("%H:%M"), resolved_every


def validate_campaign_texts(
    *,
    text: Optional[str],
    text_green: Optional[str],
    text_yellow: Optional[str],
    text_red: Optional[str],
    text_black: Optional[str],
    mood_mode: str,
) -> Optional[str]:
    values = [text, text_green, text_yellow, text_red, text_black]
    if not any(value for value in values):
        return (
            "Provide at least `text` as fallback or one of `text_green`, `text_yellow`, "
            "`text_red`, `text_black`."
        )
    if mood_mode == "IGNORE_BARCELLO" and not text:
        return "When mood_mode=IGNORE_BARCELLO you must provide `text`."
    return None


def _parse_csv(raw: Optional[str]) -> list[str]:
    return [item.strip() for item in str(raw or "").split(",") if item.strip()]


def _split_csv_for_autocomplete(raw: str) -> tuple[list[str], str]:
    segments = str(raw or "").split(",")
    confirmed_tokens = [segment.strip() for segment in segments[:-1] if segment.strip()]
    active_token = segments[-1].strip() if segments else ""
    return confirmed_tokens, active_token


def _normalize_csv_values(raw: Optional[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in _parse_csv(raw):
        token = str(item).strip().lower()
        if not token or token in seen:
            continue
        seen.add(token)
        normalized.append(token)
    return normalized


def _parse_guided_csv_values(
    raw: Optional[str],
    *,
    allowed: list[str],
    aliases: dict[str, str] | None = None,
    normalizer: Callable[[str], str] | None = None,
) -> tuple[list[str], list[str]]:
    aliases = aliases or {}
    normalize = normalizer or (lambda token: str(token or "").strip().lower())
    allowed_map = {normalize(token): token for token in allowed}
    normalized: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()

    for raw_token in _parse_csv(raw):
        raw_clean = str(raw_token).strip()
        folded = normalize(raw_clean)
        canonical = aliases.get(folded) or allowed_map.get(folded)
        if canonical is None:
            canonical = aliases.get(raw_clean.lower())
        if canonical is None:
            invalid.append(raw_clean.lower())
            continue
        canonical_clean = str(canonical).strip().lower()
        if canonical_clean in seen:
            continue
        seen.add(canonical_clean)
        normalized.append(canonical_clean)
    return normalized, invalid


def _compose_guided_csv_suggestions(
    current: str,
    *,
    allowed_values: list[str],
    preferred_labels: dict[str, str] | None = None,
    aliases: dict[str, str] | None = None,
    normalizer: Callable[[str], str] | None = None,
) -> list[app_commands.Choice[str]]:
    preferred_labels = preferred_labels or {}
    aliases = aliases or {}
    normalize = normalizer or (lambda token: str(token or "").strip().lower())
    confirmed_tokens, active_token = _split_csv_for_autocomplete(current)
    fragment = normalize(active_token)

    selected: set[str] = set()
    normalized_confirmed_tokens: list[str] = []
    for part in confirmed_tokens:
        folded = normalize(part)
        canonical = str(aliases.get(folded, folded)).strip().lower()
        if canonical in selected:
            continue
        selected.add(canonical)
        normalized_confirmed_tokens.append(canonical)

    logger.debug(
        "guided_csv_autocomplete raw=%r confirmed=%s active=%r",
        current,
        normalized_confirmed_tokens,
        active_token,
    )

    base = ", ".join((preferred_labels.get(token, token) for token in normalized_confirmed_tokens))
    suggestions: list[app_commands.Choice[str]] = []
    emitted_values: set[str] = set()
    for token in allowed_values:
        canonical = str(token).strip().lower()
        if canonical in selected:
            continue
        candidate = normalize(canonical)
        if fragment and not candidate.startswith(fragment):
            continue
        selected_label = preferred_labels.get(canonical, canonical)
        value = f"{base}, {selected_label}" if base else selected_label
        folded_value = _fold_token(value)
        if folded_value in emitted_values:
            continue
        emitted_values.add(folded_value)
        label = preferred_labels.get(canonical, canonical)
        suggestions.append(app_commands.Choice(name=label[:100], value=value[:100]))
        if len(suggestions) >= 25:
            break
    logger.debug("guided_csv_autocomplete suggestions=%d", len(suggestions))
    return suggestions


def _format_message_campaign_row(row: dict[str, object]) -> str:
    variants = [
        f"B{'✅' if row.get('text') else '—'}",
        f"G{'✅' if row.get('text_green') else '—'}",
        f"Y{'✅' if row.get('text_yellow') else '—'}",
        f"R{'✅' if row.get('text_red') else '—'}",
        f"K{'✅' if row.get('text_black') else '—'}",
    ]
    frequency = "one-shot" if int(row.get("interval_minutes") or 0) <= 0 else f"every {row.get('interval_minutes')}m"
    return " | ".join(
        [
            f"ID {row.get('id')}",
            f"type {row.get('type')}",
            "on" if bool(row.get("enabled")) else "off",
            f"channel {row.get('channel_id')}",
            f"name {row.get('name') or '-'}",
            frequency,
            f"publish_at {row.get('start_time_local')}",
            f"jitter {row.get('jitter_seconds')}s",
            f"idle {row.get('only_if_idle_minutes')}m",
            f"mood_mode {row.get('mood_mode')}",
            f"variants {' '.join(variants)}",
            f"last {row.get('last_sent_at') or '-'}",
            f"next {row.get('next_run_at') or '-'}",
            f"embed_title {row.get('embed_title') or '-'}",
            f"embed_color {row.get('embed_color') or '-'}",
            f"text {_truncate(str(row.get('text') or '—'))}",
        ]
    )


def _format_service_config_row(row: dict[str, object]) -> str:
    frequency = "one-shot" if int(row.get("interval_minutes") or 0) <= 0 else f"every {row.get('interval_minutes')}m"
    sources = _parse_csv(str(row.get("sources_json") or "").replace("[", "").replace("]", ""))
    return " | ".join(
        [
            f"ID {row.get('id')}",
            f"service {row.get('service_type')}",
            "on" if bool(row.get("enabled")) else "off",
            f"channel {row.get('channel_id')}",
            frequency,
            f"publish_at {row.get('time_local')}",
            f"next {row.get('next_run_at') or '-'}",
            f"embed_title {row.get('embed_title') or '-'}",
            f"embed_color {row.get('embed_color') or '-'}",
            f"sources {row.get('sources_json') or '[]'}",
            f"categories {row.get('categories_json') or '-'}",
            f"extras {row.get('extras_json') or '-'}",
        ]
    )


def register_messaggi(campaigns_group: app_commands.Group, ctx: CommandContext, *, top_level: str = "campaigns", visual_top_level: str = "campaigns") -> None:
    quiet_group = app_commands.Group(name="quiet", description="Quiet hours controls")
    cap_group = app_commands.Group(name="cap", description="Daily cap controls")
    custom_group = app_commands.Group(name="custom", description="Custom campaign schedules")
    news_group = app_commands.Group(name="news", description="News campaign controls")
    weather_group = app_commands.Group(name="weather", description="Weather campaign controls")
    horoscope_group = app_commands.Group(name="horoscope", description="Horoscope campaign controls")

    for group in (quiet_group, cap_group, custom_group, news_group, weather_group, horoscope_group):
        add_group_once(campaigns_group, group, logger)

    logger.debug(
        "Registered /%s with children=%d",
        campaigns_group.qualified_name or campaigns_group.name,
        count_child_commands(campaigns_group),
    )

    async def _check(interaction: discord.Interaction, *permission_keys: str) -> bool:
        candidates = [str(permission_key).strip() for permission_key in permission_keys if str(permission_key).strip()]
        for permission_key in candidates:
            if await check_permission(interaction, permission_key, ctx):
                return True
        return False

    async def _send(
        interaction: discord.Interaction,
        *,
        subcommand_path: str,
        subtitle_args: list[object] | None = None,
        lines: list[tuple[str, object]] | None = None,
        sections: list[CommandEmbedSection] | None = None,
        kind: CommandKind = "info",
    ) -> None:
        await send_standard_response(
            interaction,
            top_level=top_level,
            subcommand_path=subcommand_path,
            visual_top_level=visual_top_level,
            subtitle_args=subtitle_args,
            lines=lines,
            sections=sections,
            kind=kind,
            footer_service=ctx.footer,
        )

    async def _require_guild_channel(interaction: discord.Interaction, *, subcommand_path: str) -> tuple[str, str] | None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await _send(interaction, subcommand_path=subcommand_path, lines=[("error", "Use this command in a guild channel.")], kind="error")
            return None
        return str(interaction.guild_id), str(interaction.channel_id)

    async def _require_guild(interaction: discord.Interaction, *, subcommand_path: str) -> str | None:
        if interaction.guild_id is None:
            await _send(interaction, subcommand_path=subcommand_path, lines=[("error", "Use this command in a guild.")], kind="error")
            return None
        return str(interaction.guild_id)

    async def _list_custom_campaigns(guild_id: str) -> list[dict[str, object]]:
        rows = await ctx.database.list_message_campaigns(guild_id, include_disabled=True)
        return [dict(row) for row in rows if str(row["type"]).upper() == "CUSTOM"]

    async def _get_custom_campaign(guild_id: str, campaign_id: int) -> dict[str, object] | None:
        row = await ctx.database.get_message_campaign(guild_id, campaign_id)
        if row is None or str(row["type"]).upper() != "CUSTOM":
            return None
        return dict(row)

    async def _validate_embed_color(interaction: discord.Interaction, embed_color: Optional[str], *, subcommand_path: str) -> bool:
        if ctx.message_scheduler is None:
            return True
        if ctx.message_scheduler.is_valid_embed_color(embed_color):
            return True
        await _send(interaction, subcommand_path=subcommand_path, lines=[("error", "Invalid embed_color. Use #RRGGBB, RRGGBB, or 0xRRGGBB.")], kind="error")
        return False

    async def _custom_toggle(interaction: discord.Interaction, action: str) -> None:
        subcommand_path = f"campaigns custom {action}"
        if not await _check(interaction, f"campaigns.custom.{action}", f"campagne.custom.{action}"):
            return
        scope = await _require_guild_channel(interaction, subcommand_path=subcommand_path)
        if scope is None:
            return
        guild_id, channel_id = scope
        rows = [row for row in await _list_custom_campaigns(guild_id) if str(row.get("channel_id")) == channel_id]
        if action == "status":
            enabled_count = sum(1 for row in rows if bool(row.get("enabled")))
            await _send(interaction, subcommand_path=subcommand_path, lines=[("enabled", f"{enabled_count}/{len(rows)}"), ("channel", f"<#{channel_id}>")])
            return
        enabled = action == "on"
        for row in rows:
            await ctx.database.set_message_campaign_enabled(guild_id, int(row["id"]), enabled)
        await _send(interaction, subcommand_path=subcommand_path, lines=[("channel", f"<#{channel_id}>"), ("schedules", len(rows)), ("result", "enabled" if enabled else "disabled")], kind="success")

    async def _build_service_run_payload(guild_id: str, channel_id: str, service_type: str) -> dict[str, object] | None:
        row = await ctx.database.get_campaign_content_config_by_service(guild_id, channel_id, service_type)
        return dict(row) if row is not None else None

    async def _news_sources_autocomplete(_: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return _compose_guided_csv_suggestions(
            current,
            allowed_values=NEWS_SOURCE_CHOICES,
            preferred_labels=NEWS_SOURCE_LABELS,
            aliases=NEWS_SOURCE_ALIASES,
        )

    async def _news_categories_autocomplete(_: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return _compose_guided_csv_suggestions(
            current,
            allowed_values=NEWS_CATEGORY_CHOICES,
            preferred_labels=NEWS_CATEGORY_LABELS,
            aliases=NEWS_CATEGORY_ALIASES,
            normalizer=_fold_token,
        )

    async def _news_extras_autocomplete(_: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return _compose_guided_csv_suggestions(
            current,
            allowed_values=NEWS_EXTRA_CHOICES,
            preferred_labels=NEWS_EXTRA_LABELS,
        )

    async def _get_service_schedule(guild_id: str, service_type: str, schedule_id: int) -> dict[str, object] | None:
        row = await ctx.database.get_campaign_content_config(guild_id, schedule_id)
        if row is None or str(row["service_type"]).upper() != service_type:
            return None
        return dict(row)

    async def _set_service_enabled(interaction: discord.Interaction, *, service_type: str, action: str) -> None:
        subcommand_path = f"campaigns {service_type.lower()} {action}"
        if not await _check(interaction, f"campaigns.{service_type.lower()}.{action}", f"campagne.{service_type.lower()}.{action}"):
            return
        scope = await _require_guild_channel(interaction, subcommand_path=subcommand_path)
        if scope is None:
            return
        guild_id, channel_id = scope
        rows = [
            dict(row)
            for row in await ctx.database.list_campaign_content_configs_by_service(
                guild_id,
                service_type=service_type,
                channel_id=channel_id,
                include_disabled=True,
            )
        ]
        if action == "status":
            enabled_count = sum(1 for row in rows if bool(row.get("enabled")))
            latest = rows[-1] if rows else None
            if latest is None:
                await _send(interaction, subcommand_path=subcommand_path, lines=[("enabled", f"{enabled_count}/{len(rows)}"), ("warning", "No schedules found for this channel.")], kind="warning")
                return
            await _send(interaction, subcommand_path=subcommand_path, lines=[("enabled", f"{enabled_count}/{len(rows)}"), ("channel", f"<#{channel_id}>")], sections=[CommandEmbedSection(title="Latest", lines=[_format_service_config_row(latest)])])
            return
        enabled = action == "on"
        for row in rows:
            await ctx.database.set_campaign_content_enabled(guild_id, int(row["id"]), enabled)
        await _send(interaction, subcommand_path=subcommand_path, lines=[("channel", f"<#{channel_id}>"), ("schedules", len(rows)), ("result", "enabled" if enabled else "disabled")], kind="success")

    async def _service_schedule_show(
        interaction: discord.Interaction,
        *,
        service_type: str,
        schedule_id: int,
    ) -> None:
        if not await _check(interaction, f"campaigns.{service_type.lower()}.schedule_show", f"campagne.{service_type.lower()}.schedule_show"):
            return
        subcommand_path = f"campaigns {service_type.lower()} schedule_show"
        guild_id = await _require_guild(interaction, subcommand_path=subcommand_path)
        if guild_id is None:
            return
        row = await _get_service_schedule(guild_id, service_type, schedule_id)
        if row is None:
            await _send(interaction, subcommand_path=subcommand_path, lines=[("warning", f"{service_type.title()} schedule not found.")], kind="warning")
            return
        await _send(interaction, subcommand_path=subcommand_path, subtitle_args=[schedule_id], lines=[("schedule_id", schedule_id), ("channel", f"<#{row['channel_id']}>")], sections=[CommandEmbedSection(title="Schedule", lines=[_format_service_config_row(row)])])

    async def _service_schedule_remove(
        interaction: discord.Interaction,
        *,
        service_type: str,
        schedule_id: int,
    ) -> None:
        if not await _check(interaction, f"campaigns.{service_type.lower()}.schedule_remove", f"campagne.{service_type.lower()}.schedule_remove"):
            return
        subcommand_path = f"campaigns {service_type.lower()} schedule_remove"
        guild_id = await _require_guild(interaction, subcommand_path=subcommand_path)
        if guild_id is None:
            return
        row = await _get_service_schedule(guild_id, service_type, schedule_id)
        if row is None:
            await _send(interaction, subcommand_path=subcommand_path, lines=[("warning", f"{service_type.title()} schedule not found.")], kind="warning")
            return
        await ctx.database.soft_delete_campaign_content_config(guild_id, schedule_id)
        await _send(interaction, subcommand_path=subcommand_path, subtitle_args=[schedule_id], lines=[("schedule_id", schedule_id), ("result", "removed")], kind="success")

    async def _service_schedule_list(
        interaction: discord.Interaction,
        *,
        service_type: str,
    ) -> None:
        if not await _check(interaction, f"campaigns.{service_type.lower()}.schedule_list", f"campagne.{service_type.lower()}.schedule_list"):
            return
        subcommand_path = f"campaigns {service_type.lower()} schedule_list"
        guild_id = await _require_guild(interaction, subcommand_path=subcommand_path)
        if guild_id is None:
            return
        rows = [
            dict(row)
            for row in await ctx.database.list_campaign_content_configs_by_service(
                guild_id,
                service_type=service_type,
                include_disabled=True,
            )
        ]
        if not rows:
            await _send(interaction, subcommand_path=subcommand_path, lines=[("warning", f"No {service_type.lower()} schedules configured.")], kind="warning")
            return
        await _send(interaction, subcommand_path=subcommand_path, lines=[("schedules", len(rows))], sections=[CommandEmbedSection(title="Schedules", lines=[_format_service_config_row(row) for row in rows])])

    async def _service_run(
        interaction: discord.Interaction,
        *,
        service_type: str,
        schedule_id: int | None = None,
    ) -> None:
        if not await _check(interaction, f"campaigns.{service_type.lower()}.run", f"campagne.{service_type.lower()}.run"):
            return
        subcommand_path = f"campaigns {service_type.lower()} run"
        scope = await _require_guild_channel(interaction, subcommand_path=subcommand_path)
        if scope is None:
            return
        guild_id, channel_id = scope
        if schedule_id is not None:
            by_id = await ctx.database.get_campaign_content_config(guild_id, schedule_id)
            if by_id is None:
                await _send(interaction, subcommand_path=subcommand_path, subtitle_args=[schedule_id], lines=[("warning", "Schedule not found.")], kind="warning")
                return
            row = dict(by_id)
            if str(row.get("service_type") or "").upper() != service_type:
                await _send(interaction, subcommand_path=subcommand_path, subtitle_args=[schedule_id], lines=[("error", f"Schedule ID {schedule_id} is not a {service_type.lower()} schedule.")], kind="error")
                return
        else:
            scoped_rows = [
                dict(candidate)
                for candidate in await ctx.database.list_campaign_content_configs_by_service(
                    guild_id,
                    service_type=service_type,
                    channel_id=channel_id,
                    include_disabled=True,
                )
            ]
            if not scoped_rows:
                await _send(interaction, subcommand_path=subcommand_path, lines=[("warning", f"No {service_type.lower()} schedule found for this channel.")], kind="warning")
                return
            if len(scoped_rows) > 1:
                await _send(interaction, subcommand_path=subcommand_path, lines=[("error", f"Multiple {service_type.lower()} schedules found in this channel. Specify `id`.")], kind="error")
                return
            row = scoped_rows[0]
        service = getattr(ctx.message_scheduler, "_campaign_content_service", None) if ctx.message_scheduler is not None else None
        if service is None:
            await _send(interaction, subcommand_path=subcommand_path, lines=[("error", "Campaign content service unavailable.")], kind="error")
            return
        await _send(
            interaction,
            subcommand_path=subcommand_path,
            subtitle_args=[schedule_id] if schedule_id is not None else None,
            lines=[("schedule_id", row.get("id")), ("channel", f"<#{row.get('channel_id')}>"), ("result", "running")],
            kind="success",
        )
        if service_type == "NEWS":
            await service.execute_news_service(row)
        elif service_type == "WEATHER":
            await service.execute_weather_service(row)
        elif service_type == "HOROSCOPE":
            await service.execute_horoscope_service(row)

    async def _service_schedule_add(
        interaction: discord.Interaction,
        *,
        service_type: str,
        publish_at: str | None,
        every: int | None,
        embed_title: str | None,
        embed_color: str | None,
        sources: str | None,
        categories: str | None,
        extras: str | None = None,
    ) -> None:
        if not await _check(interaction, f"campaigns.{service_type.lower()}.schedule_add", f"campagne.{service_type.lower()}.schedule_add"):
            return
        subcommand_path = f"campaigns {service_type.lower()} schedule_add"
        scope = await _require_guild_channel(interaction, subcommand_path=subcommand_path)
        if scope is None:
            return
        if not await _validate_embed_color(interaction, embed_color, subcommand_path=subcommand_path):
            return
        guild_id, channel_id = scope

        now = datetime.now(timezone.utc)
        try:
            next_run, time_local, interval_minutes = _resolve_schedule(
                publish_at=publish_at,
                every=every,
                now_utc=now,
                tz=ctx.timezone,
            )
        except ValueError as exc:
            await _send(interaction, subcommand_path=subcommand_path, lines=[("error", str(exc))], kind="error")
            return
        sources_json = json.dumps(_normalize_csv_values(sources), ensure_ascii=False)
        config_id = await ctx.database.create_campaign_content_config(
            guild_id=guild_id,
            channel_id=channel_id,
            service_type=service_type,
            enabled=True,
            time_local=time_local,
            interval_minutes=interval_minutes,
            embed_title=embed_title,
            embed_color=embed_color,
            sources_json=sources_json,
            categories_json=",".join(_normalize_csv_values(categories)) if categories is not None else None,
            extras_json=json.dumps(_normalize_csv_values(extras), ensure_ascii=False) if extras is not None else None,
            next_run_at=next_run.isoformat(),
        )
        await _send(interaction, subcommand_path=subcommand_path, subtitle_args=[config_id], lines=[("schedule_id", config_id), ("next_run", next_run.isoformat()), ("result", "created")], kind="success")

    async def _service_schedule_edit(
        interaction: discord.Interaction,
        *,
        service_type: str,
        schedule_id: int,
        publish_at: str | None,
        every: int | None,
        embed_title: str | None,
        embed_color: str | None,
        enabled: bool | None,
        sources: str | None = None,
        categories: str | None = None,
        extras: str | None = None,
    ) -> None:
        if not await _check(interaction, f"campaigns.{service_type.lower()}.schedule_edit", f"campagne.{service_type.lower()}.schedule_edit"):
            return
        subcommand_path = f"campaigns {service_type.lower()} schedule_edit"
        guild_id = await _require_guild(interaction, subcommand_path=subcommand_path)
        if guild_id is None:
            return
        schedule = await _get_service_schedule(guild_id, service_type, schedule_id)
        if schedule is None:
            await _send(interaction, subcommand_path=subcommand_path, lines=[("warning", f"{service_type.title()} schedule not found.")], kind="warning")
            return
        if embed_color is not None and not await _validate_embed_color(interaction, embed_color, subcommand_path=subcommand_path):
            return

        next_run_at: str | None = None
        time_local: str | None = None
        interval_minutes: int | None = None
        if publish_at is not None or every is not None:
            now = datetime.now(timezone.utc)
            current_every = every if every is not None else int(schedule.get("interval_minutes") or 0)
            try:
                if publish_at is not None:
                    next_run, time_local, interval_minutes = _resolve_schedule(
                        publish_at=publish_at,
                        every=current_every,
                        now_utc=now,
                        tz=ctx.timezone,
                    )
                else:
                    interval_minutes = current_every
                    time_local = str(schedule.get("time_local") or now.astimezone(ctx.timezone).strftime("%H:%M"))
                    next_run = calculate_initial_next_run(now, time_local, int(interval_minutes or 0), ctx.timezone) if int(interval_minutes or 0) > 0 else now
            except ValueError as exc:
                await _send(interaction, subcommand_path=subcommand_path, lines=[("error", str(exc))], kind="error")
                return
            next_run_at = next_run.isoformat()

        updated = await ctx.database.update_campaign_content_config(
            guild_id,
            schedule_id,
            time_local=time_local,
            interval_minutes=interval_minutes,
            embed_title=embed_title,
            embed_color=embed_color,
            sources_json=json.dumps(_normalize_csv_values(sources), ensure_ascii=False) if sources is not None else None,
            categories_json=",".join(_normalize_csv_values(categories)) if categories is not None else None,
            extras_json=json.dumps(_normalize_csv_values(extras), ensure_ascii=False) if extras is not None else None,
            next_run_at=next_run_at,
            set_time_local=time_local is not None,
            set_interval_minutes=interval_minutes is not None,
            set_embed_title=embed_title is not None,
            set_embed_color=embed_color is not None,
            set_sources_json=sources is not None,
            set_categories_json=categories is not None,
            set_extras_json=extras is not None,
            set_next_run_at=next_run_at is not None,
        )
        if enabled is not None:
            await ctx.database.set_campaign_content_enabled(guild_id, schedule_id, enabled)
        if not updated and enabled is None:
            await _send(interaction, subcommand_path=subcommand_path, lines=[("warning", "No changes requested.")], kind="warning")
            return
        refreshed = await _get_service_schedule(guild_id, service_type, schedule_id)
        await _send(interaction, subcommand_path=subcommand_path, subtitle_args=[schedule_id], lines=[("schedule_id", schedule_id), ("result", "updated")], sections=[CommandEmbedSection(title="Schedule", lines=[_format_service_config_row(refreshed or schedule)])], kind="success")

    @campaigns_group.command(name="on", description="Enable campaigns in the current channel")
    async def messaggi_on(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campaigns.on", "campagne.on"):
            return
        scope = await _require_guild_channel(interaction, subcommand_path="campaigns on")
        if scope is None:
            return
        guild_id, channel_id = scope
        await ctx.database.set_message_channel_enabled(guild_id, channel_id, True)
        await _send(interaction, subcommand_path="campaigns on", lines=[("channel", f"<#{channel_id}>"), ("result", "enabled")], kind="success")

    @campaigns_group.command(name="off", description="Disable campaigns in the current channel")
    async def messaggi_off(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campaigns.off", "campagne.off"):
            return
        scope = await _require_guild_channel(interaction, subcommand_path="campaigns off")
        if scope is None:
            return
        guild_id, channel_id = scope
        await ctx.database.set_message_channel_enabled(guild_id, channel_id, False)
        await _send(interaction, subcommand_path="campaigns off", lines=[("channel", f"<#{channel_id}>"), ("result", "disabled")], kind="success")

    @campaigns_group.command(name="status", description="Show campaign status for the current channel")
    async def messaggi_status(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campaigns.status", "campagne.status"):
            return
        scope = await _require_guild_channel(interaction, subcommand_path="campaigns status")
        if scope is None:
            return
        guild_id, channel_id = scope
        enabled = await ctx.database.get_message_channel_status(guild_id, channel_id)
        active_campaigns = await ctx.database.list_message_campaigns(guild_id, include_disabled=False)
        active_for_channel = [row for row in active_campaigns if str(row["channel_id"]) == channel_id]
        await _send(interaction, subcommand_path="campaigns status", lines=[("channel", f"<#{channel_id}>"), ("campaigns", "enabled" if enabled else "disabled"), ("active_entries", len(active_for_channel))])

    @quiet_group.command(name="on", description="Enable quiet hours")
    async def quiet_on(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campaigns.quiet.on", "campaigns.quiet_on", "campagne.quiet.on", "campagne.quiet_on"):
            return
        await ctx.database.set_setting("messages_quiet_enabled", "1")
        await _send(interaction, subcommand_path="campaigns quiet on", lines=[("quiet_hours", "enabled")], kind="success")

    @quiet_group.command(name="off", description="Disable quiet hours")
    async def quiet_off(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campaigns.quiet.off", "campaigns.quiet_off", "campagne.quiet.off", "campagne.quiet_off"):
            return
        await ctx.database.set_setting("messages_quiet_enabled", "0")
        await _send(interaction, subcommand_path="campaigns quiet off", lines=[("quiet_hours", "disabled")], kind="success")

    @quiet_group.command(name="status", description="Show quiet hours status")
    async def quiet_status(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campaigns.quiet.status", "campaigns.quiet_status", "campagne.quiet.status", "campagne.quiet_status"):
            return
        enabled = await _ensure_setting(ctx, "messages_quiet_enabled", "1")
        start = await _ensure_setting(ctx, "messages_quiet_start", QUIET_DEFAULT_START)
        end = await _ensure_setting(ctx, "messages_quiet_end", QUIET_DEFAULT_END)
        await _send(interaction, subcommand_path="campaigns quiet status", lines=[("quiet_hours", "enabled" if enabled == "1" else "disabled"), ("start", start), ("end", end)])

    @quiet_group.command(name="range_set", description="Set the quiet-hours start/end range")
    @app_commands.describe(start="Quiet hours start time (HH:MM)", end="Quiet hours end time (HH:MM)")
    async def quiet_range_set(interaction: discord.Interaction, start: str, end: str) -> None:
        if not await _check(interaction, "campaigns.quiet.range_set", "campaigns.quiet.config_set", "campaigns.quiet.set", "campaigns.quiet_set", "campagne.quiet.config_set", "campagne.quiet.set", "campagne.quiet_set"):
            return
        await ctx.database.set_setting("messages_quiet_start", start)
        await ctx.database.set_setting("messages_quiet_end", end)
        await _send(interaction, subcommand_path="campaigns quiet range_set", lines=[("start", start), ("end", end), ("result", "updated")], kind="success")

    @quiet_group.command(name="range_show", description="Show the quiet-hours start/end range")
    async def quiet_range_show(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campaigns.quiet.range_show", "campaigns.quiet.config_show", "campaigns.quiet_status", "campagne.quiet.config_show", "campagne.quiet_status"):
            return
        start = await _ensure_setting(ctx, "messages_quiet_start", QUIET_DEFAULT_START)
        end = await _ensure_setting(ctx, "messages_quiet_end", QUIET_DEFAULT_END)
        await _send(interaction, subcommand_path="campaigns quiet range_show", lines=[("start", start), ("end", end)])

    @quiet_group.command(name="range_reset", description="Reset the quiet-hours start/end range")
    async def quiet_range_reset(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campaigns.quiet.range_reset", "campaigns.quiet.config_reset", "campaigns.quiet.set", "campaigns.quiet_set", "campagne.quiet.config_reset", "campagne.quiet.set", "campagne.quiet_set"):
            return
        await ctx.database.set_setting("messages_quiet_start", QUIET_DEFAULT_START)
        await ctx.database.set_setting("messages_quiet_end", QUIET_DEFAULT_END)
        await _send(interaction, subcommand_path="campaigns quiet range_reset", lines=[("start", QUIET_DEFAULT_START), ("end", QUIET_DEFAULT_END), ("result", "reset")], kind="success")

    @cap_group.command(name="on", description="Enable the daily cap")
    async def cap_on(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campaigns.cap.on", "campaigns.cap_on", "campagne.cap.on", "campagne.cap_on"):
            return
        await ctx.database.set_setting("messages_daily_cap_enabled", "1")
        await _send(interaction, subcommand_path="campaigns cap on", lines=[("daily_cap", "enabled")], kind="success")

    @cap_group.command(name="off", description="Disable the daily cap")
    async def cap_off(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campaigns.cap.off", "campaigns.cap_off", "campagne.cap.off", "campagne.cap_off"):
            return
        await ctx.database.set_setting("messages_daily_cap_enabled", "0")
        await _send(interaction, subcommand_path="campaigns cap off", lines=[("daily_cap", "disabled")], kind="success")

    @cap_group.command(name="status", description="Show the daily cap status")
    async def cap_status(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campaigns.cap.status", "campaigns.cap_status", "campagne.cap.status", "campagne.cap_status"):
            return
        enabled = await _ensure_setting(ctx, "messages_daily_cap_enabled", "1")
        cap = await _ensure_setting(ctx, "messages_daily_cap", str(CAP_DEFAULT))
        await _send(interaction, subcommand_path="campaigns cap status", lines=[("daily_cap", "enabled" if enabled == "1" else "disabled"), ("daily_limit", cap)])

    @cap_group.command(name="limits_set", description="Set the daily cap limit")
    @app_commands.describe(daily_limit="Maximum messages per day")
    async def cap_limits_set(interaction: discord.Interaction, daily_limit: int) -> None:
        if not await _check(interaction, "campaigns.cap.limits_set", "campaigns.cap.config_set", "campaigns.cap.set", "campaigns.cap_set", "campagne.cap.config_set", "campagne.cap.set", "campagne.cap_set"):
            return
        if daily_limit <= 0:
            await _send(interaction, subcommand_path="campaigns cap limits_set", lines=[("error", "daily_limit must be greater than 0.")], kind="error")
            return
        await ctx.database.set_setting("messages_daily_cap", str(daily_limit))
        await _send(interaction, subcommand_path="campaigns cap limits_set", lines=[("daily_limit", daily_limit), ("result", "updated")], kind="success")

    @cap_group.command(name="limits_show", description="Show the daily cap limit")
    async def cap_limits_show(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campaigns.cap.limits_show", "campaigns.cap.config_show", "campaigns.cap_status", "campagne.cap.config_show", "campagne.cap_status"):
            return
        cap = await _ensure_setting(ctx, "messages_daily_cap", str(CAP_DEFAULT))
        await _send(interaction, subcommand_path="campaigns cap limits_show", lines=[("daily_limit", cap)])

    @cap_group.command(name="limits_reset", description="Reset the daily cap limit")
    async def cap_limits_reset(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campaigns.cap.limits_reset", "campaigns.cap.config_reset", "campaigns.cap.set", "campaigns.cap_set", "campagne.cap.config_reset", "campagne.cap.set", "campagne.cap_set"):
            return
        await ctx.database.set_setting("messages_daily_cap", str(CAP_DEFAULT))
        await _send(interaction, subcommand_path="campaigns cap limits_reset", lines=[("daily_limit", CAP_DEFAULT), ("result", "reset")], kind="success")

    @custom_group.command(name="on", description="Enable custom campaigns in the current channel")
    async def custom_on(interaction: discord.Interaction) -> None:
        await _custom_toggle(interaction, "on")

    @custom_group.command(name="off", description="Disable custom campaigns in the current channel")
    async def custom_off(interaction: discord.Interaction) -> None:
        await _custom_toggle(interaction, "off")

    @custom_group.command(name="status", description="Show custom campaign status for the current channel")
    async def custom_status(interaction: discord.Interaction) -> None:
        await _custom_toggle(interaction, "status")

    @custom_group.command(name="schedule_add", description="Add a custom campaign schedule")
    @app_commands.describe(
        text="Fallback text",
        text_green="Text for green mood",
        text_yellow="Text for yellow mood",
        text_red="Text for red mood",
        text_black="Text for black mood",
        mood_mode="Mood selection mode",
        publish_at="First publication time (DD/MM/YYYY HH:MM)",
        every="Repeat interval in minutes",
        jitter_seconds="Optional jitter in seconds",
        only_if_idle_minutes="Only send if the channel has been idle for X minutes",
        embed_title="Optional embed title",
        embed_color="Optional embed color",
    )
    @app_commands.choices(mood_mode=MOOD_CHOICES)
    async def custom_schedule_add(
        interaction: discord.Interaction,
        text: Optional[str] = None,
        text_green: Optional[str] = None,
        text_yellow: Optional[str] = None,
        text_red: Optional[str] = None,
        text_black: Optional[str] = None,
        mood_mode: Optional[app_commands.Choice[str]] = None,
        publish_at: Optional[str] = None,
        every: Optional[int] = None,
        jitter_seconds: Optional[int] = 0,
        only_if_idle_minutes: Optional[int] = 0,
        embed_title: Optional[str] = None,
        embed_color: Optional[str] = None,
    ) -> None:
        if not await _check(interaction, "campaigns.custom.schedule_add", "campaigns.custom.entry_add", "campagne.custom.schedule_add", "campagne.custom.entry_add", "campagne.aggiungi"):
            return
        scope = await _require_guild_channel(interaction, subcommand_path="campaigns custom schedule_add")
        if scope is None:
            return
        if not await _validate_embed_color(interaction, embed_color, subcommand_path="campaigns custom schedule_add"):
            return
        guild_id, channel_id = scope
        now = datetime.now(timezone.utc)
        try:
            next_run, start_time_local, resolved_every = _resolve_schedule(
                publish_at=publish_at,
                every=every,
                now_utc=now,
                tz=ctx.timezone,
            )
        except ValueError as exc:
            await _send(interaction, subcommand_path="campaigns custom schedule_add", lines=[("error", str(exc))], kind="error")
            return
        resolved_mood_mode = mood_mode.value if mood_mode else "AUTO"
        validation_error = validate_campaign_texts(
            text=text,
            text_green=text_green,
            text_yellow=text_yellow,
            text_red=text_red,
            text_black=text_black,
            mood_mode=resolved_mood_mode,
        )
        if validation_error:
            await _send(interaction, subcommand_path="campaigns custom schedule_add", lines=[("error", validation_error)], kind="error")
            return
        campaign_id = await ctx.database.create_message_campaign(
            guild_id=guild_id,
            channel_id=channel_id,
            campaign_type="CUSTOM",
            name=None,
            text=text,
            text_green=text_green,
            text_yellow=text_yellow,
            text_red=text_red,
            text_black=text_black,
            enabled=True,
            start_time_local=start_time_local,
            interval_minutes=resolved_every,
            jitter_seconds=int(jitter_seconds or 0),
            only_if_idle_minutes=int(only_if_idle_minutes or 0),
            mood_mode=resolved_mood_mode,
            next_run_at=next_run.isoformat(),
            created_by=str(interaction.user.id),
            embed_title=embed_title,
            embed_color=embed_color,
        )
        await _send(interaction, subcommand_path="campaigns custom schedule_add", subtitle_args=[campaign_id], lines=[("schedule_id", campaign_id), ("next_run", next_run.isoformat()), ("result", "created")], kind="success")

    @custom_group.command(name="schedule_list", description="List custom campaign schedules")
    async def custom_schedule_list(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campaigns.custom.schedule_list", "campaigns.custom.entry_list", "campagne.custom.schedule_list", "campagne.custom.entry_list", "campagne.lista"):
            return
        guild_id = await _require_guild(interaction, subcommand_path="campaigns custom schedule_list")
        if guild_id is None:
            return
        campaigns = await _list_custom_campaigns(guild_id)
        if not campaigns:
            await _send(interaction, subcommand_path="campaigns custom schedule_list", lines=[("warning", "No custom schedules configured.")], kind="warning")
            return
        await _send(interaction, subcommand_path="campaigns custom schedule_list", lines=[("schedules", len(campaigns))], sections=[CommandEmbedSection(title="Schedules", lines=[_format_message_campaign_row(row) for row in campaigns])])

    @custom_group.command(name="schedule_show", description="Show a custom campaign schedule")
    @app_commands.describe(id="Campaign schedule ID")
    async def custom_schedule_show(interaction: discord.Interaction, id: int) -> None:
        if not await _check(interaction, "campaigns.custom.schedule_show", "campaigns.custom.entry_show", "campagne.custom.schedule_show", "campagne.custom.entry_show"):
            return
        guild_id = await _require_guild(interaction, subcommand_path="campaigns custom schedule_show")
        if guild_id is None:
            return
        campaign = await _get_custom_campaign(guild_id, id)
        if campaign is None:
            await _send(interaction, subcommand_path="campaigns custom schedule_show", subtitle_args=[id], lines=[("warning", "Custom schedule not found.")], kind="warning")
            return
        await _send(interaction, subcommand_path="campaigns custom schedule_show", subtitle_args=[id], lines=[("schedule_id", id)], sections=[CommandEmbedSection(title="Schedule", lines=[_format_message_campaign_row(campaign)])])

    @custom_group.command(name="schedule_remove", description="Remove a custom campaign schedule")
    @app_commands.describe(id="Campaign schedule ID")
    async def custom_schedule_remove(interaction: discord.Interaction, id: int) -> None:
        if not await _check(interaction, "campaigns.custom.schedule_remove", "campaigns.custom.entry_remove", "campagne.custom.schedule_remove", "campagne.custom.entry_remove", "campagne.cancella"):
            return
        guild_id = await _require_guild(interaction, subcommand_path="campaigns custom schedule_remove")
        if guild_id is None:
            return
        campaign = await _get_custom_campaign(guild_id, id)
        if campaign is None:
            await _send(interaction, subcommand_path="campaigns custom schedule_remove", subtitle_args=[id], lines=[("warning", "Custom schedule not found.")], kind="warning")
            return
        await ctx.database.soft_delete_message_campaign(guild_id, id)
        await _send(interaction, subcommand_path="campaigns custom schedule_remove", subtitle_args=[id], lines=[("schedule_id", id), ("result", "removed")], kind="success")

    @custom_group.command(name="run", description="Run a custom campaign schedule now")
    @app_commands.describe(id="Campaign schedule ID")
    async def custom_run(interaction: discord.Interaction, id: int) -> None:
        if not await _check(interaction, "campaigns.custom.run", "campaigns.custom.entry_run", "campagne.custom.run", "campagne.custom.entry_run", "campagne.test"):
            return
        guild_id = await _require_guild(interaction, subcommand_path="campaigns custom run")
        if guild_id is None or interaction.channel is None or interaction.channel_id is None:
            if not interaction.response.is_done():
                await _send(interaction, subcommand_path="campaigns custom run", subtitle_args=[id], lines=[("error", "Use this command in a guild channel.")], kind="error")
            return
        campaign = await _get_custom_campaign(guild_id, id)
        if campaign is None:
            await _send(interaction, subcommand_path="campaigns custom run", subtitle_args=[id], lines=[("warning", "Custom schedule not found.")], kind="warning")
            return
        if ctx.message_scheduler is None:
            await _send(interaction, subcommand_path="campaigns custom run", subtitle_args=[id], lines=[("error", "Scheduler service unavailable.")], kind="error")
            return
        await _send(interaction, subcommand_path="campaigns custom run", subtitle_args=[id], lines=[("schedule_id", id), ("result", "running")], kind="success")
        if isinstance(interaction.channel, discord.abc.Messageable):
            rendered_text, _, _ = await ctx.message_scheduler.preview_campaign_text(
                campaign,
                channel_id_override=str(interaction.channel_id),
            )
            await ctx.message_scheduler.send_campaign_embed(interaction.channel, campaign, rendered_text)

    @custom_group.command(name="schedule_edit", description="Edit a custom campaign schedule")
    @app_commands.describe(
        id="Campaign entry ID",
        text="Fallback text",
        text_green="Text for green mood",
        text_yellow="Text for yellow mood",
        text_red="Text for red mood",
        text_black="Text for black mood",
        mood_mode="Mood selection mode",
        publish_at="First publication time (DD/MM/YYYY HH:MM)",
        every="Repeat interval in minutes",
        jitter_seconds="Optional jitter in seconds",
        only_if_idle_minutes="Only send if the channel has been idle for X minutes",
        embed_title="Optional embed title",
        embed_color="Optional embed color",
        enabled="Enable or disable this schedule",
    )
    @app_commands.choices(mood_mode=MOOD_CHOICES)
    async def custom_schedule_edit(
        interaction: discord.Interaction,
        id: int,
        text: str | None = None,
        text_green: str | None = None,
        text_yellow: str | None = None,
        text_red: str | None = None,
        text_black: str | None = None,
        mood_mode: app_commands.Choice[str] | None = None,
        publish_at: str | None = None,
        every: int | None = None,
        jitter_seconds: int | None = None,
        only_if_idle_minutes: int | None = None,
        embed_title: str | None = None,
        embed_color: str | None = None,
        enabled: bool | None = None,
    ) -> None:
        if not await _check(interaction, "campaigns.custom.schedule_edit", "campaigns.custom.entry_edit", "campagne.custom.schedule_edit", "campagne.custom.entry_edit", "campagne.pausa", "campagne.riprendi"):
            return
        guild_id = await _require_guild(interaction, subcommand_path="campaigns custom schedule_edit")
        if guild_id is None:
            return
        campaign = await _get_custom_campaign(guild_id, id)
        if campaign is None:
            await _send(interaction, subcommand_path="campaigns custom schedule_edit", subtitle_args=[id], lines=[("warning", "Custom schedule not found.")], kind="warning")
            return
        if embed_color is not None and not await _validate_embed_color(interaction, embed_color, subcommand_path="campaigns custom schedule_edit"):
            return

        candidate_text = text if text is not None else campaign.get("text")
        candidate_green = text_green if text_green is not None else campaign.get("text_green")
        candidate_yellow = text_yellow if text_yellow is not None else campaign.get("text_yellow")
        candidate_red = text_red if text_red is not None else campaign.get("text_red")
        candidate_black = text_black if text_black is not None else campaign.get("text_black")
        resolved_mood_mode = mood_mode.value if mood_mode is not None else str(campaign.get("mood_mode") or "AUTO")
        validation_error = validate_campaign_texts(
            text=str(candidate_text) if candidate_text is not None else None,
            text_green=str(candidate_green) if candidate_green is not None else None,
            text_yellow=str(candidate_yellow) if candidate_yellow is not None else None,
            text_red=str(candidate_red) if candidate_red is not None else None,
            text_black=str(candidate_black) if candidate_black is not None else None,
            mood_mode=resolved_mood_mode,
        )
        if validation_error:
            await _send(interaction, subcommand_path="campaigns custom schedule_edit", subtitle_args=[id], lines=[("error", validation_error)], kind="error")
            return

        next_run_at: str | None = None
        start_time_local: str | None = None
        interval_minutes: int | None = None
        if publish_at is not None or every is not None:
            now = datetime.now(timezone.utc)
            interval_minutes = every if every is not None else int(campaign.get("interval_minutes") or 0)
            if publish_at is not None:
                try:
                    next_run, start_time_local, interval_minutes = _resolve_schedule(
                        publish_at=publish_at,
                        every=interval_minutes,
                        now_utc=now,
                        tz=ctx.timezone,
                    )
                except ValueError as exc:
                    await _send(interaction, subcommand_path="campaigns custom schedule_edit", subtitle_args=[id], lines=[("error", str(exc))], kind="error")
                    return
            else:
                start_time_local = str(campaign.get("start_time_local") or now.astimezone(ctx.timezone).strftime("%H:%M"))
                next_run = calculate_initial_next_run(now, start_time_local, int(interval_minutes or 0), ctx.timezone) if int(interval_minutes or 0) > 0 else now
            next_run_at = next_run.isoformat()

        updated = await ctx.database.update_message_campaign(
            guild_id,
            id,
            text=text,
            text_green=text_green,
            text_yellow=text_yellow,
            text_red=text_red,
            text_black=text_black,
            mood_mode=resolved_mood_mode,
            start_time_local=start_time_local,
            interval_minutes=interval_minutes,
            jitter_seconds=jitter_seconds,
            only_if_idle_minutes=only_if_idle_minutes,
            next_run_at=next_run_at,
            embed_title=embed_title,
            embed_color=embed_color,
            set_text=text is not None,
            set_text_green=text_green is not None,
            set_text_yellow=text_yellow is not None,
            set_text_red=text_red is not None,
            set_text_black=text_black is not None,
            set_mood_mode=mood_mode is not None,
            set_start_time_local=start_time_local is not None,
            set_interval_minutes=interval_minutes is not None,
            set_jitter_seconds=jitter_seconds is not None,
            set_only_if_idle_minutes=only_if_idle_minutes is not None,
            set_next_run_at=next_run_at is not None,
            set_embed_title=embed_title is not None,
            set_embed_color=embed_color is not None,
        )
        if enabled is not None:
            await ctx.database.set_message_campaign_enabled(guild_id, id, enabled)
        if not updated and enabled is None:
            await _send(interaction, subcommand_path="campaigns custom schedule_edit", subtitle_args=[id], lines=[("warning", "No changes requested.")], kind="warning")
            return
        refreshed = await _get_custom_campaign(guild_id, id)
        await _send(interaction, subcommand_path="campaigns custom schedule_edit", subtitle_args=[id], lines=[("schedule_id", id), ("result", "updated")], sections=[CommandEmbedSection(title="Schedule", lines=[_format_message_campaign_row(refreshed or campaign)])], kind="success")

    @news_group.command(name="on", description="Enable news campaigns in the current channel")
    async def news_on(interaction: discord.Interaction) -> None:
        await _set_service_enabled(interaction, service_type="NEWS", action="on")

    @news_group.command(name="off", description="Disable news campaigns in the current channel")
    async def news_off(interaction: discord.Interaction) -> None:
        await _set_service_enabled(interaction, service_type="NEWS", action="off")

    @news_group.command(name="status", description="Show news campaign status for the current channel")
    async def news_status(interaction: discord.Interaction) -> None:
        await _set_service_enabled(interaction, service_type="NEWS", action="status")

    @news_group.command(name="schedule_add", description="Add a news campaign schedule")
    @app_commands.describe(
        publish_at="First publication time (DD/MM/YYYY HH:MM)",
        every="Repeat interval in minutes",
        embed_title="Optional embed title",
        embed_color="Optional embed color",
        sources="Guided multi-value sources (comma-separated)",
        categories="Guided multi-value categories (comma-separated)",
        extras="Guided multi-value extras (comma-separated)",
    )
    @app_commands.autocomplete(sources=_news_sources_autocomplete, categories=_news_categories_autocomplete, extras=_news_extras_autocomplete)
    async def news_schedule_add(
        interaction: discord.Interaction,
        publish_at: str | None = None,
        every: int | None = None,
        embed_title: str | None = None,
        embed_color: str | None = None,
        sources: str | None = None,
        categories: str | None = None,
        extras: str | None = None,
    ) -> None:
        normalized_sources, invalid_sources = _parse_guided_csv_values(
            sources,
            allowed=NEWS_SOURCE_CHOICES,
            aliases=NEWS_SOURCE_ALIASES,
        )
        if invalid_sources:
            await _send(
                interaction,
                subcommand_path="campaigns news schedule_add",
                lines=[("error", f"Unsupported sources: {', '.join(invalid_sources)}.")],
                kind="error",
            )
            return
        normalized_categories, invalid_categories = _parse_guided_csv_values(
            categories,
            allowed=NEWS_CATEGORY_CHOICES,
            aliases=NEWS_CATEGORY_ALIASES,
            normalizer=_fold_token,
        )
        if invalid_categories:
            await _send(
                interaction,
                subcommand_path="campaigns news schedule_add",
                lines=[("error", f"Unsupported categories: {', '.join(invalid_categories)}.")],
                kind="error",
            )
            return
        normalized_extras, invalid_extras = _parse_guided_csv_values(
            extras,
            allowed=NEWS_EXTRA_CHOICES,
        )
        if invalid_extras:
            await _send(
                interaction,
                subcommand_path="campaigns news schedule_add",
                lines=[("error", f"Unsupported extras: {', '.join(invalid_extras)}.")],
                kind="error",
            )
            return
        await _service_schedule_add(
            interaction,
            service_type="NEWS",
            publish_at=publish_at,
            every=every,
            embed_title=embed_title,
            embed_color=embed_color,
            sources=",".join(normalized_sources) if sources is not None else None,
            categories=",".join(normalized_categories) if categories is not None else None,
            extras=",".join(normalized_extras) if extras is not None else None,
        )

    @news_group.command(name="schedule_edit", description="Edit a news campaign schedule")
    @app_commands.describe(
        id="News schedule ID",
        publish_at="First publication time (DD/MM/YYYY HH:MM)",
        every="Repeat interval in minutes",
        embed_title="Optional embed title",
        embed_color="Optional embed color",
        enabled="Enable or disable this schedule",
        sources="Guided multi-value sources (comma-separated)",
        categories="Guided multi-value categories (comma-separated)",
        extras="Guided multi-value extras (comma-separated)",
    )
    @app_commands.autocomplete(sources=_news_sources_autocomplete, categories=_news_categories_autocomplete, extras=_news_extras_autocomplete)
    async def news_schedule_edit(
        interaction: discord.Interaction,
        id: int,
        publish_at: str | None = None,
        every: int | None = None,
        embed_title: str | None = None,
        embed_color: str | None = None,
        enabled: bool | None = None,
        sources: str | None = None,
        categories: str | None = None,
        extras: str | None = None,
    ) -> None:
        normalized_sources, invalid_sources = _parse_guided_csv_values(
            sources,
            allowed=NEWS_SOURCE_CHOICES,
            aliases=NEWS_SOURCE_ALIASES,
        )
        if invalid_sources:
            await _send(
                interaction,
                subcommand_path="campaigns news schedule_edit",
                lines=[("error", f"Unsupported sources: {', '.join(invalid_sources)}.")],
                kind="error",
            )
            return
        normalized_categories, invalid_categories = _parse_guided_csv_values(
            categories,
            allowed=NEWS_CATEGORY_CHOICES,
            aliases=NEWS_CATEGORY_ALIASES,
            normalizer=_fold_token,
        )
        if invalid_categories:
            await _send(
                interaction,
                subcommand_path="campaigns news schedule_edit",
                lines=[("error", f"Unsupported categories: {', '.join(invalid_categories)}.")],
                kind="error",
            )
            return
        normalized_extras, invalid_extras = _parse_guided_csv_values(extras, allowed=NEWS_EXTRA_CHOICES)
        if invalid_extras:
            await _send(
                interaction,
                subcommand_path="campaigns news schedule_edit",
                lines=[("error", f"Unsupported extras: {', '.join(invalid_extras)}.")],
                kind="error",
            )
            return
        await _service_schedule_edit(
            interaction,
            service_type="NEWS",
            schedule_id=id,
            publish_at=publish_at,
            every=every,
            embed_title=embed_title,
            embed_color=embed_color,
            enabled=enabled,
            sources=",".join(normalized_sources) if sources is not None else None,
            categories=",".join(normalized_categories) if categories is not None else None,
            extras=",".join(normalized_extras) if extras is not None else None,
        )

    @news_group.command(name="schedule_show", description="Show a news campaign schedule")
    @app_commands.describe(id="News schedule ID")
    async def news_schedule_show(interaction: discord.Interaction, id: int) -> None:
        await _service_schedule_show(interaction, service_type="NEWS", schedule_id=id)

    @news_group.command(name="schedule_remove", description="Remove a news campaign schedule")
    @app_commands.describe(id="News schedule ID")
    async def news_schedule_remove(interaction: discord.Interaction, id: int) -> None:
        await _service_schedule_remove(interaction, service_type="NEWS", schedule_id=id)

    @news_group.command(name="schedule_list", description="List news campaign schedules")
    async def news_schedule_list(interaction: discord.Interaction) -> None:
        await _service_schedule_list(interaction, service_type="NEWS")

    @news_group.command(name="run", description="Run the news campaign immediately")
    @app_commands.describe(id="News schedule ID (recommended when multiple schedules exist)")
    async def news_run(interaction: discord.Interaction, id: int | None = None) -> None:
        await _service_run(interaction, service_type="NEWS", schedule_id=id)

    @weather_group.command(name="on", description="Enable weather campaigns in the current channel")
    async def weather_on(interaction: discord.Interaction) -> None:
        await _set_service_enabled(interaction, service_type="WEATHER", action="on")

    @weather_group.command(name="off", description="Disable weather campaigns in the current channel")
    async def weather_off(interaction: discord.Interaction) -> None:
        await _set_service_enabled(interaction, service_type="WEATHER", action="off")

    @weather_group.command(name="status", description="Show weather campaign status for the current channel")
    async def weather_status(interaction: discord.Interaction) -> None:
        await _set_service_enabled(interaction, service_type="WEATHER", action="status")

    @weather_group.command(name="schedule_add", description="Add a weather campaign schedule")
    @app_commands.describe(
        publish_at="First publication time (DD/MM/YYYY HH:MM)",
        every="Repeat interval in minutes",
        embed_title="Optional embed title",
        embed_color="Optional embed color",
        sources="Comma-separated provider list",
    )
    async def weather_schedule_add(
        interaction: discord.Interaction,
        publish_at: str | None = None,
        every: int | None = None,
        embed_title: str | None = None,
        embed_color: str | None = None,
        sources: str | None = None,
    ) -> None:
        await _service_schedule_add(
            interaction,
            service_type="WEATHER",
            publish_at=publish_at,
            every=every,
            embed_title=embed_title,
            embed_color=embed_color,
            sources=sources,
            categories=None,
        )

    @weather_group.command(name="schedule_edit", description="Edit a weather campaign schedule")
    @app_commands.describe(
        id="Weather schedule ID",
        publish_at="First publication time (DD/MM/YYYY HH:MM)",
        every="Repeat interval in minutes",
        embed_title="Optional embed title",
        embed_color="Optional embed color",
        sources="Comma-separated provider list",
        enabled="Enable or disable this schedule",
    )
    async def weather_schedule_edit(
        interaction: discord.Interaction,
        id: int,
        publish_at: str | None = None,
        every: int | None = None,
        embed_title: str | None = None,
        embed_color: str | None = None,
        sources: str | None = None,
        enabled: bool | None = None,
    ) -> None:
        await _service_schedule_edit(
            interaction,
            service_type="WEATHER",
            schedule_id=id,
            publish_at=publish_at,
            every=every,
            embed_title=embed_title,
            embed_color=embed_color,
            sources=sources,
            enabled=enabled,
        )

    @weather_group.command(name="schedule_show", description="Show a weather campaign schedule")
    @app_commands.describe(id="Weather schedule ID")
    async def weather_schedule_show(interaction: discord.Interaction, id: int) -> None:
        await _service_schedule_show(interaction, service_type="WEATHER", schedule_id=id)

    @weather_group.command(name="schedule_remove", description="Remove a weather campaign schedule")
    @app_commands.describe(id="Weather schedule ID")
    async def weather_schedule_remove(interaction: discord.Interaction, id: int) -> None:
        await _service_schedule_remove(interaction, service_type="WEATHER", schedule_id=id)

    @weather_group.command(name="schedule_list", description="List weather campaign schedules")
    async def weather_schedule_list(interaction: discord.Interaction) -> None:
        await _service_schedule_list(interaction, service_type="WEATHER")

    @weather_group.command(name="run", description="Run the weather campaign immediately")
    @app_commands.describe(id="Weather schedule ID (recommended when multiple schedules exist)")
    async def weather_run(interaction: discord.Interaction, id: int | None = None) -> None:
        await _service_run(interaction, service_type="WEATHER", schedule_id=id)

    @horoscope_group.command(name="on", description="Enable horoscope campaigns in the current channel")
    async def horoscope_on(interaction: discord.Interaction) -> None:
        await _set_service_enabled(interaction, service_type="HOROSCOPE", action="on")

    @horoscope_group.command(name="off", description="Disable horoscope campaigns in the current channel")
    async def horoscope_off(interaction: discord.Interaction) -> None:
        await _set_service_enabled(interaction, service_type="HOROSCOPE", action="off")

    @horoscope_group.command(name="status", description="Show horoscope campaign status for the current channel")
    async def horoscope_status(interaction: discord.Interaction) -> None:
        await _set_service_enabled(interaction, service_type="HOROSCOPE", action="status")

    @horoscope_group.command(name="schedule_add", description="Add a horoscope campaign schedule")
    @app_commands.describe(
        publish_at="First publication time (DD/MM/YYYY HH:MM)",
        every="Repeat interval in minutes",
        embed_title="Optional embed title",
        embed_color="Optional embed color",
        sources="Comma-separated provider list",
    )
    async def horoscope_schedule_add(
        interaction: discord.Interaction,
        publish_at: str | None = None,
        every: int | None = None,
        embed_title: str | None = None,
        embed_color: str | None = None,
        sources: str | None = None,
    ) -> None:
        await _service_schedule_add(
            interaction,
            service_type="HOROSCOPE",
            publish_at=publish_at,
            every=every,
            embed_title=embed_title,
            embed_color=embed_color,
            sources=sources,
            categories=None,
        )

    @horoscope_group.command(name="schedule_edit", description="Edit a horoscope campaign schedule")
    @app_commands.describe(
        id="Horoscope schedule ID",
        publish_at="First publication time (DD/MM/YYYY HH:MM)",
        every="Repeat interval in minutes",
        embed_title="Optional embed title",
        embed_color="Optional embed color",
        sources="Comma-separated provider list",
        enabled="Enable or disable this schedule",
    )
    async def horoscope_schedule_edit(
        interaction: discord.Interaction,
        id: int,
        publish_at: str | None = None,
        every: int | None = None,
        embed_title: str | None = None,
        embed_color: str | None = None,
        sources: str | None = None,
        enabled: bool | None = None,
    ) -> None:
        await _service_schedule_edit(
            interaction,
            service_type="HOROSCOPE",
            schedule_id=id,
            publish_at=publish_at,
            every=every,
            embed_title=embed_title,
            embed_color=embed_color,
            sources=sources,
            enabled=enabled,
        )

    @horoscope_group.command(name="schedule_show", description="Show a horoscope campaign schedule")
    @app_commands.describe(id="Horoscope schedule ID")
    async def horoscope_schedule_show(interaction: discord.Interaction, id: int) -> None:
        await _service_schedule_show(interaction, service_type="HOROSCOPE", schedule_id=id)

    @horoscope_group.command(name="schedule_remove", description="Remove a horoscope campaign schedule")
    @app_commands.describe(id="Horoscope schedule ID")
    async def horoscope_schedule_remove(interaction: discord.Interaction, id: int) -> None:
        await _service_schedule_remove(interaction, service_type="HOROSCOPE", schedule_id=id)

    @horoscope_group.command(name="schedule_list", description="List horoscope campaign schedules")
    async def horoscope_schedule_list(interaction: discord.Interaction) -> None:
        await _service_schedule_list(interaction, service_type="HOROSCOPE")

    @horoscope_group.command(name="run", description="Run the horoscope campaign immediately")
    @app_commands.describe(id="Horoscope schedule ID (recommended when multiple schedules exist)")
    async def horoscope_run(interaction: discord.Interaction, id: int | None = None) -> None:
        await _service_run(interaction, service_type="HOROSCOPE", schedule_id=id)
