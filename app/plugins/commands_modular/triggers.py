from __future__ import annotations

import logging
import json
import re
from datetime import datetime, timedelta, timezone

import discord

from app.services.footer import attach_footer_meta
from discord import app_commands

from app.plugins.commands_modular.command_helpers import add_group_once
from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.time_windows import parse_italian_datetime
from app.services.config_file_loader import load_json_file

logger = logging.getLogger(__name__)


BARCELLO_TRIGGER_CONFIG_PATH = "settings/barcello_trigger.json"


def register_triggers(
    bm_group: app_commands.Group,
    campagne_group: app_commands.Group,
    qna_group: app_commands.Group,
    insights_group: app_commands.Group,
    ctx: CommandContext,
) -> app_commands.Group:
    frasi_group = app_commands.Group(name="frasi", description="Phrase trigger controls")
    prompt_group = app_commands.Group(name="prompt", description="Prompt campaign controls")

    add_group_once(campagne_group, prompt_group, logger)

    def _normalize_embed_color(raw: str | None) -> str | None:
        if raw is None:
            return None
        value = raw.strip()
        if not value:
            return None

        if value.startswith("#"):
            candidate = value[1:]
            if len(candidate) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in candidate):
                return f"#{candidate.upper()}"
            return None

        lowered = value.lower()
        if lowered.startswith("0x"):
            candidate = value[2:]
            if len(candidate) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in candidate):
                return f"#{candidate.upper()}"
            return None

        if len(value) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in value):
            return f"#{value.upper()}"

        if value.isdigit():
            number = int(value, 10)
            if 0 <= number <= 0xFFFFFF:
                return f"#{number:06X}"
        return None

    def _normalize_phrase_templates_state(raw_state: dict[str, object]) -> dict[str, object]:
        state: dict[str, object] = {}

        templates: dict[str, str] = {}
        raw_templates = raw_state.get("templates")
        if isinstance(raw_templates, dict):
            for kind in ("DEFAULT", "FIRST"):
                value = raw_templates.get(kind)
                if isinstance(value, str):
                    templates[kind] = value
        if templates:
            state["templates"] = templates

        global_milestones_enabled = raw_state.get("global_milestones_enabled")
        if isinstance(global_milestones_enabled, bool):
            state["global_milestones_enabled"] = global_milestones_enabled

        return state

    def _parse_role_ids_input(raw_roles: str | None) -> list[str]:
        text = str(raw_roles or "").strip()
        if not text:
            return []
        found = re.findall(r"<@&(\d+)>", text)
        if found:
            values = found
        else:
            values = re.findall(r"\d+", text)
        return list(dict.fromkeys(values))

    def _format_phrase_row(row: dict[str, object]) -> str:
        role_ids = row.get("allowed_role_ids") if isinstance(row.get("allowed_role_ids"), list) else []
        roles_text = "tutti" if not role_ids else ", ".join(f"<@&{role_id}>" for role_id in role_ids)
        mode_raw = str(row.get("match_mode") or "CONTAINS").lower()
        cooldown_raw = row.get("cooldown_seconds")
        cooldown_text = f"{cooldown_raw}s" if cooldown_raw is not None else "nessuno"
        enabled = bool(row.get("enabled", 1))
        return " · ".join(
            [
                f"#{row.get('id')}",
                f'"{row.get("phrase")}"',
                f"mode: {mode_raw}",
                f"colore: {row.get('embed_color') or '-'}",
                f"cooldown: {cooldown_text}",
                f"ruoli: {roles_text}",
                f"stato: {'attiva' if enabled else 'disattiva'}",
            ]
        )

    def _humanize_ts(raw_ts: object) -> str:
        if not raw_ts:
            return "-"
        try:
            dt = datetime.fromisoformat(str(raw_ts))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
            minutes = max(0, int(delta.total_seconds() // 60))
            if minutes < 120:
                rel = f"{minutes}m fa"
            elif minutes < 60 * 48:
                rel = f"{minutes // 60}h fa"
            else:
                rel = f"{minutes // (60 * 24)}g fa"
            return f"{dt.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} ({rel})"
        except ValueError:
            return str(raw_ts)

    TIER_CHOICES = [
        app_commands.Choice(name="base", value="base"),
        app_commands.Choice(name="role1", value="role1"),
        app_commands.Choice(name="role2", value="role2"),
        app_commands.Choice(name="role3", value="role3"),
        app_commands.Choice(name="mod", value="mod"),
    ]

    MATCH_MODE_CHOICES = [
        app_commands.Choice(name="contains", value="CONTAINS"),
        app_commands.Choice(name="regex", value="REGEX"),
    ]

    async def _guard(interaction: discord.Interaction, *legacy_aliases: str) -> bool:
        return await check_permission(interaction, _command_permission_key(interaction), ctx, legacy_aliases=legacy_aliases)

    async def _require_channel(interaction: discord.Interaction, *legacy_aliases: str) -> tuple[str, str] | None:
        if not await _guard(interaction, *legacy_aliases):
            return None
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("Use this command in a guild channel.", ephemeral=True)
            return None
        return str(interaction.guild_id), str(interaction.channel_id)

    async def _set_toggle(interaction: discord.Interaction, key: str, action: str, *legacy_aliases: str) -> None:
        scope = await _require_channel(interaction, *legacy_aliases)
        if scope is None:
            return
        guild_id, channel_id = scope
        if key == "frasi":
            if action == "status":
                enabled = await ctx.database.get_trigger_enabled_global(guild_id, key)
                if not enabled:
                    enabled = await ctx.database.get_trigger_enabled_any_channel(guild_id, key)
                await interaction.response.send_message(f"Phrase triggers are {'on' if enabled else 'off'} at server scope.", ephemeral=True)
                return
            enabled = action == "on"
            await ctx.database.set_trigger_enabled_global(guild_id, key, enabled)
            await interaction.response.send_message(
                f"Phrase triggers are now {'enabled' if enabled else 'disabled'} at server scope.",
                ephemeral=True,
            )
            return
        if action == "status":
            enabled = await ctx.database.get_trigger_enabled(guild_id, channel_id, key)
            await interaction.response.send_message(f"{key} is {'on' if enabled else 'off'} in this channel.", ephemeral=True)
            return
        enabled = action == "on"
        await ctx.database.set_trigger_enabled(guild_id, channel_id, key, enabled)
        await interaction.response.send_message(f"{key} is now {'enabled' if enabled else 'disabled'} in this channel.", ephemeral=True)

    def _format_phrase_row(row: dict[str, object]) -> str:
        role_ids = row.get("allowed_role_ids") if isinstance(row.get("allowed_role_ids"), list) else []
        roles_text = "all" if not role_ids else ", ".join(f"<@&{role_id}>" for role_id in role_ids)
        mode_raw = str(row.get("match_mode") or "CONTAINS").lower()
        cooldown_raw = row.get("cooldown_seconds")
        cooldown_text = f"{cooldown_raw}s" if cooldown_raw is not None else "none"
        enabled = bool(row.get("enabled", 1))
        return " · ".join(
            [
                f"#{row.get('id')}",
                f'"{row.get("phrase")}"',
                f"mode: {mode_raw}",
                f"color: {row.get('embed_color') or '-'}",
                f"cooldown: {cooldown_text}",
                f"roles: {roles_text}",
                f"status: {'enabled' if enabled else 'disabled'}",
            ]
        )

    def _humanize_ts(raw_ts: object) -> str:
        if not raw_ts:
            return "-"
        try:
            dt = datetime.fromisoformat(str(raw_ts))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
            minutes = max(0, int(delta.total_seconds() // 60))
            if minutes < 120:
                rel = f"{minutes}m ago"
            elif minutes < 60 * 48:
                rel = f"{minutes // 60}h ago"
            else:
                rel = f"{minutes // (60 * 24)}d ago"
            return f"{dt.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} ({rel})"
        except ValueError:
            return str(raw_ts)

    @frasi_group.command(name="on", description="Enable phrase triggers")
    async def frasi_on(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "frasi", "on")

    @frasi_group.command(name="off", description="Disable phrase triggers")
    async def frasi_off(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "frasi", "off")

    @frasi_group.command(name="status", description="Show phrase trigger status")
    async def frasi_status(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "frasi", "status")

    @frasi_group.command(name="entry_add", description="Add a phrase trigger entry")
    @app_commands.describe(
        phrase="Trigger phrase",
        match_mode="Phrase match mode",
        color="Optional embed color (#RRGGBB)",
        cooldown_seconds="Optional cooldown in seconds",
        role_ids="Allowed roles as mentions or IDs",
    )
    @app_commands.choices(match_mode=MATCH_MODE_CHOICES)
    async def frasi_entry_add(
        interaction: discord.Interaction,
        phrase: str,
        match_mode: app_commands.Choice[str],
        color: str | None = None,
        cooldown_seconds: int | None = None,
        role_ids: str | None = None,
    ) -> None:
        scope = await _require_channel(interaction, "frasi.add")
        if scope is None:
            return
        guild_id, channel_id = scope
        if cooldown_seconds is not None and cooldown_seconds <= 0:
            await interaction.response.send_message("cooldown_seconds must be a positive integer.", ephemeral=True)
            return
        parsed_color = _normalize_embed_color(color)
        if color is not None and parsed_color is None:
            await interaction.response.send_message("Invalid color. Use #RRGGBB, RRGGBB, 0xRRGGBB, or a decimal value.", ephemeral=True)
            return
        parsed_role_ids = _parse_role_ids_input(role_ids)
        if parsed_role_ids and interaction.guild is None:
            await interaction.response.send_message("Cannot validate roles without guild context.", ephemeral=True)
            return
        if parsed_role_ids and interaction.guild is not None:
            invalid_ids = [role_id for role_id in parsed_role_ids if interaction.guild.get_role(int(role_id)) is None]
            if invalid_ids:
                await interaction.response.send_message(
                    f"Invalid roles for this server: {', '.join(invalid_ids)}",
                    ephemeral=True,
                )
                return
        await ctx.database.add_trigger_phrase(
            guild_id,
            channel_id,
            phrase,
            match_mode.value,
            False,
            parsed_color,
            cooldown_seconds,
            parsed_role_ids,
        )
        await interaction.response.send_message("Phrase trigger entry added.", ephemeral=True)

    @frasi_group.command(name="entry_remove", description="Remove a phrase trigger entry")
    @app_commands.describe(id="Phrase entry ID")
    async def frasi_entry_remove(interaction: discord.Interaction, id: int) -> None:
        scope = await _require_channel(interaction, "frasi.remove")
        if scope is None:
            return
        guild_id, _ = scope
        row = await ctx.database.get_trigger_phrase_by_id(guild_id, id)
        if not row:
            await interaction.response.send_message(f"Phrase entry #{id} not found.", ephemeral=True)
            return
        await ctx.database.remove_trigger_phrase_by_id(guild_id, id)
        await interaction.response.send_message(f"Phrase entry #{id} removed.", ephemeral=True)

    @frasi_group.command(name="entry_list", description="List phrase trigger entries")
    async def frasi_entry_list(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction, "frasi.list")
        if scope is None:
            return
        guild_id, _ = scope
        rows = await ctx.database.list_trigger_phrases_guild(guild_id)
        if not rows:
            await interaction.response.send_message("No phrase entries configured.", ephemeral=True)
            return
        await interaction.response.send_message("\n".join(_format_phrase_row(row) for row in rows), ephemeral=True)

    @frasi_group.command(name="entry_show", description="Show a phrase trigger entry")
    @app_commands.describe(id="Phrase entry ID")
    async def frasi_entry_show(interaction: discord.Interaction, id: int) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        guild_id, _ = scope
        row = await ctx.database.get_trigger_phrase_by_id(guild_id, id)
        if not row:
            await interaction.response.send_message(f"Phrase entry #{id} not found.", ephemeral=True)
            return
        summary = await ctx.database.get_trigger_phrase_stats_summary(guild_id, id)
        await interaction.response.send_message(
            "\n".join(
                [
                    _format_phrase_row(dict(row)),
                    f"Last activity: {_humanize_ts(summary.get('last_seen_ts_max') or row.get('last_seen_ts'))}",
                    f"Total uses: {int(summary.get('total_uses') or 0)}",
                    f"Unique users: {int(summary.get('unique_users') or 0)}",
                ]
            ),
            ephemeral=True,
        )

    @frasi_group.command(name="entry_edit", description="Edit a phrase trigger entry")
    @app_commands.describe(
        id="Phrase entry ID",
        phrase="Updated trigger phrase",
        match_mode="Phrase match mode",
        color="Updated embed color (#RRGGBB)",
        cooldown_seconds="Updated cooldown in seconds",
        role_ids="Updated allowed roles as mentions or IDs",
        reset_role_ids="Remove the role allowlist",
        reset_cooldown="Remove the cooldown",
        reset_color="Remove the custom color",
        enabled="Enable or disable this phrase entry",
    )
    @app_commands.choices(match_mode=MATCH_MODE_CHOICES)
    async def frasi_entry_edit(
        interaction: discord.Interaction,
        id: int,
        phrase: str | None = None,
        match_mode: app_commands.Choice[str] | None = None,
        color: str | None = None,
        cooldown_seconds: int | None = None,
        role_ids: str | None = None,
        reset_role_ids: bool = False,
        reset_cooldown: bool = False,
        reset_color: bool = False,
        enabled: bool | None = None,
    ) -> None:
        scope = await _require_channel(interaction, "frasi.edit")
        if scope is None:
            return
        guild_id, _ = scope
        row = await ctx.database.get_trigger_phrase_by_id(guild_id, id)
        if not row:
            await interaction.response.send_message(f"Phrase entry #{id} not found.", ephemeral=True)
            return
        if reset_role_ids and role_ids:
            await interaction.response.send_message("Use either role_ids or reset_role_ids, not both.", ephemeral=True)
            return
        if reset_cooldown and cooldown_seconds is not None:
            await interaction.response.send_message("Use either cooldown_seconds or reset_cooldown, not both.", ephemeral=True)
            return
        if reset_color and color is not None:
            await interaction.response.send_message("Use either color or reset_color, not both.", ephemeral=True)
            return
        if cooldown_seconds is not None and cooldown_seconds <= 0:
            await interaction.response.send_message("cooldown_seconds must be a positive integer.", ephemeral=True)
            return

        parsed_color: str | None = None
        if color is not None:
            parsed_color = _normalize_embed_color(color)
            if parsed_color is None:
                await interaction.response.send_message("Invalid color. Use #RRGGBB, RRGGBB, 0xRRGGBB, or a decimal value.", ephemeral=True)
                return

        parsed_role_ids: list[str] | None = None
        if role_ids is not None:
            parsed_role_ids = _parse_role_ids_input(role_ids)
            if interaction.guild is None:
                await interaction.response.send_message("Cannot validate roles without guild context.", ephemeral=True)
                return
            invalid_ids = [role_id for role_id in parsed_role_ids if interaction.guild.get_role(int(role_id)) is None]
            if invalid_ids:
                await interaction.response.send_message(f"Invalid roles for this server: {', '.join(invalid_ids)}", ephemeral=True)
                return

        updated = await ctx.database.update_trigger_phrase(
            guild_id,
            id,
            phrase=phrase,
            match_mode=match_mode.value if match_mode is not None else None,
            embed_color=parsed_color if color is not None else None,
            set_embed_color=color is not None or reset_color,
            cooldown_seconds=cooldown_seconds,
            set_cooldown_seconds=cooldown_seconds is not None or reset_cooldown,
            allowed_role_ids=parsed_role_ids,
            set_allowed_role_ids=role_ids is not None or reset_role_ids,
            enabled=enabled,
        )
        if not updated:
            await interaction.response.send_message("No changes requested.", ephemeral=True)
            return
        row_after = await ctx.database.get_trigger_phrase_by_id(guild_id, id)
        await interaction.response.send_message(f"Updated phrase entry #{id}.\n{_format_phrase_row(row_after)}", ephemeral=True)

    @frasi_group.command(name="template_milestone_set", description="Create or update a milestone template")
    @app_commands.describe(threshold="Milestone threshold", text="Milestone template text")
    async def frasi_template_milestone_set(interaction: discord.Interaction, threshold: int, text: str) -> None:
        scope = await _require_channel(interaction, "frasi.milestone_global_set")
        if scope is None:
            return
        guild_id, _ = scope
        if threshold < 2:
            await interaction.response.send_message("threshold must be greater than or equal to 2.", ephemeral=True)
            return
        cleaned_text = text.strip()
        if not cleaned_text:
            await interaction.response.send_message("text cannot be empty.", ephemeral=True)
            return
        await ctx.database.set_trigger_phrase_global_milestones_enabled(guild_id, True)
        await ctx.database.set_trigger_phrase_global_milestone(guild_id, threshold, cleaned_text)
        await interaction.response.send_message(f"Milestone template saved for threshold {threshold}.", ephemeral=True)

    @frasi_group.command(name="template_milestone_show", description="Show milestone templates")
    async def frasi_template_milestone_show(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction, "frasi.milestone_global_list", "frasi.milestone_global_status")
        if scope is None:
            return
        guild_id, _ = scope
        enabled = await ctx.database.get_trigger_phrase_global_milestones_enabled(guild_id)
        milestones = await ctx.database.list_trigger_phrase_global_milestones(guild_id)
        if not milestones:
            await interaction.response.send_message(f"Milestone templates are {'enabled' if enabled else 'disabled'}. No templates configured.", ephemeral=True)
            return
        lines = [f"Milestone templates are {'enabled' if enabled else 'disabled'}."]
        lines.extend(f"{int(m['threshold_count'])} -> {str(m['template_text'])}" for m in milestones)
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @frasi_group.command(name="template_milestone_reset", description="Reset all milestone templates")
    async def frasi_template_milestone_reset(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction, "frasi.milestone_global_remove")
        if scope is None:
            return
        guild_id, _ = scope
        milestones = await ctx.database.list_trigger_phrase_global_milestones(guild_id)
        for milestone in milestones:
            await ctx.database.delete_trigger_phrase_global_milestone(guild_id, int(milestone["threshold_count"]))
        await ctx.database.set_trigger_phrase_global_milestones_enabled(guild_id, False)
        await interaction.response.send_message(f"Reset {len(milestones)} milestone templates.", ephemeral=True)

    @frasi_group.command(name="template_global_set", description="Set the global phrase template")
    @app_commands.describe(text="Template text")
    async def frasi_template_global_set(interaction: discord.Interaction, text: str) -> None:
        scope = await _require_channel(interaction, "frasi.template_set")
        if scope is None:
            return
        guild_id, _ = scope
        state = await ctx.database.get_trigger_state_any_channel(guild_id, "frasi")
        normalized = _normalize_phrase_templates_state(state)
        templates = dict(normalized.get("templates") or {})
        templates["DEFAULT"] = text
        normalized["templates"] = templates
        await ctx.database.set_trigger_state_global(guild_id, "frasi", normalized)
        await interaction.response.send_message("Global phrase template updated.", ephemeral=True)

    @frasi_group.command(name="template_global_show", description="Show the global phrase template")
    async def frasi_template_global_show(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction, "frasi.template_show")
        if scope is None:
            return
        guild_id, _ = scope
        state = await ctx.database.get_trigger_state_any_channel(guild_id, "frasi")
        normalized = _normalize_phrase_templates_state(state)
        templates = dict(normalized.get("templates") or {})
        default_template = templates.get("DEFAULT") or "-"
        first_template = templates.get("FIRST") or "-"
        await interaction.response.send_message(
            f"DEFAULT: {default_template}\nFIRST: {first_template}",
            ephemeral=True,
        )

    @frasi_group.command(name="template_global_reset", description="Reset the global phrase template")
    async def frasi_template_global_reset(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction, "frasi.template_reset")
        if scope is None:
            return
        guild_id, _ = scope
        state = await ctx.database.get_trigger_state_any_channel(guild_id, "frasi")
        normalized = _normalize_phrase_templates_state(state)
        templates = dict(normalized.get("templates") or {})
        templates.pop("DEFAULT", None)
        if templates:
            normalized["templates"] = templates
        else:
            normalized.pop("templates", None)
        await ctx.database.set_trigger_state_global(guild_id, "frasi", normalized)
        await interaction.response.send_message("Global phrase template reset.", ephemeral=True)

    @frasi_group.command(name="template_user_set", description="Set a user-specific phrase template")
    @app_commands.describe(user="Target user", text="Template text")
    async def frasi_template_user_set(interaction: discord.Interaction, user: discord.Member, text: str) -> None:
        scope = await _require_channel(interaction, "frasi.userphrase_set")
        if scope is None:
            return
        guild_id, _ = scope
        cleaned_text = text.strip()
        if not cleaned_text:
            await interaction.response.send_message("text cannot be empty.", ephemeral=True)
            return
        if len(cleaned_text) > 300:
            await interaction.response.send_message("text is too long (max 300 characters).", ephemeral=True)
            return
        await ctx.database.upsert_trigger_phrase_global_user_custom_text(guild_id, str(user.id), cleaned_text)
        await interaction.response.send_message(f"User phrase template updated for {user.mention}.", ephemeral=True)

    @frasi_group.command(name="template_user_show", description="Show a user-specific phrase template")
    @app_commands.describe(user="Target user")
    async def frasi_template_user_show(interaction: discord.Interaction, user: discord.Member) -> None:
        scope = await _require_channel(interaction, "frasi.userphrase_show")
        if scope is None:
            return
        guild_id, _ = scope
        text = await ctx.database.get_trigger_phrase_global_user_custom_text(guild_id, str(user.id))
        if not text:
            await interaction.response.send_message(f"No user phrase template found for {user.mention}.", ephemeral=True)
            return
        await interaction.response.send_message(f"{user.mention} -> {text}", ephemeral=True)

    @frasi_group.command(name="template_user_reset", description="Reset a user-specific phrase template")
    @app_commands.describe(user="Target user")
    async def frasi_template_user_reset(interaction: discord.Interaction, user: discord.Member) -> None:
        scope = await _require_channel(interaction, "frasi.userphrase_remove")
        if scope is None:
            return
        guild_id, _ = scope
        removed = await ctx.database.delete_trigger_phrase_global_user_custom_text(guild_id, str(user.id))
        if not removed:
            await interaction.response.send_message(f"No user phrase template found for {user.mention}.", ephemeral=True)
            return
        await interaction.response.send_message(f"User phrase template reset for {user.mention}.", ephemeral=True)
    @prompt_group.command(name="on", description="Enable prompt campaigns in the current channel")
    async def prompt_on(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        rows = await ctx.database.list_message_campaigns(guild_id, include_disabled=True)
        prompt_rows = [dict(row) for row in rows if str(row["type"]) == "AI_PROMPT" and str(row["channel_id"]) == channel_id]
        for row in prompt_rows:
            await ctx.database.set_message_campaign_enabled(guild_id, int(row["id"]), True)
        await interaction.response.send_message(f"Prompt campaigns enabled in this channel. Updated {len(prompt_rows)} entries.", ephemeral=True)

    @prompt_group.command(name="off", description="Disable prompt campaigns in the current channel")
    async def prompt_off(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        rows = await ctx.database.list_message_campaigns(guild_id, include_disabled=True)
        prompt_rows = [dict(row) for row in rows if str(row["type"]) == "AI_PROMPT" and str(row["channel_id"]) == channel_id]
        for row in prompt_rows:
            await ctx.database.set_message_campaign_enabled(guild_id, int(row["id"]), False)
        await interaction.response.send_message(f"Prompt campaigns disabled in this channel. Updated {len(prompt_rows)} entries.", ephemeral=True)

    @prompt_group.command(name="status", description="Show prompt campaign status for the current channel")
    async def prompt_status(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        rows = await ctx.database.list_message_campaigns(guild_id, include_disabled=True)
        prompt_rows = [dict(row) for row in rows if str(row["type"]) == "AI_PROMPT" and str(row["channel_id"]) == channel_id]
        enabled_count = sum(1 for row in prompt_rows if bool(row.get("enabled")))
        await interaction.response.send_message(f"Prompt campaigns in this channel: {enabled_count}/{len(prompt_rows)} enabled.", ephemeral=True)

    @prompt_group.command(name="entry_add", description="Add a prompt campaign entry")
    @app_commands.describe(
        text="Prompt text",
        name="Optional campaign name",
        publish_at="First publication time (DD/MM/YYYY HH:MM)",
        every="Repeat interval in minutes",
        embed_title="Optional embed title",
        embed_color="Optional embed color",
    )
    async def prompt_entry_add(
        interaction: discord.Interaction,
        text: str,
        name: str | None = None,
        publish_at: str | None = None,
        every: int | None = None,
        embed_title: str | None = None,
        embed_color: str | None = None,
    ) -> None:
        if not await _guard(interaction, "campagne.prompt.create"):
            return
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("Use this command in a guild channel.", ephemeral=True)
            return
        if ctx.message_scheduler is not None and not ctx.message_scheduler.is_valid_embed_color(embed_color):
            await interaction.response.send_message("Invalid embed_color. Use #RRGGBB, RRGGBB, or 0xRRGGBB.", ephemeral=True)
            return
        now_utc = datetime.now(timezone.utc)
        now_local = now_utc.astimezone(ctx.timezone)
        resolved_name = (name or "").strip() or f"prompt-{now_local.strftime('%Y%m%d-%H%M')}"
        resolved_interval = int(every or 0)
        if resolved_interval < 0:
            await interaction.response.send_message("every must be greater than or equal to 0.", ephemeral=True)
            return
        publish_at_raw = (publish_at or "").strip()
        publish_at_dt = parse_italian_datetime(publish_at_raw) if publish_at_raw else None
        if publish_at_raw and publish_at_dt is None:
            await interaction.response.send_message("Invalid publish_at format. Use DD/MM/YYYY HH:MM.", ephemeral=True)
            return
        if publish_at_dt is not None:
            next_run = publish_at_dt.astimezone(timezone.utc)
            resolved_time_local = publish_at_dt.astimezone(ctx.timezone).strftime("%H:%M")
        else:
            next_run = now_utc
            resolved_time_local = now_local.strftime("%H:%M")
        campaign_id = await ctx.database.create_message_campaign(
            guild_id=str(interaction.guild_id),
            channel_id=str(interaction.channel_id),
            campaign_type="AI_PROMPT",
            name=resolved_name,
            text=text,
            text_green=None,
            text_yellow=None,
            text_red=None,
            text_black=None,
            enabled=True,
            start_time_local=resolved_time_local,
            interval_minutes=resolved_interval,
            jitter_seconds=0,
            only_if_idle_minutes=0,
            mood_mode="IGNORE_BARCELLO",
            next_run_at=next_run.isoformat(),
            created_by=str(interaction.user.id),
            embed_title=embed_title,
            embed_color=embed_color,
        )
        await interaction.response.send_message(f"Prompt campaign {campaign_id} created.", ephemeral=True)

    @prompt_group.command(name="entry_list", description="List prompt campaign entries")
    async def prompt_entry_list(interaction: discord.Interaction) -> None:
        if not await _guard(interaction, "campagne.prompt.list"):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("Use this command in a guild.", ephemeral=True)
            return
        rows = await ctx.database.list_message_campaigns(str(interaction.guild_id), include_disabled=True)
        prompt_rows = [dict(row) for row in rows if str(row["type"]) == "AI_PROMPT"]
        if not prompt_rows:
            await interaction.response.send_message("No prompt campaigns configured.", ephemeral=True)
            return
        await interaction.response.send_message(
            "\n".join(
                f"ID {row['id']} {'on' if row['enabled'] else 'off'} {row['name'] or '-'} ch={row['channel_id'] or '-'} next={row['next_run_at'] or '-'} every={'one-shot' if int(row['interval_minutes']) <= 0 else str(row['interval_minutes']) + 'm'}"
                for row in prompt_rows
            ),
            ephemeral=True,
        )

    @prompt_group.command(name="entry_show", description="Show a prompt campaign entry")
    @app_commands.describe(id="Prompt campaign ID")
    async def prompt_entry_show(interaction: discord.Interaction, id: int) -> None:
        if not await _guard(interaction):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("Use this command in a guild.", ephemeral=True)
            return
        row = await ctx.database.get_message_campaign(str(interaction.guild_id), id)
        if not row or str(row["type"]) != "AI_PROMPT":
            await interaction.response.send_message("Prompt campaign not found.", ephemeral=True)
            return
        payload = dict(row)
        await interaction.response.send_message(
            "\n".join(
                [
                    f"ID {payload['id']}",
                    f"name={payload['name'] or '-'}",
                    f"enabled={'on' if payload['enabled'] else 'off'}",
                    f"channel={payload['channel_id']}",
                    f"publish_at={payload['start_time_local']}",
                    f"every={payload['interval_minutes']}",
                    f"next={payload['next_run_at']}",
                    f"embed_title={payload['embed_title'] or '-'}",
                    f"embed_color={payload['embed_color'] or '-'}",
                    f"text={payload['text'] or '-'}",
                ]
            ),
            ephemeral=True,
        )

    @prompt_group.command(name="entry_remove", description="Remove a prompt campaign entry")
    @app_commands.describe(id="Prompt campaign ID")
    async def prompt_entry_remove(interaction: discord.Interaction, id: int) -> None:
        if not await _guard(interaction, "campagne.prompt.delete"):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("Use this command in a guild.", ephemeral=True)
            return
        row = await ctx.database.get_message_campaign(str(interaction.guild_id), id)
        if not row or str(row["type"]) != "AI_PROMPT":
            await interaction.response.send_message("Prompt campaign not found.", ephemeral=True)
            return
        await ctx.database.soft_delete_message_campaign(str(interaction.guild_id), id)
        await interaction.response.send_message("Prompt campaign removed.", ephemeral=True)

    @prompt_group.command(name="entry_run", description="Run a prompt campaign entry now")
    @app_commands.describe(id="Prompt campaign ID")
    async def prompt_entry_run(interaction: discord.Interaction, id: int) -> None:
        if not await _guard(interaction, "campagne.prompt.test"):
            return
        if interaction.guild_id is None or interaction.channel is None or interaction.channel_id is None:
            await interaction.response.send_message("Use this command in a guild channel.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        campaign = await ctx.database.get_message_campaign(str(interaction.guild_id), id)
        if not campaign or str(campaign["type"]) != "AI_PROMPT":
            await interaction.followup.send("Prompt campaign not found.", ephemeral=True)
            return
        if ctx.message_scheduler is None:
            await interaction.followup.send("Scheduler service unavailable.", ephemeral=True)
            return
        rendered_text, reason, debug_payload = await ctx.message_scheduler.preview_campaign_text(
            dict(campaign),
            channel_id_override=str(interaction.channel_id),
        )
        logger.info(
            "prompt_entry_run campaign_id=%s user=%s channel=%s ai_called=%s reason=%s",
            id,
            interaction.user.id,
            interaction.channel_id,
            "yes" if debug_payload.get("selected_source") == "ai" else "no",
            reason,
        )
        if not rendered_text:
            await interaction.followup.send(f"Unable to generate output ({reason or 'no_text'}).", ephemeral=True)
            return
        await interaction.followup.send("Prompt campaign sent.", ephemeral=True)
        if isinstance(interaction.channel, discord.abc.Messageable):
            await ctx.message_scheduler.send_campaign_embed(interaction.channel, dict(campaign), rendered_text)

    @prompt_group.command(name="entry_edit", description="Edit a prompt campaign entry")
    @app_commands.describe(
        id="Prompt campaign ID",
        text="Updated prompt text",
        name="Updated campaign name",
        publish_at="First publication time (DD/MM/YYYY HH:MM)",
        every="Repeat interval in minutes",
        embed_title="Updated embed title",
        embed_color="Updated embed color",
        enabled="Enable or disable this entry",
    )
    async def prompt_entry_edit(
        interaction: discord.Interaction,
        id: int,
        text: str | None = None,
        name: str | None = None,
        publish_at: str | None = None,
        every: int | None = None,
        embed_title: str | None = None,
        embed_color: str | None = None,
        enabled: bool | None = None,
    ) -> None:
        if not await _guard(interaction, "campagne.prompt.create"):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("Use this command in a guild.", ephemeral=True)
            return
        campaign = await ctx.database.get_message_campaign(str(interaction.guild_id), id)
        if not campaign or str(campaign["type"]) != "AI_PROMPT":
            await interaction.response.send_message("Prompt campaign not found.", ephemeral=True)
            return
        if ctx.message_scheduler is not None and not ctx.message_scheduler.is_valid_embed_color(embed_color):
            await interaction.response.send_message("Invalid embed_color. Use #RRGGBB, RRGGBB, or 0xRRGGBB.", ephemeral=True)
            return
        start_time_local = None
        interval_minutes = None
        next_run_at = None
        if publish_at is not None or every is not None:
            current_interval = every if every is not None else int(campaign["interval_minutes"])
            publish_at_raw = (publish_at or "").strip()
            if publish_at_raw:
                publish_at_dt = parse_italian_datetime(publish_at_raw)
                if publish_at_dt is None:
                    await interaction.response.send_message("Invalid publish_at format. Use DD/MM/YYYY HH:MM.", ephemeral=True)
                    return
                start_time_local = publish_at_dt.astimezone(ctx.timezone).strftime("%H:%M")
                next_run_at = publish_at_dt.astimezone(timezone.utc).isoformat()
            else:
                now = datetime.now(timezone.utc)
                start_time_local = str(campaign["start_time_local"])
                next_run = now if current_interval <= 0 else now
                next_run_at = next_run.isoformat()
            interval_minutes = current_interval
        updated = await ctx.database.update_message_campaign(
            str(interaction.guild_id),
            id,
            name=name,
            text=text,
            start_time_local=start_time_local,
            interval_minutes=interval_minutes,
            next_run_at=next_run_at,
            embed_title=embed_title,
            embed_color=embed_color,
            set_name=name is not None,
            set_text=text is not None,
            set_start_time_local=start_time_local is not None,
            set_interval_minutes=interval_minutes is not None,
            set_next_run_at=next_run_at is not None,
            set_embed_title=embed_title is not None,
            set_embed_color=embed_color is not None,
        )
        if enabled is not None:
            await ctx.database.set_message_campaign_enabled(str(interaction.guild_id), id, enabled)
        if not updated and enabled is None:
            await interaction.response.send_message("No changes requested.", ephemeral=True)
            return
        await interaction.response.send_message(f"Prompt campaign {id} updated.", ephemeral=True)

    @qna_group.command(name="on", description="Enable QnA in the current channel")
    async def qna_on(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "qna", "on")

    @qna_group.command(name="off", description="Disable QnA in the current channel")
    async def qna_off(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "qna", "off")

    @qna_group.command(name="status", description="Show QnA status for the current channel")
    async def qna_status(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "qna", "status")

    @qna_group.command(name="limits_show", description="Show QnA daily limits")
    @app_commands.describe(tier="Optional QnA tier filter")
    @app_commands.choices(tier=TIER_CHOICES)
    async def qna_limits_show(interaction: discord.Interaction, tier: app_commands.Choice[str] | None = None) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        raw = await ctx.database.get_setting("qna.daily_limits")
        defaults = {"base": 0, "role1": 1, "role2": 2, "role3": 3, "mod": 999}
        if not raw:
            data = defaults
        else:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = defaults
            data = parsed if isinstance(parsed, dict) else defaults
        if tier is not None:
            value = int(data.get(tier.value, defaults[tier.value]))
            await interaction.response.send_message(f"{tier.value}={value}", ephemeral=True)
            return
        pretty = json.dumps(data, ensure_ascii=False, indent=2)
        await interaction.response.send_message(f"```json\n{pretty}\n```", ephemeral=True)

    @qna_group.command(name="limits_set", description="Set a QnA daily limit")
    @app_commands.describe(tier="QnA tier", limit="Daily question limit")
    @app_commands.choices(tier=TIER_CHOICES)
    async def qna_limits_set(interaction: discord.Interaction, tier: app_commands.Choice[str], limit: int) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        if limit < 0 or limit > 999:
            await interaction.response.send_message("limit must be between 0 and 999.", ephemeral=True)
            return
        raw = await ctx.database.get_setting("qna.daily_limits")
        data = {"base": 0, "role1": 1, "role2": 2, "role3": 3, "mod": 999}
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                data.update(parsed)
        data[tier.value] = int(limit)
        await ctx.database.set_setting("qna.daily_limits", json.dumps(data, ensure_ascii=False))
        await interaction.response.send_message(f"QnA limit updated: {tier.value}={limit}.", ephemeral=True)

    @qna_group.command(name="limits_reset", description="Reset QnA daily limits to defaults")
    async def qna_limits_reset(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        defaults = {"base": 0, "role1": 1, "role2": 2, "role3": 3, "mod": 999}
        await ctx.database.set_setting("qna.daily_limits", json.dumps(defaults, ensure_ascii=False))
        await interaction.response.send_message("QnA daily limits reset to defaults.", ephemeral=True)

    @qna_group.command(name="bonus_set", description="Set a QnA bonus for a user")
    @app_commands.describe(user="Target user", amount="Bonus amount", hours_valid="Optional validity in hours")
    async def qna_bonus_set(interaction: discord.Interaction, user: discord.Member, amount: int, hours_valid: int | None = None) -> None:
        if not await _guard(interaction, "qna.bonus_add"):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("Use this command in a guild.", ephemeral=True)
            return
        if amount < 0 or amount > 999:
            await interaction.response.send_message("amount must be between 0 and 999.", ephemeral=True)
            return
        expires_at = None
        if hours_valid is not None:
            if hours_valid <= 0 or hours_valid > 24 * 30:
                await interaction.response.send_message("hours_valid must be between 1 and 720.", ephemeral=True)
                return
            expires_at = (datetime.now(timezone.utc) + timedelta(hours=hours_valid)).isoformat()
        await ctx.database.set_qna_bonus(str(interaction.guild_id), str(user.id), int(amount), expires_at)
        await interaction.response.send_message(
            f"QnA bonus set for {user.mention}: {amount}" + (f" until {expires_at}" if expires_at else ""),
            ephemeral=True,
        )

    @qna_group.command(name="bonus_show", description="Show a user's QnA bonus")
    @app_commands.describe(user="Target user")
    async def qna_bonus_show(interaction: discord.Interaction, user: discord.Member) -> None:
        if not await _guard(interaction):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("Use this command in a guild.", ephemeral=True)
            return
        bonus, expires_at = await ctx.database.get_qna_bonus(str(interaction.guild_id), str(user.id))
        await interaction.response.send_message(f"QnA bonus for {user.mention}: {bonus}\nExpires: {expires_at or '-'}", ephemeral=True)

    @qna_group.command(name="bonus_reset", description="Reset a user's QnA bonus")
    @app_commands.describe(user="Target user")
    async def qna_bonus_reset(interaction: discord.Interaction, user: discord.Member) -> None:
        if not await _guard(interaction, "qna.bonus_clear"):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("Use this command in a guild.", ephemeral=True)
            return
        await ctx.database.clear_qna_bonus(str(interaction.guild_id), str(user.id))
        await interaction.response.send_message(f"QnA bonus reset for {user.mention}.", ephemeral=True)

    @insights_group.command(name="on", description="Enable insights in the current channel")
    async def insights_on(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "insights", "on")

    @insights_group.command(name="off", description="Disable insights in the current channel")
    async def insights_off(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "insights", "off")

    @insights_group.command(name="status", description="Show insights status for the current channel")
    async def insights_status(interaction: discord.Interaction) -> None:
        if not await _guard(interaction):
            return
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("Use this command in a guild channel.", ephemeral=True)
            return
        if ctx.trigger_engine is None:
            await interaction.response.send_message("Trigger engine unavailable.", ephemeral=True)
            return
        status = await ctx.trigger_engine.get_insights_status(str(interaction.guild_id), str(interaction.channel_id))
        await interaction.response.send_message(
            "\n".join(
                [
                    f"Insights: {'on' if status['enabled'] else 'off'}",
                    f"Interval: {status['interval_minutes']} min",
                    f"Template: {str(status['template'])[:140]}",
                    f"Last post: {status['last_post_at'] or '-'}",
                ]
            ),
            ephemeral=True,
        )

    @insights_group.command(name="template_set", description="Set the insights template")
    @app_commands.describe(text="Template text or natural-language config prompt")
    async def insights_template_set(interaction: discord.Interaction, text: str) -> None:
        if not await _guard(interaction, "insights.config"):
            return
        if ctx.trigger_engine is None:
            await interaction.response.send_message("Trigger engine unavailable.", ephemeral=True)
            return
        config = await ctx.trigger_engine.configure_insights(text)
        await interaction.response.send_message(
            f"Insights template saved. Interval: {config['interval_minutes']} min. Template: {config['template'][:120]}",
            ephemeral=True,
        )

    @insights_group.command(name="template_show", description="Show the insights template")
    async def insights_template_show(interaction: discord.Interaction) -> None:
        if not await _guard(interaction):
            return
        if ctx.trigger_engine is None:
            await interaction.response.send_message("Trigger engine unavailable.", ephemeral=True)
            return
        raw = await ctx.database.get_setting("community_insights.config")
        config = await ctx.trigger_engine._community_insights.get_config(raw)
        pretty = json.dumps(config, ensure_ascii=False, indent=2)
        await interaction.response.send_message(f"```json\n{pretty}\n```", ephemeral=True)

    @insights_group.command(name="template_reset", description="Reset the insights template to defaults")
    async def insights_template_reset(interaction: discord.Interaction) -> None:
        if not await _guard(interaction, "insights.config"):
            return
        await ctx.database.set_setting("community_insights.config", "{}")
        await interaction.response.send_message("Insights template reset to defaults.", ephemeral=True)

    return frasi_group
