from __future__ import annotations

from datetime import datetime

import discord
from discord import app_commands

from app.core.config_paths import BARCELLO_TRIGGER_JSON
from app.config.file_loader import load_json_file
from app.shared.discord.command_embeds import send_legacy_standard_response
from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission


async def _send_legacy(interaction: discord.Interaction, ctx: CommandContext, **kwargs) -> None:
    kwargs.setdefault("command_description", getattr(getattr(interaction, "command", None), "description", None))
    await send_legacy_standard_response(interaction, footer_service=ctx.footer, **kwargs)


async def _require_channel_scope(interaction: discord.Interaction, ctx: CommandContext) -> tuple[str, str] | None:
    if interaction.guild_id is None or interaction.channel_id is None:
        await _send_legacy(
            interaction,
            ctx,
            top_level="status",
            path_parts=["error"],
            entries=[("Reason", "This command only works in guild channels")],
            tone="error",
            service_name="status",
            ephemeral=True,
        )
        return None
    return str(interaction.guild_id), str(interaction.channel_id)


async def _show_barcello_mood(interaction: discord.Interaction, ctx: CommandContext) -> None:
    scope = await _require_channel_scope(interaction, ctx)
    if scope is None:
        return
    guild_id, channel_id = scope
    cfg = load_json_file(BARCELLO_TRIGGER_JSON)
    stored = await ctx.database.get_trigger_state(guild_id, channel_id, "barcello_mood")
    stored_mood = str(stored.get("mood") or "")

    channels_cfg = cfg.get("channels") if isinstance(cfg.get("channels"), dict) else {}
    channel_cfg = channels_cfg.get(channel_id) if isinstance(channels_cfg.get(channel_id), dict) else {}
    cfg_default = str(cfg.get("mood_default") or "chill")
    channel_default = str(channel_cfg.get("mood_default") or "")
    effective = stored_mood or channel_default or cfg_default

    time_buckets = cfg.get("time_buckets") if isinstance(cfg.get("time_buckets"), dict) else {}
    now_local = datetime.now(ctx.timezone)
    current_hour = now_local.hour
    time_bucket = "unknown"
    for name, payload in time_buckets.items():
        if not isinstance(payload, dict):
            continue
        start = payload.get("start")
        end = payload.get("end")
        if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= 24 and start <= current_hour < end:
            time_bucket = str(name)
            break

    daily = await ctx.database.get_trigger_state(guild_id, channel_id, "barcello_daily")
    day_key = now_local.date().isoformat()
    counts = daily.get("counts") if isinstance(daily.get("counts"), dict) and str(daily.get("date") or "") == day_key else {}
    last_status = await ctx.database.get_barcello_trigger_state(guild_id, channel_id)
    current_color = str((last_status or {}).get("last_color") or "")
    state_count_today = int(counts.get(current_color) or 0) if current_color else 0

    tiers = cfg.get("dramatic_tiers") if isinstance(cfg.get("dramatic_tiers"), list) else [{"min_count_today": 1, "label": "t1"}]
    drama_label = "t1"
    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        minimum = tier.get("min_count_today")
        label = tier.get("label")
        if isinstance(minimum, int) and isinstance(label, str) and state_count_today >= minimum:
            drama_label = label

    await _send_legacy(
        interaction,
        ctx,
        top_level="status",
        path_parts=["mood_show"],
        entries=[
            ("Current Mood", effective),
            ("Stored Mood", stored_mood or "-"),
            ("Channel Default Mood", channel_default or "-"),
            ("Global Default Mood", cfg_default),
            ("Current Time Bucket", time_bucket),
            ("Current Drama Label", f"{drama_label} (count {state_count_today}, state {current_color or '-'})"),
        ],
        service_name="status",
        ephemeral=True,
    )


def register_status(status_group: app_commands.Group, ctx: CommandContext) -> None:
    @status_group.command(name="show", description="Show the Barcellometro status.")
    @app_commands.describe(service="Optional service or plugin name.")
    async def status_show_command(interaction: discord.Interaction, service: str | None = None) -> None:
        if not await check_permission(interaction, "status", ctx):
            return
        if service:
            status = ctx.status.component_status(service)
            await _send_legacy(
                interaction,
                ctx,
                top_level="status",
                path_parts=["show", service],
                entries=[
                    ("Service", service),
                    ("Active", status["active"]),
                    ("State", status["state"]),
                    ("Metrics", status["metrics"]),
                ],
                service_name="status",
                ephemeral=True,
            )
            return
        general = await ctx.status.general_status()
        await _send_legacy(
            interaction,
            ctx,
            top_level="status",
            path_parts=["show"],
            entries=[
                ("Bot", "online"),
                ("Db Path", general["db_path"]),
                ("Retention Days", general["retention_days"]),
                ("Enabled Channels", general["enabled_channels"]),
                ("Users", general["users_count"]),
                ("Messages", general["messages_count"]),
                ("Events", general["events_count"]),
                ("Last Event", general["last_event_ts"]),
            ],
            service_name="status",
            ephemeral=True,
        )

    @status_group.command(name="mood_set", description="Set the Barcello mood for this channel.")
    @app_commands.describe(value="Mood value.")
    async def status_mood_set_command(interaction: discord.Interaction, value: str) -> None:
        if not await check_permission(interaction, "status.mood_set", ctx):
            return
        scope = await _require_channel_scope(interaction, ctx)
        if scope is None:
            return
        guild_id, channel_id = scope
        normalized = value.strip()
        if not normalized:
            await _send_legacy(
                interaction,
                ctx,
                top_level="status",
                path_parts=["mood_set"],
                entries=[("Reason", "Please provide a valid mood")],
                tone="warning",
                service_name="status",
                ephemeral=True,
            )
            return
        cfg = load_json_file(BARCELLO_TRIGGER_JSON)
        available_moods = cfg.get("moods") if isinstance(cfg.get("moods"), dict) else {}
        if available_moods and normalized not in available_moods:
            await _send_legacy(
                interaction,
                ctx,
                top_level="status",
                path_parts=["mood_set"],
                entries=[("Reason", f"Mood `{normalized}` is not defined in config")],
                sections=[("Available", [("Moods", ", ".join(sorted(available_moods.keys())))])],
                tone="error",
                service_name="status",
                ephemeral=True,
            )
            return
        today = datetime.now(ctx.timezone).date().isoformat()
        await ctx.database.set_trigger_state(
            guild_id,
            channel_id,
            "barcello_mood",
            {"mood": normalized, "date": today, "mode": "manual"},
        )
        await _send_legacy(
            interaction,
            ctx,
            top_level="status",
            path_parts=["mood_set"],
            entries=[("Status", "updated"), ("Mood", normalized)],
            tone="success",
            service_name="status",
            ephemeral=True,
        )

    @status_group.command(name="mood_show", description="Show the Barcello mood for this channel.")
    async def status_mood_show_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "status.mood_show", ctx):
            return
        await _show_barcello_mood(interaction, ctx)

    @status_group.command(name="mood_reset", description="Reset the Barcello mood for this channel.")
    async def status_mood_reset_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "status.mood_reset", ctx):
            return
        scope = await _require_channel_scope(interaction, ctx)
        if scope is None:
            return
        guild_id, channel_id = scope
        await ctx.database.set_trigger_state(guild_id, channel_id, "barcello_mood", {})
        await _send_legacy(
            interaction,
            ctx,
            top_level="status",
            path_parts=["mood_reset"],
            entries=[("Status", "reset")],
            tone="success",
            service_name="status",
            ephemeral=True,
        )
