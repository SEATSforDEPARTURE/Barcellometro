from __future__ import annotations

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.services.ai_model_catalog import build_model_autocomplete_choices
from app.shared.discord.command_embeds import send_legacy_standard_response, send_standard_response


async def _send_legacy(interaction: discord.Interaction, ctx: CommandContext, **kwargs) -> None:
    await send_legacy_standard_response(interaction, footer_service=ctx.footer, **kwargs)


async def _send_admin_response(
    interaction: discord.Interaction,
    ctx: CommandContext,
    *,
    subcommand_path: str,
    lines: list[tuple[str, object]] | None = None,
    sections: list[tuple[str, list[tuple[str, object]]]] | None = None,
    kind: str = "info",
) -> None:
    await send_standard_response(
        interaction,
        top_level="admin",
        subcommand_path=subcommand_path,
        lines=lines,
        sections=sections,
        kind=kind,
        footer_service=ctx.footer,
        ephemeral=True,
    )


def _truncate_embed_text(value: str | None, limit: int = 1000) -> str:
    text = (value or "").strip()
    if not text:
        return "(empty)"
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def register_admin(admin_group: app_commands.Group, ctx: CommandContext) -> None:
    ai_task_choices = [
        app_commands.Choice(name="summary", value="summary"),
        app_commands.Choice(name="server_summary", value="server_summary"),
        app_commands.Choice(name="audio_summary", value="audio_summary"),
        app_commands.Choice(name="qa", value="qa"),
        app_commands.Choice(name="analysis", value="analysis"),
        app_commands.Choice(name="transcription", value="transcription"),
        app_commands.Choice(name="translation", value="translation"),
        app_commands.Choice(name="campaign_editorial", value="campaign_editorial"),
        app_commands.Choice(name="campaign_prompt", value="campaign_prompt"),
    ]
    toggle_choices = [app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")]

    events_group = app_commands.Group(name="events", description="Event collection controls")
    retention_group = app_commands.Group(name="retention", description="Retention controls")
    backfill_group = app_commands.Group(name="backfill", description="Backfill controls")
    ai_group = app_commands.Group(name="ai", description="AI service controls")
    admin_group.add_command(events_group)
    admin_group.add_command(retention_group)
    admin_group.add_command(backfill_group)
    admin_group.add_command(ai_group)

    async def _require_guild_channel(interaction: discord.Interaction) -> discord.abc.GuildChannel | None:
        if not interaction.channel or not isinstance(interaction.channel, discord.abc.GuildChannel):
            await _send_legacy(interaction, ctx,
                top_level="admin",
                path_parts=["events", "error"],
                entries=[("Reason", "This command only works in guild channels")],
                tone="error",
                service_name="status",
            )
            return None
        return interaction.channel

    async def _set_events_enabled(interaction: discord.Interaction, enabled: bool) -> None:
        channel = await _require_guild_channel(interaction)
        if channel is None:
            return
        await ctx.database.upsert_channel(
            channel_id=str(channel.id),
            guild_id=str(interaction.guild_id),
            name=channel.name,
            enabled=1 if enabled else 0,
            channel_type=str(channel.type),
            category_id=str(channel.category_id) if channel.category_id else None,
            is_nsfw=1 if channel.is_nsfw() else 0,
            slowmode_delay=channel.slowmode_delay,
        )
        await _send_legacy(interaction, ctx,
            top_level="admin",
            path_parts=["events", "on" if enabled else "off"],
            entries=[("Channel", getattr(channel, "mention", channel.name)), ("Status", "enabled" if enabled else "disabled")],
            tone="success",
            service_name="status",
        )

    async def _show_events_status(interaction: discord.Interaction) -> None:
        channel = await _require_guild_channel(interaction)
        if channel is None:
            return
        row = await ctx.database.fetchone("SELECT enabled FROM channels WHERE channel_id = ?", (str(channel.id),))
        enabled = bool(row and int(row["enabled"] or 0) == 1)
        await _send_legacy(interaction, ctx,
            top_level="admin",
            path_parts=["events", "status"],
            entries=[("Channel", getattr(channel, "mention", channel.name)), ("Status", enabled)],
            service_name="status",
        )

    async def _autocomplete_ai_model(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        selected_task = getattr(interaction.namespace, "task", None)
        task_value = selected_task.value if isinstance(selected_task, app_commands.Choice) else selected_task
        return await build_model_autocomplete_choices(task_value, current)

    def _is_valid_provider_model(value: str) -> bool:
        return ":" in value and bool(value.split(":", 1)[0].strip()) and bool(value.split(":", 1)[1].strip())

    async def _send_ai_map(
        interaction: discord.Interaction,
        *,
        title: str,
        values: dict[str, str],
        task: str | None,
    ) -> None:
        header = "ai model_show" if "primary" in title.lower() else "ai fallback_show"
        if task is not None:
            await _send_legacy(interaction, ctx,
                top_level="admin",
                path_parts=["ai", "model_show" if "primary" in title.lower() else "fallback_show"],
                entries=[("Task", task), ("Model", values.get(task) or "(not set)")],
                service_name="status",
            )
            return
        await _send_legacy(interaction, ctx,
            top_level="admin",
            path_parts=["ai", "model_show" if "primary" in title.lower() else "fallback_show"],
            entries=[("Configured Tasks", len(values))],
            sections=[("Models", [(item_task, item_model) for item_task, item_model in sorted(values.items())])],
            service_name="status",
        )

    @events_group.command(name="on", description="Enable event collection for this channel.")
    async def events_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.events.on", ctx):
            return
        await _set_events_enabled(interaction, True)

    @events_group.command(name="off", description="Disable event collection for this channel.")
    async def events_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.events.off", ctx):
            return
        await _set_events_enabled(interaction, False)

    @events_group.command(name="status", description="Show event collection status for this channel.")
    async def events_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.events.status", ctx):
            return
        await _show_events_status(interaction)

    @retention_group.command(name="on", description="Enable the retention task.")
    async def retention_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.retention.on", ctx):
            return
        await ctx.retention.set_enabled(True)
        await _send_legacy(interaction, ctx, top_level="admin", path_parts=["retention", "on"], entries=[("Status", "enabled")], tone="success", service_name="status")

    @retention_group.command(name="off", description="Disable the retention task.")
    async def retention_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.retention.off", ctx):
            return
        await ctx.retention.set_enabled(False)
        await _send_legacy(interaction, ctx, top_level="admin", path_parts=["retention", "off"], entries=[("Status", "disabled")], tone="success", service_name="status")

    @retention_group.command(name="status", description="Show retention status.")
    async def retention_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.retention.status", ctx):
            return
        enabled = await ctx.retention.is_enabled()
        days = await ctx.retention.get_retention_days()
        await _send_legacy(interaction, ctx,
            top_level="admin",
            path_parts=["retention", "status"],
            entries=[("Status", enabled), ("Days", days)],
            service_name="status",
        )

    @retention_group.command(name="config_set", description="Update retention configuration.")
    @app_commands.describe(days="Retention window in days.")
    async def retention_config_set_command(interaction: discord.Interaction, days: int | None = None) -> None:
        if not await check_permission(interaction, "admin.retention.config_set", ctx):
            return
        if days is None:
            await _send_legacy(interaction, ctx,
                top_level="admin",
                path_parts=["retention", "config_set"],
                entries=[("Reason", "No changes provided")],
                tone="warning",
                sections=[("Next Step", [("Command", "/admin retention config_show")])],
                service_name="status",
            )
            return
        if days <= 0:
            await _send_legacy(interaction, ctx,
                top_level="admin",
                path_parts=["retention", "config_set"],
                entries=[("Reason", "Provide a valid positive day value")],
                tone="error",
                service_name="status",
            )
            return
        await ctx.retention.set_retention_days(days)
        await _send_legacy(interaction, ctx,
            top_level="admin",
            path_parts=["retention", "config_set"],
            entries=[("Status", "updated"), ("Days", days)],
            tone="success",
            service_name="status",
        )

    @retention_group.command(name="config_show", description="Show retention configuration.")
    async def retention_config_show_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.retention.config_show", ctx):
            return
        await _send_legacy(interaction, ctx,
            top_level="admin",
            path_parts=["retention", "config_show"],
            entries=[("Days", await ctx.retention.get_retention_days())],
            service_name="status",
        )

    @retention_group.command(name="config_reset", description="Reset retention configuration to defaults.")
    async def retention_config_reset_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.retention.config_reset", ctx):
            return
        default_days = int(getattr(ctx.retention, "_default_days", 30))
        await ctx.retention.set_retention_days(default_days)
        await _send_legacy(interaction, ctx,
            top_level="admin",
            path_parts=["retention", "config_reset"],
            entries=[("Status", "reset"), ("Days", default_days)],
            tone="success",
            service_name="status",
        )

    @backfill_group.command(name="on", description="Enable backfill.")
    async def backfill_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.backfill.on", ctx):
            return
        await ctx.backfill.set_enabled(True)
        await _send_legacy(interaction, ctx, top_level="admin", path_parts=["backfill", "on"], entries=[("Status", "enabled")], tone="success", service_name="status")

    @backfill_group.command(name="off", description="Disable backfill.")
    async def backfill_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.backfill.off", ctx):
            return
        await ctx.backfill.set_enabled(False)
        await _send_legacy(interaction, ctx, top_level="admin", path_parts=["backfill", "off"], entries=[("Status", "disabled")], tone="success", service_name="status")

    @backfill_group.command(name="status", description="Show backfill status.")
    async def backfill_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.backfill.status", ctx):
            return
        enabled = await ctx.backfill.is_enabled()
        days = await ctx.backfill.get_backfill_days()
        await _send_legacy(interaction, ctx,
            top_level="admin",
            path_parts=["backfill", "status"],
            entries=[("Status", enabled), ("Days", days)],
            service_name="status",
        )

    @backfill_group.command(name="config_set", description="Update backfill configuration.")
    @app_commands.describe(days="Backfill window in days.")
    async def backfill_config_set_command(interaction: discord.Interaction, days: int | None = None) -> None:
        if not await check_permission(interaction, "admin.backfill.config_set", ctx):
            return
        if days is None:
            await _send_legacy(interaction, ctx,
                top_level="admin",
                path_parts=["backfill", "config_set"],
                entries=[("Reason", "No changes provided")],
                tone="warning",
                sections=[("Next Step", [("Command", "/admin backfill config_show")])],
                service_name="status",
            )
            return
        if days <= 0:
            await _send_legacy(interaction, ctx,
                top_level="admin",
                path_parts=["backfill", "config_set"],
                entries=[("Reason", "Provide a valid positive day value")],
                tone="error",
                service_name="status",
            )
            return
        await ctx.backfill.set_backfill_days(days)
        await _send_legacy(interaction, ctx,
            top_level="admin",
            path_parts=["backfill", "config_set"],
            entries=[("Status", "updated"), ("Days", days)],
            tone="success",
            service_name="status",
        )

    @backfill_group.command(name="config_show", description="Show backfill configuration.")
    async def backfill_config_show_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.backfill.config_show", ctx):
            return
        await _send_legacy(interaction, ctx,
            top_level="admin",
            path_parts=["backfill", "config_show"],
            entries=[("Days", await ctx.backfill.get_backfill_days())],
            service_name="status",
        )

    @backfill_group.command(name="config_reset", description="Reset backfill configuration to defaults.")
    async def backfill_config_reset_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.backfill.config_reset", ctx):
            return
        default_days = int(getattr(ctx.backfill, "_default_days", 30))
        await ctx.backfill.set_backfill_days(default_days)
        await _send_legacy(interaction, ctx,
            top_level="admin",
            path_parts=["backfill", "config_reset"],
            entries=[("Status", "reset"), ("Days", default_days)],
            tone="success",
            service_name="status",
        )

    @backfill_group.command(name="run", description="Run backfill now.")
    async def backfill_run_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.backfill.run", ctx):
            return
        if not await ctx.backfill.is_enabled():
            await _send_legacy(interaction, ctx,
                top_level="admin",
                path_parts=["backfill", "run"],
                entries=[("Reason", "Backfill is disabled"), ("Action", "Enable it first")],
                tone="warning",
                service_name="status",
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await ctx.backfill.run_once(force_full_window=True)
        await _send_legacy(interaction, ctx,
            top_level="admin",
            path_parts=["backfill", "run"],
            entries=[("Status", "completed")],
            tone="success",
            sections=[("Metrics", [("Messages", result.messages), ("Events", result.events), ("Channels", result.channels), ("Errors", result.errors)])],
            service_name="status",
        )

    @ai_group.command(name="on", description="Enable the AI service.")
    async def ai_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.ai.on", ctx):
            return
        await ctx.ai.set_enabled(True)
        await _send_legacy(interaction, ctx, top_level="admin", path_parts=["ai", "on"], entries=[("Status", "enabled")], tone="success", service_name="status")

    @ai_group.command(name="off", description="Disable the AI service.")
    async def ai_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.ai.off", ctx):
            return
        await ctx.ai.set_enabled(False)
        await _send_legacy(interaction, ctx, top_level="admin", path_parts=["ai", "off"], entries=[("Status", "disabled")], tone="success", service_name="status")

    @ai_group.command(name="model_set", description="Set the AI model for a task.")
    @app_commands.describe(task="AI task.", model="Select or search for a provider:model value.")
    @app_commands.choices(task=ai_task_choices)
    @app_commands.autocomplete(model=_autocomplete_ai_model)
    async def ai_model_set_command(
        interaction: discord.Interaction,
        task: app_commands.Choice[str],
        model: str,
    ) -> None:
        if not await check_permission(interaction, "admin.ai.model_set", ctx):
            return
        if not _is_valid_provider_model(model):
            await _send_legacy(interaction, ctx,
                top_level="admin",
                path_parts=["ai", "model_set"],
                entries=[("Reason", "Invalid provider:model format")],
                tone="error",
                sections=[("Example", [("Model", "openai:gpt-4o-mini")])],
                service_name="status",
            )
            return
        await ctx.ai.set_model(task.value, model)
        await _send_legacy(interaction, ctx,
            top_level="admin",
            path_parts=["ai", "model_set"],
            entries=[("Task", task.value), ("Model", model), ("Scope", "primary")],
            tone="success",
            service_name="status",
        )

    @ai_group.command(name="model_show", description="Show configured AI models.")
    @app_commands.describe(task="Optional AI task.")
    @app_commands.choices(task=ai_task_choices)
    async def ai_model_show_command(
        interaction: discord.Interaction,
        task: app_commands.Choice[str] | None = None,
    ) -> None:
        if not await check_permission(interaction, "admin.ai.model_show", ctx):
            return
        status = ctx.ai.status()
        models = status.get("models", {}) if isinstance(status, dict) else {}
        await _send_ai_map(interaction, title="AI primary models", values=models if isinstance(models, dict) else {}, task=task.value if task else None)

    @ai_group.command(name="fallback_set", description="Set the AI fallback model for a task.")
    @app_commands.describe(task="AI task.", model="Select or search for a provider:model value.")
    @app_commands.choices(task=ai_task_choices)
    @app_commands.autocomplete(model=_autocomplete_ai_model)
    async def ai_fallback_set_command(
        interaction: discord.Interaction,
        task: app_commands.Choice[str],
        model: str,
    ) -> None:
        if not await check_permission(interaction, "admin.ai.fallback_set", ctx):
            return
        if not _is_valid_provider_model(model):
            await _send_legacy(interaction, ctx,
                top_level="admin",
                path_parts=["ai", "fallback_set"],
                entries=[("Reason", "Invalid provider:model format")],
                tone="error",
                sections=[("Example", [("Model", "openai:gpt-4o-mini")])],
                service_name="status",
            )
            return
        await ctx.ai.set_fallback_model(task.value, model)
        await _send_legacy(interaction, ctx,
            top_level="admin",
            path_parts=["ai", "fallback_set"],
            entries=[("Task", task.value), ("Model", model), ("Scope", "fallback")],
            tone="success",
            service_name="status",
        )

    @ai_group.command(name="fallback_show", description="Show configured AI fallback models.")
    @app_commands.describe(task="Optional AI task.")
    @app_commands.choices(task=ai_task_choices)
    async def ai_fallback_show_command(
        interaction: discord.Interaction,
        task: app_commands.Choice[str] | None = None,
    ) -> None:
        if not await check_permission(interaction, "admin.ai.fallback_show", ctx):
            return
        status = ctx.ai.status()
        models = status.get("fallback_models", {}) if isinstance(status, dict) else {}
        await _send_ai_map(interaction, title="AI fallback models", values=models if isinstance(models, dict) else {}, task=task.value if task else None)

    @ai_group.command(name="status", description="Show AI service status.")
    async def ai_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.ai.status", ctx):
            return
        status = ctx.ai.status()
        metrics = status.get("metrics", {}) if isinstance(status, dict) else {}
        models = status.get("models", {}) if isinstance(status, dict) else {}
        fallback_models = status.get("fallback_models", {}) if isinstance(status, dict) else {}

        last_test_state = metrics.get("last_test_ok")
        test_outcome = "(n/a)" if last_test_state is None else ("ok" if last_test_state else "failed")
        await _send_legacy(interaction, ctx,
            top_level="admin",
            path_parts=["ai", "status"],
            entries=[("Service", status.get("state") or "unknown")],
            sections=[
                ("Primary", [(task_name, model_name) for task_name, model_name in sorted(models.items())] if isinstance(models, dict) else []),
                ("Fallback", [(task_name, model_name) for task_name, model_name in sorted(fallback_models.items())] if isinstance(fallback_models, dict) else []),
                ("Last Usage", [("Task", metrics.get("last_used_task") or "(n/a)"), ("Model", metrics.get("last_used_model") or "(n/a)")]),
                (
                    "Last Run",
                    [
                        ("Task", metrics.get("last_test_task") or "(n/a)"),
                        ("Model", metrics.get("last_test_model") or "(n/a)"),
                        ("Result", test_outcome),
                        ("Error", _truncate_embed_text(str(metrics.get("last_test_error"))) if metrics.get("last_test_error") else "(n/a)"),
                    ],
                ),
            ],
            service_name="status",
        )

    @ai_group.command(name="run", description="Run an AI test prompt.")
    @app_commands.describe(task="AI task.", prompt="Prompt text.", web="Enable or disable web search.")
    @app_commands.choices(task=ai_task_choices, web=toggle_choices)
    async def ai_run_command(
        interaction: discord.Interaction,
        task: app_commands.Choice[str],
        prompt: str,
        web: app_commands.Choice[str] | None = None,
    ) -> None:
        if not await check_permission(interaction, "admin.ai.run", ctx):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        web_value = (web.value if web is not None else "off") == "on"
        result = await ctx.ai.run_test(task.value, prompt, use_web=web_value)

        sections = [("Output", [("Result", _truncate_embed_text(result.get("output"), limit=900))])]
        if result.get("error"):
            sections.append(("Error", [("Message", _truncate_embed_text(str(result.get("error")), limit=900))]))
        await _send_legacy(interaction, ctx,
            top_level="admin",
            path_parts=["ai", "run"],
            entries=[
                ("Task", result.get("task") or task.value),
                ("Model", result.get("model") or "(n/a)"),
                ("Web", web_value),
                ("Result", "ok" if result.get("ok") else "failed"),
            ],
            tone="success" if result.get("ok") else "error",
            sections=sections,
            service_name="status",
        )

