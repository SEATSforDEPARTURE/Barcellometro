from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Optional

import discord
from discord import app_commands

from app.plugins.commands_modular.command_helpers import add_group_once, count_child_commands
from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.time_windows import parse_italian_datetime
from app.services.scheduler_utils import calculate_initial_next_run

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
        ]
    )


def register_messaggi(campagne_group: app_commands.Group, ctx: CommandContext) -> None:
    quiet_group = app_commands.Group(name="quiet", description="Quiet hours controls")
    cap_group = app_commands.Group(name="cap", description="Daily cap controls")
    custom_group = app_commands.Group(name="custom", description="Custom campaign entries")
    news_group = app_commands.Group(name="news", description="News campaign controls")
    weather_group = app_commands.Group(name="weather", description="Weather campaign controls")
    horoscope_group = app_commands.Group(name="horoscope", description="Horoscope campaign controls")

    for group in (quiet_group, cap_group, custom_group, news_group, weather_group, horoscope_group):
        add_group_once(campagne_group, group, logger)

    logger.debug(
        "Registered /%s with children=%d",
        campagne_group.qualified_name or campagne_group.name,
        count_child_commands(campagne_group),
    )

    async def _check(interaction: discord.Interaction, command_name: str, *legacy_aliases: str) -> bool:
        return await check_permission(interaction, command_name, ctx, legacy_aliases=legacy_aliases)

    async def _require_guild_channel(interaction: discord.Interaction) -> tuple[str, str] | None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("Use this command in a guild channel.", ephemeral=True)
            return None
        return str(interaction.guild_id), str(interaction.channel_id)

    async def _require_guild(interaction: discord.Interaction) -> str | None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Use this command in a guild.", ephemeral=True)
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

    async def _validate_embed_color(interaction: discord.Interaction, embed_color: Optional[str]) -> bool:
        if ctx.message_scheduler is None:
            return True
        if ctx.message_scheduler.is_valid_embed_color(embed_color):
            return True
        await interaction.response.send_message(
            "Invalid embed_color. Use #RRGGBB, RRGGBB, or 0xRRGGBB.",
            ephemeral=True,
        )
        return False

    async def _custom_toggle(interaction: discord.Interaction, action: str) -> None:
        if not await _check(interaction, f"campagne.custom.{action}"):
            return
        scope = await _require_guild_channel(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        rows = [row for row in await _list_custom_campaigns(guild_id) if str(row.get("channel_id")) == channel_id]
        if action == "status":
            enabled_count = sum(1 for row in rows if bool(row.get("enabled")))
            await interaction.response.send_message(
                f"Custom campaigns in this channel: {enabled_count}/{len(rows)} enabled.",
                ephemeral=True,
            )
            return
        enabled = action == "on"
        for row in rows:
            await ctx.database.set_message_campaign_enabled(guild_id, int(row["id"]), enabled)
        await interaction.response.send_message(
            f"Custom campaigns in this channel are now {'enabled' if enabled else 'disabled'}. Updated {len(rows)} entries.",
            ephemeral=True,
        )

    async def _build_service_run_payload(guild_id: str, channel_id: str, service_type: str) -> dict[str, object] | None:
        row = await ctx.database.get_campaign_content_config_by_service(guild_id, channel_id, service_type)
        return dict(row) if row is not None else None

    async def _set_service_enabled(interaction: discord.Interaction, *, service_type: str, action: str, legacy_aliases: tuple[str, ...] = ()) -> None:
        if not await _check(interaction, f"campagne.{service_type.lower()}.{action}", *legacy_aliases):
            return
        scope = await _require_guild_channel(interaction)
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
            base = f"{service_type.lower()} configs in this channel: {enabled_count}/{len(rows)} enabled."
            if latest is None:
                await interaction.response.send_message(base + " No active configuration found.", ephemeral=True)
                return
            await interaction.response.send_message(base + f" Latest: {_format_service_config_row(latest)}", ephemeral=True)
            return
        enabled = action == "on"
        for row in rows:
            await ctx.database.set_campaign_content_enabled(guild_id, int(row["id"]), enabled)
        await interaction.response.send_message(
            f"{service_type.title()} campaigns in this channel are now {'enabled' if enabled else 'disabled'}. Updated {len(rows)} entries.",
            ephemeral=True,
        )

    async def _service_config_show(
        interaction: discord.Interaction,
        *,
        service_type: str,
        legacy_aliases: tuple[str, ...] = (),
    ) -> None:
        if not await _check(interaction, f"campagne.{service_type.lower()}.config_show", *legacy_aliases):
            return
        scope = await _require_guild_channel(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        row = await ctx.database.get_campaign_content_config_by_service(guild_id, channel_id, service_type)
        if row is None:
            await interaction.response.send_message(f"No {service_type.lower()} config found for this channel.", ephemeral=True)
            return
        await interaction.response.send_message(_format_service_config_row(dict(row)), ephemeral=True)

    async def _service_config_reset(
        interaction: discord.Interaction,
        *,
        service_type: str,
        legacy_aliases: tuple[str, ...] = (),
    ) -> None:
        if not await _check(interaction, f"campagne.{service_type.lower()}.config_reset", *legacy_aliases):
            return
        scope = await _require_guild_channel(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        rows = await ctx.database.list_campaign_content_configs_by_service(
            guild_id,
            service_type=service_type,
            channel_id=channel_id,
            include_disabled=True,
        )
        for row in rows:
            await ctx.database.soft_delete_campaign_content_config(guild_id, int(row["id"]))
        await interaction.response.send_message(
            f"Reset {len(rows)} {service_type.lower()} config(s) for this channel.",
            ephemeral=True,
        )

    async def _service_run(
        interaction: discord.Interaction,
        *,
        service_type: str,
        legacy_aliases: tuple[str, ...] = (),
    ) -> None:
        if not await _check(interaction, f"campagne.{service_type.lower()}.run", *legacy_aliases):
            return
        scope = await _require_guild_channel(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        row = await _build_service_run_payload(guild_id, channel_id, service_type)
        if row is None:
            await interaction.response.send_message(f"No {service_type.lower()} config found for this channel.", ephemeral=True)
            return
        service = getattr(ctx.message_scheduler, "_campaign_content_service", None) if ctx.message_scheduler is not None else None
        if service is None:
            await interaction.response.send_message("Campaign content service unavailable.", ephemeral=True)
            return
        await interaction.response.send_message(f"Running {service_type.lower()} campaign now.", ephemeral=True)
        if service_type == "NEWS":
            await service.execute_news_service(row)
        elif service_type == "WEATHER":
            await service.execute_weather_service(row)
        elif service_type == "HOROSCOPE":
            await service.execute_horoscope_service(row)

    async def _service_config_set(
        interaction: discord.Interaction,
        *,
        service_type: str,
        publish_at: str | None,
        every: int | None,
        embed_title: str | None,
        embed_color: str | None,
        sources: str | None,
        categories: str | None,
        legacy_aliases: tuple[str, ...] = (),
    ) -> None:
        if not await _check(interaction, f"campagne.{service_type.lower()}.config_set", *legacy_aliases):
            return
        scope = await _require_guild_channel(interaction)
        if scope is None:
            return
        if not await _validate_embed_color(interaction, embed_color):
            return
        guild_id, channel_id = scope
        row = await ctx.database.get_campaign_content_config_by_service(guild_id, channel_id, service_type)
        existing = dict(row) if row is not None else None

        now = datetime.now(timezone.utc)
        resolved_publish = publish_at
        resolved_every = every if every is not None else int(existing["interval_minutes"]) if existing is not None else 0
        try:
            next_run, time_local, interval_minutes = _resolve_schedule(
                publish_at=resolved_publish,
                every=resolved_every,
                now_utc=now,
                tz=ctx.timezone,
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        if existing is not None and publish_at is None and every is None:
            time_local = str(existing["time_local"])
            next_run = datetime.fromisoformat(str(existing["next_run_at"])) if existing.get("next_run_at") else now
        sources_json = json.dumps(
            _parse_csv(sources) if sources is not None else json.loads(str(existing["sources_json"])) if existing and existing.get("sources_json") else [],
            ensure_ascii=False,
        )
        categories_json = categories if categories is not None else str(existing["categories_json"]) if existing and existing.get("categories_json") is not None else None
        resolved_embed_title = embed_title if embed_title is not None else str(existing["embed_title"]) if existing and existing.get("embed_title") is not None else None
        resolved_embed_color = embed_color if embed_color is not None else str(existing["embed_color"]) if existing and existing.get("embed_color") is not None else None

        if existing is None:
            config_id = await ctx.database.create_campaign_content_config(
                guild_id=guild_id,
                channel_id=channel_id,
                service_type=service_type,
                enabled=True,
                time_local=time_local,
                interval_minutes=interval_minutes,
                embed_title=resolved_embed_title,
                embed_color=resolved_embed_color,
                sources_json=sources_json,
                categories_json=categories_json,
                next_run_at=next_run.isoformat(),
            )
            await interaction.response.send_message(
                f"Created {service_type.lower()} config {config_id}. Next run: {next_run.isoformat()}.",
                ephemeral=True,
            )
            return

        await ctx.database.update_campaign_content_config(
            guild_id,
            int(existing["id"]),
            time_local=time_local,
            interval_minutes=interval_minutes,
            embed_title=resolved_embed_title,
            embed_color=resolved_embed_color,
            sources_json=sources_json,
            categories_json=categories_json,
            next_run_at=next_run.isoformat(),
            set_time_local=True,
            set_interval_minutes=True,
            set_embed_title=True,
            set_embed_color=True,
            set_sources_json=True,
            set_categories_json=True,
            set_next_run_at=True,
        )
        await interaction.response.send_message(
            f"Updated {service_type.lower()} config {existing['id']}. Next run: {next_run.isoformat()}.",
            ephemeral=True,
        )

    @campagne_group.command(name="on", description="Enable campaigns in the current channel")
    async def messaggi_on(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campagne.on"):
            return
        scope = await _require_guild_channel(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        await ctx.database.set_message_channel_enabled(guild_id, channel_id, True)
        await interaction.response.send_message("Campaigns enabled in this channel.", ephemeral=True)

    @campagne_group.command(name="off", description="Disable campaigns in the current channel")
    async def messaggi_off(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campagne.off"):
            return
        scope = await _require_guild_channel(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        await ctx.database.set_message_channel_enabled(guild_id, channel_id, False)
        await interaction.response.send_message("Campaigns disabled in this channel.", ephemeral=True)

    @campagne_group.command(name="status", description="Show campaign status for the current channel")
    async def messaggi_status(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campagne.status"):
            return
        scope = await _require_guild_channel(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        enabled = await ctx.database.get_message_channel_status(guild_id, channel_id)
        active_campaigns = await ctx.database.list_message_campaigns(guild_id, include_disabled=False)
        active_for_channel = [row for row in active_campaigns if str(row["channel_id"]) == channel_id]
        await interaction.response.send_message(
            f"Channel campaigns are {'enabled' if enabled else 'disabled'}. Active entries in this channel: {len(active_for_channel)}.",
            ephemeral=True,
        )

    @quiet_group.command(name="on", description="Enable quiet hours")
    async def quiet_on(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campagne.quiet.on", "campagne.quiet_on"):
            return
        await ctx.database.set_setting("messages_quiet_enabled", "1")
        await interaction.response.send_message("Quiet hours enabled.", ephemeral=True)

    @quiet_group.command(name="off", description="Disable quiet hours")
    async def quiet_off(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campagne.quiet.off", "campagne.quiet_off"):
            return
        await ctx.database.set_setting("messages_quiet_enabled", "0")
        await interaction.response.send_message("Quiet hours disabled.", ephemeral=True)

    @quiet_group.command(name="status", description="Show quiet hours status")
    async def quiet_status(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campagne.quiet.status", "campagne.quiet_status"):
            return
        enabled = await _ensure_setting(ctx, "messages_quiet_enabled", "1")
        start = await _ensure_setting(ctx, "messages_quiet_start", QUIET_DEFAULT_START)
        end = await _ensure_setting(ctx, "messages_quiet_end", QUIET_DEFAULT_END)
        await interaction.response.send_message(
            f"Quiet hours are {'enabled' if enabled == '1' else 'disabled'}: {start}-{end}.",
            ephemeral=True,
        )

    @quiet_group.command(name="config_set", description="Set quiet hours configuration")
    @app_commands.describe(start="Quiet hours start time (HH:MM)", end="Quiet hours end time (HH:MM)")
    async def quiet_config_set(interaction: discord.Interaction, start: str, end: str) -> None:
        if not await _check(interaction, "campagne.quiet.config_set", "campagne.quiet.set", "campagne.quiet_set"):
            return
        await ctx.database.set_setting("messages_quiet_start", start)
        await ctx.database.set_setting("messages_quiet_end", end)
        await interaction.response.send_message(f"Quiet hours updated to {start}-{end}.", ephemeral=True)

    @quiet_group.command(name="config_show", description="Show quiet hours configuration")
    async def quiet_config_show(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campagne.quiet.config_show", "campagne.quiet_status"):
            return
        start = await _ensure_setting(ctx, "messages_quiet_start", QUIET_DEFAULT_START)
        end = await _ensure_setting(ctx, "messages_quiet_end", QUIET_DEFAULT_END)
        await interaction.response.send_message(f"Quiet hours config: start={start}, end={end}.", ephemeral=True)

    @quiet_group.command(name="config_reset", description="Reset quiet hours configuration")
    async def quiet_config_reset(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campagne.quiet.config_reset", "campagne.quiet.set", "campagne.quiet_set"):
            return
        await ctx.database.set_setting("messages_quiet_start", QUIET_DEFAULT_START)
        await ctx.database.set_setting("messages_quiet_end", QUIET_DEFAULT_END)
        await interaction.response.send_message("Quiet hours configuration reset to defaults.", ephemeral=True)

    @cap_group.command(name="on", description="Enable the daily cap")
    async def cap_on(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campagne.cap.on", "campagne.cap_on"):
            return
        await ctx.database.set_setting("messages_daily_cap_enabled", "1")
        await interaction.response.send_message("Daily cap enabled.", ephemeral=True)

    @cap_group.command(name="off", description="Disable the daily cap")
    async def cap_off(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campagne.cap.off", "campagne.cap_off"):
            return
        await ctx.database.set_setting("messages_daily_cap_enabled", "0")
        await interaction.response.send_message("Daily cap disabled.", ephemeral=True)

    @cap_group.command(name="status", description="Show the daily cap status")
    async def cap_status(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campagne.cap.status", "campagne.cap_status"):
            return
        enabled = await _ensure_setting(ctx, "messages_daily_cap_enabled", "1")
        cap = await _ensure_setting(ctx, "messages_daily_cap", str(CAP_DEFAULT))
        await interaction.response.send_message(
            f"Daily cap is {'enabled' if enabled == '1' else 'disabled'}: {cap} messages/day.",
            ephemeral=True,
        )

    @cap_group.command(name="config_set", description="Set the daily cap configuration")
    @app_commands.describe(daily_limit="Maximum messages per day")
    async def cap_config_set(interaction: discord.Interaction, daily_limit: int) -> None:
        if not await _check(interaction, "campagne.cap.config_set", "campagne.cap.set", "campagne.cap_set"):
            return
        if daily_limit <= 0:
            await interaction.response.send_message("daily_limit must be greater than 0.", ephemeral=True)
            return
        await ctx.database.set_setting("messages_daily_cap", str(daily_limit))
        await interaction.response.send_message(f"Daily cap set to {daily_limit}.", ephemeral=True)

    @cap_group.command(name="config_show", description="Show the daily cap configuration")
    async def cap_config_show(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campagne.cap.config_show", "campagne.cap_status"):
            return
        cap = await _ensure_setting(ctx, "messages_daily_cap", str(CAP_DEFAULT))
        await interaction.response.send_message(f"Daily cap config: daily_limit={cap}.", ephemeral=True)

    @cap_group.command(name="config_reset", description="Reset the daily cap configuration")
    async def cap_config_reset(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campagne.cap.config_reset", "campagne.cap.set", "campagne.cap_set"):
            return
        await ctx.database.set_setting("messages_daily_cap", str(CAP_DEFAULT))
        await interaction.response.send_message("Daily cap configuration reset to defaults.", ephemeral=True)

    @custom_group.command(name="on", description="Enable custom campaigns in the current channel")
    async def custom_on(interaction: discord.Interaction) -> None:
        await _custom_toggle(interaction, "on")

    @custom_group.command(name="off", description="Disable custom campaigns in the current channel")
    async def custom_off(interaction: discord.Interaction) -> None:
        await _custom_toggle(interaction, "off")

    @custom_group.command(name="status", description="Show custom campaign status for the current channel")
    async def custom_status(interaction: discord.Interaction) -> None:
        await _custom_toggle(interaction, "status")

    @custom_group.command(name="entry_add", description="Add a custom campaign entry")
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
    async def custom_entry_add(
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
        if not await _check(interaction, "campagne.custom.entry_add", "campagne.aggiungi"):
            return
        scope = await _require_guild_channel(interaction)
        if scope is None:
            return
        if not await _validate_embed_color(interaction, embed_color):
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
            await interaction.response.send_message(str(exc), ephemeral=True)
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
            await interaction.response.send_message(validation_error, ephemeral=True)
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
        await interaction.response.send_message(
            f"Created custom campaign {campaign_id}. Next run: {next_run.isoformat()}.",
            ephemeral=True,
        )

    @custom_group.command(name="entry_list", description="List custom campaign entries")
    async def custom_entry_list(interaction: discord.Interaction) -> None:
        if not await _check(interaction, "campagne.custom.entry_list", "campagne.lista"):
            return
        guild_id = await _require_guild(interaction)
        if guild_id is None:
            return
        campaigns = await _list_custom_campaigns(guild_id)
        if not campaigns:
            await interaction.response.send_message("No custom campaigns configured.", ephemeral=True)
            return
        await interaction.response.send_message("\n".join(_format_message_campaign_row(row) for row in campaigns), ephemeral=True)

    @custom_group.command(name="entry_show", description="Show a custom campaign entry")
    @app_commands.describe(id="Campaign entry ID")
    async def custom_entry_show(interaction: discord.Interaction, id: int) -> None:
        if not await _check(interaction, "campagne.custom.entry_show"):
            return
        guild_id = await _require_guild(interaction)
        if guild_id is None:
            return
        campaign = await _get_custom_campaign(guild_id, id)
        if campaign is None:
            await interaction.response.send_message("Custom campaign not found.", ephemeral=True)
            return
        await interaction.response.send_message(_format_message_campaign_row(campaign), ephemeral=True)

    @custom_group.command(name="entry_remove", description="Remove a custom campaign entry")
    @app_commands.describe(id="Campaign entry ID")
    async def custom_entry_remove(interaction: discord.Interaction, id: int) -> None:
        if not await _check(interaction, "campagne.custom.entry_remove", "campagne.cancella"):
            return
        guild_id = await _require_guild(interaction)
        if guild_id is None:
            return
        campaign = await _get_custom_campaign(guild_id, id)
        if campaign is None:
            await interaction.response.send_message("Custom campaign not found.", ephemeral=True)
            return
        await ctx.database.soft_delete_message_campaign(guild_id, id)
        await interaction.response.send_message(f"Removed custom campaign {id}.", ephemeral=True)

    @custom_group.command(name="entry_run", description="Run a custom campaign entry now")
    @app_commands.describe(id="Campaign entry ID")
    async def custom_entry_run(interaction: discord.Interaction, id: int) -> None:
        if not await _check(interaction, "campagne.custom.entry_run", "campagne.test"):
            return
        guild_id = await _require_guild(interaction)
        if guild_id is None or interaction.channel is None or interaction.channel_id is None:
            if not interaction.response.is_done():
                await interaction.response.send_message("Use this command in a guild channel.", ephemeral=True)
            return
        campaign = await _get_custom_campaign(guild_id, id)
        if campaign is None:
            await interaction.response.send_message("Custom campaign not found.", ephemeral=True)
            return
        if ctx.message_scheduler is None:
            await interaction.response.send_message("Scheduler service unavailable.", ephemeral=True)
            return
        await interaction.response.send_message("Running custom campaign test.", ephemeral=True)
        if isinstance(interaction.channel, discord.abc.Messageable):
            rendered_text, _, _ = await ctx.message_scheduler.preview_campaign_text(
                campaign,
                channel_id_override=str(interaction.channel_id),
            )
            await ctx.message_scheduler.send_campaign_embed(interaction.channel, campaign, rendered_text)

    @custom_group.command(name="entry_edit", description="Edit a custom campaign entry")
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
        enabled="Enable or disable this entry",
    )
    @app_commands.choices(mood_mode=MOOD_CHOICES)
    async def custom_entry_edit(
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
        if not await _check(interaction, "campagne.custom.entry_edit", "campagne.pausa", "campagne.riprendi"):
            return
        guild_id = await _require_guild(interaction)
        if guild_id is None:
            return
        campaign = await _get_custom_campaign(guild_id, id)
        if campaign is None:
            await interaction.response.send_message("Custom campaign not found.", ephemeral=True)
            return
        if embed_color is not None and not await _validate_embed_color(interaction, embed_color):
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
            await interaction.response.send_message(validation_error, ephemeral=True)
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
                    await interaction.response.send_message(str(exc), ephemeral=True)
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
            await interaction.response.send_message("No changes requested.", ephemeral=True)
            return
        refreshed = await _get_custom_campaign(guild_id, id)
        await interaction.response.send_message(
            f"Updated custom campaign {id}.\n{_format_message_campaign_row(refreshed or campaign)}",
            ephemeral=True,
        )

    @news_group.command(name="on", description="Enable news campaigns in the current channel")
    async def news_on(interaction: discord.Interaction) -> None:
        await _set_service_enabled(interaction, service_type="NEWS", action="on", legacy_aliases=("campagne.notizie", "campagne.servizi_on"))

    @news_group.command(name="off", description="Disable news campaigns in the current channel")
    async def news_off(interaction: discord.Interaction) -> None:
        await _set_service_enabled(interaction, service_type="NEWS", action="off", legacy_aliases=("campagne.notizie", "campagne.servizi_off"))

    @news_group.command(name="status", description="Show news campaign status for the current channel")
    async def news_status(interaction: discord.Interaction) -> None:
        await _set_service_enabled(interaction, service_type="NEWS", action="status", legacy_aliases=("campagne.notizie",))

    @news_group.command(name="config_set", description="Create or update the news campaign configuration")
    @app_commands.describe(
        publish_at="First publication time (DD/MM/YYYY HH:MM)",
        every="Repeat interval in minutes",
        embed_title="Optional embed title",
        embed_color="Optional embed color",
        sources="Comma-separated source list or RSS URLs",
        categories="Comma-separated category list",
    )
    async def news_config_set(
        interaction: discord.Interaction,
        publish_at: str | None = None,
        every: int | None = None,
        embed_title: str | None = None,
        embed_color: str | None = None,
        sources: str | None = None,
        categories: str | None = None,
    ) -> None:
        await _service_config_set(
            interaction,
            service_type="NEWS",
            publish_at=publish_at,
            every=every,
            embed_title=embed_title,
            embed_color=embed_color,
            sources=sources,
            categories=categories,
            legacy_aliases=("campagne.notizie",),
        )

    @news_group.command(name="config_show", description="Show the news campaign configuration")
    async def news_config_show(interaction: discord.Interaction) -> None:
        await _service_config_show(interaction, service_type="NEWS", legacy_aliases=("campagne.notizie", "campagne.servizi_lista"))

    @news_group.command(name="config_reset", description="Reset the news campaign configuration")
    async def news_config_reset(interaction: discord.Interaction) -> None:
        await _service_config_reset(interaction, service_type="NEWS", legacy_aliases=("campagne.servizi_delete",))

    @news_group.command(name="run", description="Run the news campaign immediately")
    async def news_run(interaction: discord.Interaction) -> None:
        await _service_run(interaction, service_type="NEWS", legacy_aliases=("campagne.servizi_test",))

    @weather_group.command(name="on", description="Enable weather campaigns in the current channel")
    async def weather_on(interaction: discord.Interaction) -> None:
        await _set_service_enabled(interaction, service_type="WEATHER", action="on", legacy_aliases=("campagne.meteo", "campagne.servizi_on"))

    @weather_group.command(name="off", description="Disable weather campaigns in the current channel")
    async def weather_off(interaction: discord.Interaction) -> None:
        await _set_service_enabled(interaction, service_type="WEATHER", action="off", legacy_aliases=("campagne.meteo", "campagne.servizi_off"))

    @weather_group.command(name="status", description="Show weather campaign status for the current channel")
    async def weather_status(interaction: discord.Interaction) -> None:
        await _set_service_enabled(interaction, service_type="WEATHER", action="status", legacy_aliases=("campagne.meteo",))

    @weather_group.command(name="config_set", description="Create or update the weather campaign configuration")
    @app_commands.describe(
        publish_at="First publication time (DD/MM/YYYY HH:MM)",
        every="Repeat interval in minutes",
        embed_title="Optional embed title",
        embed_color="Optional embed color",
        sources="Comma-separated provider list",
    )
    async def weather_config_set(
        interaction: discord.Interaction,
        publish_at: str | None = None,
        every: int | None = None,
        embed_title: str | None = None,
        embed_color: str | None = None,
        sources: str | None = None,
    ) -> None:
        await _service_config_set(
            interaction,
            service_type="WEATHER",
            publish_at=publish_at,
            every=every,
            embed_title=embed_title,
            embed_color=embed_color,
            sources=sources,
            categories=None,
            legacy_aliases=("campagne.meteo",),
        )

    @weather_group.command(name="config_show", description="Show the weather campaign configuration")
    async def weather_config_show(interaction: discord.Interaction) -> None:
        await _service_config_show(interaction, service_type="WEATHER", legacy_aliases=("campagne.meteo", "campagne.servizi_lista"))

    @weather_group.command(name="config_reset", description="Reset the weather campaign configuration")
    async def weather_config_reset(interaction: discord.Interaction) -> None:
        await _service_config_reset(interaction, service_type="WEATHER", legacy_aliases=("campagne.servizi_delete",))

    @weather_group.command(name="run", description="Run the weather campaign immediately")
    async def weather_run(interaction: discord.Interaction) -> None:
        await _service_run(interaction, service_type="WEATHER", legacy_aliases=("campagne.servizi_test",))

    @horoscope_group.command(name="on", description="Enable horoscope campaigns in the current channel")
    async def horoscope_on(interaction: discord.Interaction) -> None:
        await _set_service_enabled(interaction, service_type="HOROSCOPE", action="on", legacy_aliases=("campagne.oroscopo", "campagne.servizi_on"))

    @horoscope_group.command(name="off", description="Disable horoscope campaigns in the current channel")
    async def horoscope_off(interaction: discord.Interaction) -> None:
        await _set_service_enabled(interaction, service_type="HOROSCOPE", action="off", legacy_aliases=("campagne.oroscopo", "campagne.servizi_off"))

    @horoscope_group.command(name="status", description="Show horoscope campaign status for the current channel")
    async def horoscope_status(interaction: discord.Interaction) -> None:
        await _set_service_enabled(interaction, service_type="HOROSCOPE", action="status", legacy_aliases=("campagne.oroscopo",))

    @horoscope_group.command(name="config_set", description="Create or update the horoscope campaign configuration")
    @app_commands.describe(
        publish_at="First publication time (DD/MM/YYYY HH:MM)",
        every="Repeat interval in minutes",
        embed_title="Optional embed title",
        embed_color="Optional embed color",
        sources="Comma-separated provider list",
    )
    async def horoscope_config_set(
        interaction: discord.Interaction,
        publish_at: str | None = None,
        every: int | None = None,
        embed_title: str | None = None,
        embed_color: str | None = None,
        sources: str | None = None,
    ) -> None:
        await _service_config_set(
            interaction,
            service_type="HOROSCOPE",
            publish_at=publish_at,
            every=every,
            embed_title=embed_title,
            embed_color=embed_color,
            sources=sources,
            categories=None,
            legacy_aliases=("campagne.oroscopo",),
        )

    @horoscope_group.command(name="config_show", description="Show the horoscope campaign configuration")
    async def horoscope_config_show(interaction: discord.Interaction) -> None:
        await _service_config_show(interaction, service_type="HOROSCOPE", legacy_aliases=("campagne.oroscopo", "campagne.servizi_lista"))

    @horoscope_group.command(name="config_reset", description="Reset the horoscope campaign configuration")
    async def horoscope_config_reset(interaction: discord.Interaction) -> None:
        await _service_config_reset(interaction, service_type="HOROSCOPE", legacy_aliases=("campagne.servizi_delete",))

    @horoscope_group.command(name="run", description="Run the horoscope campaign immediately")
    async def horoscope_run(interaction: discord.Interaction) -> None:
        await _service_run(interaction, service_type="HOROSCOPE", legacy_aliases=("campagne.servizi_test",))
