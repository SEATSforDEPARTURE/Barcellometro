from __future__ import annotations

import discord
from discord import app_commands

from app.shared.discord.command_embeds import (
    CommandEmbedSection,
    build_command_embeds,
    send_command_embeds,
    send_legacy_standard_response,
    send_standard_response,
)
from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.services.ai_model_catalog import build_model_autocomplete_choices
from app.services.footer import ServiceFooterProfile, ServiceFooterVariant, _is_persistable_service_name


def _clean_opt(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _format_value(value: str | None) -> str:
    return value if value else "(not set)"


def _human_service_name(service_name: str) -> str:
    labels = {
        "campagne_notizie": "campagne_notizie",
        "campagne_meteo": "campagne_meteo",
        "campagne_oroscopo": "campagne_oroscopo",
        "campagne_prompt": "campagne_prompt",
        "campagne_timer": "campagne_timer",
    }
    return labels.get(service_name, service_name.replace("_", " ").title())


def _format_contributors(contributors: list[str]) -> str:
    return " + ".join(contributors) if contributors else "(none)"


def _format_variant_block(service_name: str, variant: ServiceFooterVariant, phrase: str) -> str:
    mode = "local" if variant.used_local_processing else "remote"
    footer_text = variant.last_rendered_footer or "(footer not rendered yet)"
    origins = ",".join(sorted(variant.origins or [])) or "(n/a)"
    updated = variant.updated_at or "(n/a)"
    return (
        f"variant: {mode} | {_format_contributors(variant.contributors)}\n"
        f"→ {footer_text}\n"
        f"phrase: {phrase}\n"
        f"origin: {origins}\n"
        f"updated: {updated}\n"
        f"key: {variant.variant_key}"
    )


def _format_service_header(service_name: str) -> str:
    return f"**{service_name}**\nlabel: {_human_service_name(service_name)}\ntechnical alias: `{service_name}`"


def _service_section(service_name: str) -> int:
    if service_name in {"campagne_notizie", "campagne_meteo", "campagne_oroscopo"}:
        return 1
    if service_name == "campagne_prompt":
        return 2
    if service_name == "campagne_timer":
        return 3
    return 0


def _split_long_text(text: str, max_len: int = 1900) -> list[str]:
    clean_text = text.strip()
    if not clean_text:
        return []
    if len(clean_text) <= max_len:
        return [clean_text]

    parts: list[str] = []
    for line in clean_text.split("\n"):
        if len(line) <= max_len:
            parts.append(line)
            continue
        for idx in range(0, len(line), max_len):
            parts.append(line[idx : idx + max_len])

    chunks: list[str] = []
    current = ""
    for part in parts:
        candidate = f"{current}\n{part}" if current else part
        if len(candidate) <= max_len:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = part
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk]


def _chunk_status_blocks(blocks: list[str], max_len: int = 1900) -> list[str]:
    chunks: list[str] = []
    current = ""

    for raw_block in blocks:
        block = raw_block.strip()
        if not block:
            continue
        if len(block) > max_len:
            split_blocks = _split_long_text(block, max_len=max_len)
        else:
            split_blocks = [block]

        for split_block in split_blocks:
            candidate = f"{current}\n\n{split_block}" if current else split_block
            if len(candidate) <= max_len:
                current = candidate
                continue
            if current:
                chunks.append(current)
            current = split_block
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk]




async def _send_admin_response(
    interaction: discord.Interaction,
    ctx: CommandContext,
    *,
    subcommand_path: str,
    lines: list[tuple[str, object]] | None = None,
    sections: list[CommandEmbedSection] | None = None,
    kind: str = "info",
) -> None:
    await send_standard_response(
        interaction,
        top_level="bm",
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


async def _infer_audio_notes_profile(ctx: CommandContext) -> ServiceFooterProfile:
    stt_backend = ((await ctx.database.get_setting("stt.backend")) or "local").strip().lower()
    translate_backend = ((await ctx.database.get_setting("translate.backend")) or "local").strip().lower()
    stt_local_model = ((await ctx.database.get_setting("stt.local.model")) or "small").strip()
    stt_ai_model = ctx.ai.get_runtime_model("transcription") if ctx.ai is not None else "openai:gpt-4o-transcribe"
    translate_ai_model = ctx.ai.get_runtime_model("translation") if ctx.ai is not None else "openai:gpt-4o-mini"

    stt_model = stt_local_model if stt_backend != "ai" else (stt_ai_model or "gpt-4o-transcribe")
    translation_model = "argos" if translate_backend != "ai" else (translate_ai_model or "gpt-4o-mini")

    contributors: list[str] = []
    if stt_model:
        contributors.append(stt_model)
    if translation_model:
        contributors.append(translation_model)

    deduped: list[str] = []
    seen: set[str] = set()
    for item in contributors:
        clean = item.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        deduped.append(clean)

    return ServiceFooterProfile(
        service_name="audio_notes",
        contributors=deduped,
        used_local_processing=(stt_backend != "ai" or translate_backend != "ai"),
        last_rendered_footer=None,
        updated_at=None,
        origins={"inference"},
    )


async def _infer_service_profile(service_name: str, ctx: CommandContext) -> ServiceFooterProfile:
    if service_name == "audio_notes":
        return await _infer_audio_notes_profile(ctx)
    return ServiceFooterProfile(
        service_name=service_name,
        contributors=[],
        used_local_processing=True,
        last_rendered_footer=None,
        updated_at=None,
        origins={"fallback"},
    )


def register_admin(bm_group: app_commands.Group, ctx: CommandContext) -> None:
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
    footer_group = app_commands.Group(name="footer", description="Footer controls")
    bm_group.add_command(events_group)
    bm_group.add_command(retention_group)
    bm_group.add_command(backfill_group)
    bm_group.add_command(ai_group)
    bm_group.add_command(footer_group)

    async def _require_guild_channel(interaction: discord.Interaction) -> discord.abc.GuildChannel | None:
        if not interaction.channel or not isinstance(interaction.channel, discord.abc.GuildChannel):
            await send_legacy_standard_response(
                interaction,
                top_level="bm",
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
        await send_legacy_standard_response(
            interaction,
            top_level="bm",
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
        await send_legacy_standard_response(
            interaction,
            top_level="bm",
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
            await send_legacy_standard_response(
                interaction,
                top_level="bm",
                path_parts=["ai", "model_show" if "primary" in title.lower() else "fallback_show"],
                entries=[("Task", task), ("Model", values.get(task) or "(not set)")],
                service_name="status",
            )
            return
        await send_legacy_standard_response(
            interaction,
            top_level="bm",
            path_parts=["ai", "model_show" if "primary" in title.lower() else "fallback_show"],
            entries=[("Configured Tasks", len(values))],
            sections=[("Models", [(item_task, item_model) for item_task, item_model in sorted(values.items())])],
            service_name="status",
        )

    @events_group.command(name="on", description="Enable event collection for this channel.")
    async def events_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.events.on", ctx, legacy_aliases=["bm.check"]):
            return
        await _set_events_enabled(interaction, True)

    @events_group.command(name="off", description="Disable event collection for this channel.")
    async def events_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.events.off", ctx, legacy_aliases=["bm.check"]):
            return
        await _set_events_enabled(interaction, False)

    @events_group.command(name="status", description="Show event collection status for this channel.")
    async def events_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.events.status", ctx, legacy_aliases=["bm.check"]):
            return
        await _show_events_status(interaction)

    @retention_group.command(name="on", description="Enable the retention task.")
    async def retention_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.retention.on", ctx, legacy_aliases=["bm.retention"]):
            return
        await ctx.retention.set_enabled(True)
        await send_legacy_standard_response(interaction, top_level="bm", path_parts=["retention", "on"], entries=[("Status", "enabled")], tone="success", service_name="status")

    @retention_group.command(name="off", description="Disable the retention task.")
    async def retention_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.retention.off", ctx, legacy_aliases=["bm.retention"]):
            return
        await ctx.retention.set_enabled(False)
        await send_legacy_standard_response(interaction, top_level="bm", path_parts=["retention", "off"], entries=[("Status", "disabled")], tone="success", service_name="status")

    @retention_group.command(name="status", description="Show retention status.")
    async def retention_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.retention.status", ctx, legacy_aliases=["bm.retention"]):
            return
        enabled = await ctx.retention.is_enabled()
        days = await ctx.retention.get_retention_days()
        await send_legacy_standard_response(
            interaction,
            top_level="bm",
            path_parts=["retention", "status"],
            entries=[("Status", enabled), ("Days", days)],
            service_name="status",
        )

    @retention_group.command(name="config_set", description="Update retention configuration.")
    @app_commands.describe(days="Retention window in days.")
    async def retention_config_set_command(interaction: discord.Interaction, days: int | None = None) -> None:
        if not await check_permission(interaction, "bm.retention.config_set", ctx, legacy_aliases=["bm.retention"]):
            return
        if days is None:
            await send_legacy_standard_response(
                interaction,
                top_level="bm",
                path_parts=["retention", "config_set"],
                entries=[("Reason", "No changes provided")],
                tone="warning",
                sections=[("Next Step", [("Command", "/bm retention config_show")])],
                service_name="status",
            )
            return
        if days <= 0:
            await send_legacy_standard_response(
                interaction,
                top_level="bm",
                path_parts=["retention", "config_set"],
                entries=[("Reason", "Provide a valid positive day value")],
                tone="error",
                service_name="status",
            )
            return
        await ctx.retention.set_retention_days(days)
        await send_legacy_standard_response(
            interaction,
            top_level="bm",
            path_parts=["retention", "config_set"],
            entries=[("Status", "updated"), ("Days", days)],
            tone="success",
            service_name="status",
        )

    @retention_group.command(name="config_show", description="Show retention configuration.")
    async def retention_config_show_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.retention.config_show", ctx, legacy_aliases=["bm.retention"]):
            return
        await send_legacy_standard_response(
            interaction,
            top_level="bm",
            path_parts=["retention", "config_show"],
            entries=[("Days", await ctx.retention.get_retention_days())],
            service_name="status",
        )

    @retention_group.command(name="config_reset", description="Reset retention configuration to defaults.")
    async def retention_config_reset_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.retention.config_reset", ctx, legacy_aliases=["bm.retention"]):
            return
        default_days = int(getattr(ctx.retention, "_default_days", 30))
        await ctx.retention.set_retention_days(default_days)
        await send_legacy_standard_response(
            interaction,
            top_level="bm",
            path_parts=["retention", "config_reset"],
            entries=[("Status", "reset"), ("Days", default_days)],
            tone="success",
            service_name="status",
        )

    @backfill_group.command(name="on", description="Enable backfill.")
    async def backfill_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.backfill.on", ctx, legacy_aliases=["bm.backfill"]):
            return
        await ctx.backfill.set_enabled(True)
        await send_legacy_standard_response(interaction, top_level="bm", path_parts=["backfill", "on"], entries=[("Status", "enabled")], tone="success", service_name="status")

    @backfill_group.command(name="off", description="Disable backfill.")
    async def backfill_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.backfill.off", ctx, legacy_aliases=["bm.backfill"]):
            return
        await ctx.backfill.set_enabled(False)
        await send_legacy_standard_response(interaction, top_level="bm", path_parts=["backfill", "off"], entries=[("Status", "disabled")], tone="success", service_name="status")

    @backfill_group.command(name="status", description="Show backfill status.")
    async def backfill_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.backfill.status", ctx, legacy_aliases=["bm.backfill"]):
            return
        enabled = await ctx.backfill.is_enabled()
        days = await ctx.backfill.get_backfill_days()
        await send_legacy_standard_response(
            interaction,
            top_level="bm",
            path_parts=["backfill", "status"],
            entries=[("Status", enabled), ("Days", days)],
            service_name="status",
        )

    @backfill_group.command(name="config_set", description="Update backfill configuration.")
    @app_commands.describe(days="Backfill window in days.")
    async def backfill_config_set_command(interaction: discord.Interaction, days: int | None = None) -> None:
        if not await check_permission(interaction, "bm.backfill.config_set", ctx, legacy_aliases=["bm.backfill"]):
            return
        if days is None:
            await send_legacy_standard_response(
                interaction,
                top_level="bm",
                path_parts=["backfill", "config_set"],
                entries=[("Reason", "No changes provided")],
                tone="warning",
                sections=[("Next Step", [("Command", "/bm backfill config_show")])],
                service_name="status",
            )
            return
        if days <= 0:
            await send_legacy_standard_response(
                interaction,
                top_level="bm",
                path_parts=["backfill", "config_set"],
                entries=[("Reason", "Provide a valid positive day value")],
                tone="error",
                service_name="status",
            )
            return
        await ctx.backfill.set_backfill_days(days)
        await send_legacy_standard_response(
            interaction,
            top_level="bm",
            path_parts=["backfill", "config_set"],
            entries=[("Status", "updated"), ("Days", days)],
            tone="success",
            service_name="status",
        )

    @backfill_group.command(name="config_show", description="Show backfill configuration.")
    async def backfill_config_show_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.backfill.config_show", ctx, legacy_aliases=["bm.backfill"]):
            return
        await send_legacy_standard_response(
            interaction,
            top_level="bm",
            path_parts=["backfill", "config_show"],
            entries=[("Days", await ctx.backfill.get_backfill_days())],
            service_name="status",
        )

    @backfill_group.command(name="config_reset", description="Reset backfill configuration to defaults.")
    async def backfill_config_reset_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.backfill.config_reset", ctx, legacy_aliases=["bm.backfill"]):
            return
        default_days = int(getattr(ctx.backfill, "_default_days", 30))
        await ctx.backfill.set_backfill_days(default_days)
        await send_legacy_standard_response(
            interaction,
            top_level="bm",
            path_parts=["backfill", "config_reset"],
            entries=[("Status", "reset"), ("Days", default_days)],
            tone="success",
            service_name="status",
        )

    @backfill_group.command(name="run", description="Run backfill now.")
    async def backfill_run_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.backfill.run", ctx, legacy_aliases=["bm.backfill"]):
            return
        if not await ctx.backfill.is_enabled():
            await send_legacy_standard_response(
                interaction,
                top_level="bm",
                path_parts=["backfill", "run"],
                entries=[("Reason", "Backfill is disabled"), ("Action", "Enable it first")],
                tone="warning",
                service_name="status",
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await ctx.backfill.run_once(force_full_window=True)
        await send_legacy_standard_response(
            interaction,
            top_level="bm",
            path_parts=["backfill", "run"],
            entries=[("Status", "completed")],
            tone="success",
            sections=[("Metrics", [("Messages", result.messages), ("Events", result.events), ("Channels", result.channels), ("Errors", result.errors)])],
            service_name="status",
        )

    @ai_group.command(name="on", description="Enable the AI service.")
    async def ai_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.ai.on", ctx, legacy_aliases=["bm.ai"]):
            return
        await ctx.ai.set_enabled(True)
        await send_legacy_standard_response(interaction, top_level="bm", path_parts=["ai", "on"], entries=[("Status", "enabled")], tone="success", service_name="status")

    @ai_group.command(name="off", description="Disable the AI service.")
    async def ai_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.ai.off", ctx, legacy_aliases=["bm.ai"]):
            return
        await ctx.ai.set_enabled(False)
        await send_legacy_standard_response(interaction, top_level="bm", path_parts=["ai", "off"], entries=[("Status", "disabled")], tone="success", service_name="status")

    @ai_group.command(name="model_set", description="Set the AI model for a task.")
    @app_commands.describe(task="AI task.", model="Select or search for a provider:model value.")
    @app_commands.choices(task=ai_task_choices)
    @app_commands.autocomplete(model=_autocomplete_ai_model)
    async def ai_model_set_command(
        interaction: discord.Interaction,
        task: app_commands.Choice[str],
        model: str,
    ) -> None:
        if not await check_permission(interaction, "bm.ai.model_set", ctx, legacy_aliases=["bm.ai-model"]):
            return
        if not _is_valid_provider_model(model):
            await send_legacy_standard_response(
                interaction,
                top_level="bm",
                path_parts=["ai", "model_set"],
                entries=[("Reason", "Invalid provider:model format")],
                tone="error",
                sections=[("Example", [("Model", "openai:gpt-4o-mini")])],
                service_name="status",
            )
            return
        await ctx.ai.set_model(task.value, model)
        await send_legacy_standard_response(
            interaction,
            top_level="bm",
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
        if not await check_permission(interaction, "bm.ai.model_show", ctx, legacy_aliases=["bm.ai-model", "bm.ai"]):
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
        if not await check_permission(interaction, "bm.ai.fallback_set", ctx, legacy_aliases=["bm.ai-model"]):
            return
        if not _is_valid_provider_model(model):
            await send_legacy_standard_response(
                interaction,
                top_level="bm",
                path_parts=["ai", "fallback_set"],
                entries=[("Reason", "Invalid provider:model format")],
                tone="error",
                sections=[("Example", [("Model", "openai:gpt-4o-mini")])],
                service_name="status",
            )
            return
        await ctx.ai.set_fallback_model(task.value, model)
        await send_legacy_standard_response(
            interaction,
            top_level="bm",
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
        if not await check_permission(interaction, "bm.ai.fallback_show", ctx, legacy_aliases=["bm.ai-model", "bm.ai"]):
            return
        status = ctx.ai.status()
        models = status.get("fallback_models", {}) if isinstance(status, dict) else {}
        await _send_ai_map(interaction, title="AI fallback models", values=models if isinstance(models, dict) else {}, task=task.value if task else None)

    @ai_group.command(name="status", description="Show AI service status.")
    async def ai_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.ai.status", ctx, legacy_aliases=["bm.ai"]):
            return
        status = ctx.ai.status()
        metrics = status.get("metrics", {}) if isinstance(status, dict) else {}
        models = status.get("models", {}) if isinstance(status, dict) else {}
        fallback_models = status.get("fallback_models", {}) if isinstance(status, dict) else {}

        last_test_state = metrics.get("last_test_ok")
        test_outcome = "(n/a)" if last_test_state is None else ("ok" if last_test_state else "failed")
        await send_legacy_standard_response(
            interaction,
            top_level="bm",
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
        if not await check_permission(interaction, "bm.ai.run", ctx, legacy_aliases=["bm.ai"]):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        web_value = (web.value if web is not None else "off") == "on"
        result = await ctx.ai.run_test(task.value, prompt, use_web=web_value)

        sections = [("Output", [("Result", _truncate_embed_text(result.get("output"), limit=900))])]
        if result.get("error"):
            sections.append(("Error", [("Message", _truncate_embed_text(str(result.get("error")), limit=900))]))
        await send_legacy_standard_response(
            interaction,
            top_level="bm",
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

    @footer_group.command(name="on", description="Enable footer rendering.")
    async def footer_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.footer.on", ctx, legacy_aliases=["bm.footer", "bm.footer_status"]):
            return
        if ctx.footer is None:
            await send_legacy_standard_response(interaction, top_level="bm", path_parts=["footer", "on"], entries=[("Reason", "Footer service is unavailable")], tone="error", service_name="status")
            return
        await ctx.footer.set_enabled(True)
        await send_legacy_standard_response(interaction, top_level="bm", path_parts=["footer", "on"], entries=[("Status", "enabled")], tone="success", service_name="status")

    @footer_group.command(name="off", description="Disable footer rendering.")
    async def footer_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.footer.off", ctx, legacy_aliases=["bm.footer", "bm.footer_status"]):
            return
        if ctx.footer is None:
            await send_legacy_standard_response(interaction, top_level="bm", path_parts=["footer", "off"], entries=[("Reason", "Footer service is unavailable")], tone="error", service_name="status")
            return
        await ctx.footer.set_enabled(False)
        await send_legacy_standard_response(interaction, top_level="bm", path_parts=["footer", "off"], entries=[("Status", "disabled")], tone="success", service_name="status")

    @footer_group.command(name="template_global_set", description="Set the global footer template.")
    @app_commands.describe(version="Optional footer brand version.", phrase="Optional global footer phrase.")
    async def footer_template_global_set_command(
        interaction: discord.Interaction,
        version: str | None = None,
        phrase: str | None = None,
    ) -> None:
        if not await check_permission(interaction, "bm.footer.template_global_set", ctx, legacy_aliases=["bm.footer"]):
            return
        if ctx.footer is None:
            await send_legacy_standard_response(interaction, top_level="bm", path_parts=["footer", "template_global_set"], entries=[("Reason", "Footer service is unavailable")], tone="error", service_name="status")
            return
        if version is None and phrase is None:
            await send_legacy_standard_response(
                interaction,
                top_level="bm",
                path_parts=["footer", "template_global_set"],
                entries=[("Reason", "No changes provided")],
                tone="warning",
                sections=[("Next Step", [("Command", "/bm footer template_global_show")])],
                service_name="status",
            )
            return
        if version is not None:
            await ctx.footer.set_version(_clean_opt(version))
        if phrase is not None:
            await ctx.footer.set_global_phrase(_clean_opt(phrase))
        await send_legacy_standard_response(
            interaction,
            top_level="bm",
            path_parts=["footer", "template_global_set"],
            entries=[("Status", "updated"), ("Version", _format_value(await ctx.footer.get_version())), ("Phrase", _format_value(await ctx.footer.get_global_phrase()))],
            tone="success",
            service_name="status",
        )

    @footer_group.command(name="template_global_show", description="Show the global footer template.")
    async def footer_template_global_show_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.footer.template_global_show", ctx, legacy_aliases=["bm.footer", "bm.footer_status"]):
            return
        if ctx.footer is None:
            await send_legacy_standard_response(interaction, top_level="bm", path_parts=["footer", "template_global_show"], entries=[("Reason", "Footer service is unavailable")], tone="error", service_name="status")
            return
        current_version = await ctx.footer.get_version()
        current_global = await ctx.footer.get_global_phrase()
        await send_legacy_standard_response(
            interaction,
            top_level="bm",
            path_parts=["footer", "template_global_show"],
            entries=[("Version", _format_value(current_version)), ("Phrase", _format_value(current_global))],
            service_name="status",
        )

    @footer_group.command(name="template_global_reset", description="Reset the global footer template.")
    async def footer_template_global_reset_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.footer.template_global_reset", ctx, legacy_aliases=["bm.footer"]):
            return
        if ctx.footer is None:
            await send_legacy_standard_response(interaction, top_level="bm", path_parts=["footer", "template_global_reset"], entries=[("Reason", "Footer service is unavailable")], tone="error", service_name="status")
            return
        await ctx.footer.set_version(None)
        await ctx.footer.set_global_phrase(None)
        await send_legacy_standard_response(interaction, top_level="bm", path_parts=["footer", "template_global_reset"], entries=[("Status", "reset")], tone="success", service_name="status")

    @footer_group.command(name="template_service_set", description="Set a service-specific footer template.")
    @app_commands.describe(service="Service name.", phrase="Service-specific footer phrase.")
    async def footer_template_service_set_command(
        interaction: discord.Interaction,
        service: str,
        phrase: str,
    ) -> None:
        if not await check_permission(interaction, "bm.footer.template_service_set", ctx, legacy_aliases=["bm.footer"]):
            return
        if ctx.footer is None:
            await send_legacy_standard_response(interaction, top_level="bm", path_parts=["footer", "template_service_set"], entries=[("Reason", "Footer service is unavailable")], tone="error", service_name="status")
            return
        service_name = _clean_opt(service)
        if service_name is None:
            await send_legacy_standard_response(interaction, top_level="bm", path_parts=["footer", "template_service_set"], entries=[("Reason", "Provide a valid service name")], tone="error", service_name="status")
            return
        await ctx.footer.set_service_phrase(service_name, _clean_opt(phrase))
        await send_legacy_standard_response(interaction, top_level="bm", path_parts=["footer", "template_service_set"], entries=[("Service", service_name), ("Status", "updated")], tone="success", service_name="status")

    @footer_group.command(name="template_service_show", description="Show a service-specific footer template.")
    @app_commands.describe(service="Service name.")
    async def footer_template_service_show_command(interaction: discord.Interaction, service: str) -> None:
        if not await check_permission(interaction, "bm.footer.template_service_show", ctx, legacy_aliases=["bm.footer", "bm.footer_status"]):
            return
        if ctx.footer is None:
            await send_legacy_standard_response(interaction, top_level="bm", path_parts=["footer", "template_service_show"], entries=[("Reason", "Footer service is unavailable")], tone="error", service_name="status")
            return
        service_name = _clean_opt(service)
        if service_name is None:
            await send_legacy_standard_response(interaction, top_level="bm", path_parts=["footer", "template_service_show"], entries=[("Reason", "Provide a valid service name")], tone="error", service_name="status")
            return
        phrase = (await ctx.footer.get_service_phrases()).get(service_name)
        await send_legacy_standard_response(
            interaction,
            top_level="bm",
            path_parts=["footer", "template_service_show"],
            entries=[("Service", service_name), ("Phrase", _format_value(phrase))],
            service_name="status",
        )

    @footer_group.command(name="template_service_reset", description="Reset a service-specific footer template.")
    @app_commands.describe(service="Service name.")
    async def footer_template_service_reset_command(interaction: discord.Interaction, service: str) -> None:
        if not await check_permission(interaction, "bm.footer.template_service_reset", ctx, legacy_aliases=["bm.footer"]):
            return
        if ctx.footer is None:
            await send_legacy_standard_response(interaction, top_level="bm", path_parts=["footer", "template_service_reset"], entries=[("Reason", "Footer service is unavailable")], tone="error", service_name="status")
            return
        service_name = _clean_opt(service)
        if service_name is None:
            await send_legacy_standard_response(interaction, top_level="bm", path_parts=["footer", "template_service_reset"], entries=[("Reason", "Provide a valid service name")], tone="error", service_name="status")
            return
        await ctx.footer.set_service_phrase(service_name, None)
        await send_legacy_standard_response(interaction, top_level="bm", path_parts=["footer", "template_service_reset"], entries=[("Service", service_name), ("Status", "reset")], tone="success", service_name="status")

    @footer_group.command(name="status", description="Show footer status and rendered variants.")
    async def footer_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.footer.status", ctx, legacy_aliases=["bm.footer_status", "bm.footer"]):
            return
        if ctx.footer is None:
            await send_legacy_standard_response(interaction, top_level="bm", path_parts=["footer", "status"], entries=[("Reason", "Footer service is unavailable")], tone="error", service_name="status")
            return

        enabled = await ctx.footer.is_enabled()
        service_phrases = await ctx.footer.get_service_phrases()
        global_phrase = await ctx.footer.get_global_phrase()
        known_services = await ctx.footer.get_known_services()
        service_sources = await ctx.footer.get_known_service_sources()
        all_variants = await ctx.footer.get_all_service_footer_variants()
        profile_map = await ctx.footer.get_service_footer_profiles()

        if not known_services:
            await send_legacy_standard_response(interaction, top_level="bm", path_parts=["footer", "status"], entries=[("Reason", "No known footer services")], tone="warning", service_name="status")
            return

        services = sorted(set(known_services), key=lambda name: (_service_section(name), name))
        sections: dict[str, list[str]] = {
            "Standard services": [],
            "Editorial campaigns": [],
            "Prompt campaigns": [],
            "Timer campaigns": [],
        }
        minimal_services: list[str] = []

        for service_name in services:
            if not _is_persistable_service_name(service_name):
                continue
            variants = all_variants.get(service_name, {})
            if not variants:
                profile = profile_map.get(service_name)
                if profile is None:
                    profile = await _infer_service_profile(service_name, ctx)
                footer_text, _ = await ctx.footer.render_footer(
                    service_name=service_name,
                    contributors=profile.contributors,
                    used_local_processing=profile.used_local_processing,
                )
                phrase = service_phrases.get(service_name) or global_phrase or "(none)"
                origins = sorted(set(service_sources.get(service_name, [])) | set(profile.origins or set()))
                minimal_services.append(
                    f"**{service_name}**\n"
                    f"label: {_human_service_name(service_name)}\n"
                    f"technical alias: `{service_name}`\n"
                    f"→ {footer_text}\n"
                    f"phrase: {phrase}\n"
                    f"origin: {','.join(origins) if origins else '(n/a)'}"
                )
                continue

            variant_blocks: list[str] = []
            for variant in sorted(variants.values(), key=lambda item: item.variant_key):
                phrase = service_phrases.get(service_name) or global_phrase or "(none)"
                variant_blocks.append(_format_variant_block(service_name, variant, phrase))

            service_block = f"{_format_service_header(service_name)}\n\n" + "\n\n".join(variant_blocks)
            section_idx = _service_section(service_name)
            if section_idx == 1:
                sections["Editorial campaigns"].append(service_block)
            elif section_idx == 2:
                sections["Prompt campaigns"].append(service_block)
            elif section_idx == 3:
                sections["Timer campaigns"].append(service_block)
            else:
                sections["Standard services"].append(service_block)

        lines: list[str] = [f"Footer rendering: {'on' if enabled else 'off'}"]
        for title in ["Standard services", "Editorial campaigns", "Prompt campaigns", "Timer campaigns"]:
            blocks = sections[title]
            if blocks:
                lines.append(f"__{title}__\n" + "\n\n".join(blocks))
        if minimal_services:
            lines.append("__Services without persisted footer variants__\n" + "\n\n".join(minimal_services))

        chunks = _chunk_status_blocks(lines, max_len=1900)
        if not chunks:
            await send_legacy_standard_response(interaction, top_level="bm", path_parts=["footer", "status"], entries=[("Reason", "No footer data available")], tone="warning", service_name="status")
            return

        sections_payload = [CommandEmbedSection(title="Details", lines=[("status", chunk)]) for chunk in chunks]
        await _send_admin_response(interaction, ctx, subcommand_path="footer status", lines=[("footer_rendering", "on" if enabled else "off")], sections=sections_payload)
