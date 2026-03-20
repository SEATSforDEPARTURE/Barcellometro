from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import discord
from discord import app_commands

from app.plugins.commands_modular.placeholders import describe_placeholders
from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.shared.discord.command_embeds import CommandEmbedSection, CommandKind, build_command_embeds, send_command_embeds, send_standard_response

PERM = "inactivity"
DEFAULT_GRACE_DAYS = 7
DEFAULT_REMINDER_COOLDOWN_DAYS = 14
DEFAULT_TEMPBAN_DAYS = 7
DEFAULT_POLICY_JSON = '{"inactive_days":30,"window_days":30,"min_messages":1,"mode":"OR","min_account_age_days":0}'
TEMPLATE_HELP = f"Supported placeholders: {describe_placeholders()} Example: {{display_name}}, {{days_inactive}}."


def _normalize_mode(mode: str) -> str:
    normalized = mode.upper().strip()
    if normalized not in {"OR", "AND"}:
        raise ValueError("mode must be OR or AND")
    return normalized


def _policy_payload(inactive_days: int, window_days: int, min_messages: int, mode: str, min_account_age_days: int) -> str:
    return json.dumps(
        {
            "inactive_days": int(inactive_days),
            "window_days": int(window_days),
            "min_messages": int(min_messages),
            "mode": _normalize_mode(mode),
            "min_account_age_days": int(min_account_age_days),
        }
    )


async def _ensure_cfg(ctx: CommandContext, guild_id: str) -> dict[str, object]:
    if await ctx.database.get_inactivity_config(guild_id) is None:
        await ctx.database.upsert_inactivity_config(guild_id)
    row = await ctx.database.get_inactivity_config(guild_id)
    return dict(row) if row else {}


def _policy_dict(raw: str | None) -> dict[str, object]:
    if not raw:
        return json.loads(DEFAULT_POLICY_JSON)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(DEFAULT_POLICY_JSON)
    if not isinstance(data, dict):
        return json.loads(DEFAULT_POLICY_JSON)
    return data


def _bool_label(value: object) -> str:
    return "on" if bool(value) else "off"


def _status_label_from_days(days: int) -> str:
    return "on" if days > 0 else "off"


def _role_exception_ids(cfg: dict[str, object]) -> list[str]:
    try:
        raw = json.loads(str(cfg.get("excluded_role_ids_json") or "[]"))
    except json.JSONDecodeError:
        return []
    return [str(item) for item in raw]


def _role_mentions(guild: discord.Guild, role_ids: list[str]) -> list[str]:
    mentions: list[str] = []
    for role_id in role_ids:
        role = guild.get_role(int(role_id)) if role_id.isdigit() else None
        mentions.append(role.mention if role else f"`{role_id}`")
    return mentions


def _policy_summary(policy: dict[str, object]) -> str:
    return (
        f"inactive_days={policy.get('inactive_days', 30)}, "
        f"window_days={policy.get('window_days', 30)}, "
        f"min_messages={policy.get('min_messages', 1)}, "
        f"mode={policy.get('mode', 'OR')}, "
        f"min_account_age_days={policy.get('min_account_age_days', 0)}"
    )


def _render_template_preview(template: str) -> str:
    sample = {
        "user": "@ExampleUser",
        "username": "ExampleUser",
        "display_name": "Example",
        "user_id": "1234567890",
        "server": "Barcellometro",
        "guild_id": "987654321",
        "days_inactive": 39,
        "window_days": 30,
        "min_messages": 1,
        "message_count": 0,
        "grace_days": 7,
        "reminder_count": 1,
        "ban_days": 7,
        "rejoin_link": "https://discord.gg/example",
        "reason": "Inactivity",
        "inactivity_text": "has been inactive for 39 days",
    }
    try:
        return template.format(**sample)
    except Exception as exc:  # noqa: BLE001
        return f"[Template render error: {exc}]\n{template}"


def register_inattivi(inactivity_group: app_commands.Group, ctx: CommandContext) -> None:
    autokick_group = app_commands.Group(name="autokick", description="Automatic inactivity enforcement")
    grace_group = app_commands.Group(name="grace", description="Grace period settings")
    tempban_group = app_commands.Group(name="tempban", description="Temporary ban settings")
    dms_group = app_commands.Group(name="dms", description="Direct message settings")
    policy_group = app_commands.Group(name="policy", description="Inactivity policy settings")
    inactivity_group.add_command(autokick_group)
    inactivity_group.add_command(grace_group)
    inactivity_group.add_command(tempban_group)
    inactivity_group.add_command(dms_group)
    inactivity_group.add_command(policy_group)

    async def _ensure(interaction: discord.Interaction) -> bool:
        return await check_permission(interaction, PERM, ctx)

    async def _send(
        interaction: discord.Interaction,
        *,
        subcommand_path: str,
        lines: list[tuple[str, object]] | None = None,
        sections: list[CommandEmbedSection] | None = None,
        kind: CommandKind = "info",
        files: list[discord.File] | None = None,
    ) -> None:
        await send_standard_response(
            interaction,
            top_level="admin",
            subcommand_path=subcommand_path,
            lines=lines,
            sections=sections,
            kind=kind,
            footer_service=ctx.footer,
            files=files,
        )

    async def _send_lines_with_txt(interaction: discord.Interaction, *, subcommand_path: str, title: str, lines: list[str], txt_prefix: str) -> None:
        payload = "\n".join(lines) if lines else "No results."
        txt_file = discord.File(
            io.BytesIO(payload.encode("utf-8")),
            filename=f"{txt_prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.txt",
        )
        embeds = await build_command_embeds(
            top_level="admin",
            subcommand_path=subcommand_path,
            lines=[("entries", len(lines))],
            sections=[CommandEmbedSection(title=title, lines=lines or ["No results."])],
            footer_service=ctx.footer,
        )
        await send_command_embeds(interaction, embeds=embeds, ephemeral=True, files=[txt_file])

    @inactivity_group.command(name="on", description="Enable inactivity moderation.")
    async def inactivity_on(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.set_inactivity_enabled(str(interaction.guild_id), True)
        await _send(interaction, subcommand_path="inattivi on", lines=[("result", "enabled")], kind="success")

    @inactivity_group.command(name="off", description="Disable inactivity moderation.")
    async def inactivity_off(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.set_inactivity_enabled(str(interaction.guild_id), False)
        await _send(interaction, subcommand_path="inattivi off", lines=[("result", "disabled")], kind="success")

    @inactivity_group.command(name="status", description="Show the inactivity moderation status.")
    async def inactivity_status(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None or interaction.guild is None:
            return
        cfg = await _ensure_cfg(ctx, str(interaction.guild_id))
        role_policies = await ctx.database.list_inactivity_role_policies(str(interaction.guild_id))
        exception_role_ids = _role_exception_ids(cfg)
        lines = [
            f"enabled={_bool_label(cfg.get('enabled'))}",
            f"autokick={_bool_label(cfg.get('auto_enabled'))}",
            f"grace={_status_label_from_days(int(cfg.get('grace_days_after_reminder', DEFAULT_GRACE_DAYS) or 0))} ({int(cfg.get('grace_days_after_reminder', DEFAULT_GRACE_DAYS) or 0)} days)",
            f"tempban={_status_label_from_days(int(cfg.get('ban_days', DEFAULT_TEMPBAN_DAYS) or 0))} ({int(cfg.get('ban_days', DEFAULT_TEMPBAN_DAYS) or 0)} days)",
            f"dm_cooldown={int(cfg.get('reminder_cooldown_days', DEFAULT_REMINDER_COOLDOWN_DAYS) or DEFAULT_REMINDER_COOLDOWN_DAYS)} days",
            f"invite_url={cfg.get('invite_url') or 'not set'}",
            f"role_policies={len(role_policies)}",
            f"exceptions={', '.join(_role_mentions(interaction.guild, exception_role_ids)) if exception_role_ids else 'none'}",
        ]
        await _send(
            interaction,
            subcommand_path="inattivi status",
            lines=[
                ("enabled", _bool_label(cfg.get("enabled"))),
                ("autokick", _bool_label(cfg.get("auto_enabled"))),
                ("grace", f"{_status_label_from_days(int(cfg.get('grace_days_after_reminder', DEFAULT_GRACE_DAYS) or 0))} ({int(cfg.get('grace_days_after_reminder', DEFAULT_GRACE_DAYS) or 0)} days)"),
                ("tempban", f"{_status_label_from_days(int(cfg.get('ban_days', DEFAULT_TEMPBAN_DAYS) or 0))} ({int(cfg.get('ban_days', DEFAULT_TEMPBAN_DAYS) or 0)} days)"),
                ("dm_cooldown", f"{int(cfg.get('reminder_cooldown_days', DEFAULT_REMINDER_COOLDOWN_DAYS) or DEFAULT_REMINDER_COOLDOWN_DAYS)} days"),
                ("invite_url", cfg.get("invite_url") or "not set"),
                ("role_policies", len(role_policies)),
                ("exceptions", ", ".join(_role_mentions(interaction.guild, exception_role_ids)) if exception_role_ids else "none"),
            ],
        )

    @autokick_group.command(name="on", description="Enable automatic inactivity actions.")
    async def inactivity_autokick_on(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.set_inactivity_auto_enabled(str(interaction.guild_id), True)
        await _send(interaction, subcommand_path="inattivi autokick on", lines=[("result", "enabled")], kind="success")

    @autokick_group.command(name="off", description="Disable automatic inactivity actions.")
    async def inactivity_autokick_off(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.set_inactivity_auto_enabled(str(interaction.guild_id), False)
        await _send(interaction, subcommand_path="inattivi autokick off", lines=[("result", "disabled")], kind="success")

    @autokick_group.command(name="status", description="Show the automatic inactivity action status.")
    async def inactivity_autokick_status(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await _ensure_cfg(ctx, str(interaction.guild_id))
        await _send(interaction, subcommand_path="inattivi autokick status", lines=[("autokick", _bool_label(cfg.get("auto_enabled")))])

    @grace_group.command(name="on", description="Enable the inactivity grace period.")
    async def inactivity_grace_on(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await _ensure_cfg(ctx, str(interaction.guild_id))
        days = int(cfg.get("grace_days_after_reminder", 0) or 0) or DEFAULT_GRACE_DAYS
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), grace_days_after_reminder=days)
        await _send(interaction, subcommand_path="inattivi grace on", lines=[("grace", "enabled"), ("days", days)], kind="success")

    @grace_group.command(name="off", description="Disable the inactivity grace period.")
    async def inactivity_grace_off(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), grace_days_after_reminder=0)
        await _send(interaction, subcommand_path="inattivi grace off", lines=[("grace", "disabled")], kind="success")

    @grace_group.command(name="status", description="Show the inactivity grace period status.")
    async def inactivity_grace_status(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await _ensure_cfg(ctx, str(interaction.guild_id))
        days = int(cfg.get("grace_days_after_reminder", DEFAULT_GRACE_DAYS) or 0)
        await _send(interaction, subcommand_path="inattivi grace status", lines=[("grace", _status_label_from_days(days)), ("days", days)])

    @grace_group.command(name="config_set", description="Set the inactivity grace period configuration.")
    @app_commands.describe(days="Number of grace days before enforcement.")
    async def inactivity_grace_config_set(interaction: discord.Interaction, days: app_commands.Range[int, 1, 365]) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), grace_days_after_reminder=int(days))
        await _send(interaction, subcommand_path="inattivi grace config_set", lines=[("days", int(days)), ("result", "updated")], kind="success")

    @grace_group.command(name="config_show", description="Show the inactivity grace period configuration.")
    async def inactivity_grace_config_show(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await _ensure_cfg(ctx, str(interaction.guild_id))
        days = int(cfg.get("grace_days_after_reminder", DEFAULT_GRACE_DAYS) or 0)
        await _send(interaction, subcommand_path="inattivi grace config_show", lines=[("days", days)])

    @grace_group.command(name="config_reset", description="Reset the inactivity grace period configuration.")
    async def inactivity_grace_config_reset(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), grace_days_after_reminder=DEFAULT_GRACE_DAYS)
        await _send(interaction, subcommand_path="inattivi grace config_reset", lines=[("days", DEFAULT_GRACE_DAYS), ("result", "reset")], kind="success")

    @tempban_group.command(name="on", description="Enable temporary bans after inactivity kicks.")
    async def inactivity_tempban_on(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await _ensure_cfg(ctx, str(interaction.guild_id))
        days = int(cfg.get("ban_days", 0) or 0) or DEFAULT_TEMPBAN_DAYS
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), ban_days=days)
        await _send(interaction, subcommand_path="inattivi tempban on", lines=[("tempban", "enabled"), ("days", days)], kind="success")

    @tempban_group.command(name="off", description="Disable temporary bans after inactivity kicks.")
    async def inactivity_tempban_off(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), ban_days=0)
        await _send(interaction, subcommand_path="inattivi tempban off", lines=[("tempban", "disabled")], kind="success")

    @tempban_group.command(name="status", description="Show the inactivity tempban status.")
    async def inactivity_tempban_status(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await _ensure_cfg(ctx, str(interaction.guild_id))
        days = int(cfg.get("ban_days", DEFAULT_TEMPBAN_DAYS) or 0)
        await _send(interaction, subcommand_path="inattivi tempban status", lines=[("tempban", _status_label_from_days(days)), ("days", days)])

    @tempban_group.command(name="config_set", description="Set the inactivity tempban configuration.")
    @app_commands.describe(days="Number of temporary ban days after an inactivity kick.")
    async def inactivity_tempban_config_set(interaction: discord.Interaction, days: app_commands.Range[int, 1, 365]) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), ban_days=int(days))
        await _send(interaction, subcommand_path="inattivi tempban config_set", lines=[("days", int(days)), ("result", "updated")], kind="success")

    @tempban_group.command(name="config_show", description="Show the inactivity tempban configuration.")
    async def inactivity_tempban_config_show(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await _ensure_cfg(ctx, str(interaction.guild_id))
        days = int(cfg.get("ban_days", DEFAULT_TEMPBAN_DAYS) or 0)
        await _send(interaction, subcommand_path="inattivi tempban config_show", lines=[("days", days)])

    @tempban_group.command(name="config_reset", description="Reset the inactivity tempban configuration.")
    async def inactivity_tempban_config_reset(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), ban_days=DEFAULT_TEMPBAN_DAYS)
        await _send(interaction, subcommand_path="inattivi tempban config_reset", lines=[("days", DEFAULT_TEMPBAN_DAYS), ("result", "reset")], kind="success")

    @dms_group.command(name="template_reminder_set", description="Set the reminder DM template.")
    @app_commands.describe(text=TEMPLATE_HELP)
    async def inactivity_dms_template_reminder_set(interaction: discord.Interaction, text: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), dm_reminder_template=text)
        await _send(interaction, subcommand_path="inattivi dms template_reminder_set", lines=[("result", "updated")], kind="success")

    @dms_group.command(name="template_reminder_show", description="Show the reminder DM template.")
    async def inactivity_dms_template_reminder_show(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await _ensure_cfg(ctx, str(interaction.guild_id))
        template = str(cfg.get("dm_reminder_template") or "")
        preview = _render_template_preview(template) if template else "No custom template configured."
        await _send(
            interaction,
            subcommand_path="inattivi dms template_reminder_show",
            lines=[("template", template or "not set")],
            sections=[CommandEmbedSection(title="Preview", lines=[preview])],
        )

    @dms_group.command(name="template_reminder_reset", description="Reset the reminder DM template.")
    async def inactivity_dms_template_reminder_reset(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), dm_reminder_template=None)
        await _send(interaction, subcommand_path="inattivi dms template_reminder_reset", lines=[("result", "reset")], kind="success")

    @dms_group.command(name="cooldown_set", description="Set the reminder DM cooldown.")
    @app_commands.describe(days="Number of days between reminder DMs.")
    async def inactivity_dms_cooldown_set(interaction: discord.Interaction, days: app_commands.Range[int, 1, 365]) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), reminder_cooldown_days=int(days))
        await _send(interaction, subcommand_path="inattivi dms cooldown_set", lines=[("days", int(days)), ("result", "updated")], kind="success")

    @dms_group.command(name="cooldown_show", description="Show the reminder DM cooldown.")
    async def inactivity_dms_cooldown_show(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await _ensure_cfg(ctx, str(interaction.guild_id))
        await _send(interaction, subcommand_path="inattivi dms cooldown_show", lines=[("days", int(cfg.get("reminder_cooldown_days", DEFAULT_REMINDER_COOLDOWN_DAYS) or DEFAULT_REMINDER_COOLDOWN_DAYS))])

    @dms_group.command(name="cooldown_reset", description="Reset the reminder DM cooldown.")
    async def inactivity_dms_cooldown_reset(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_inactivity_config(
            str(interaction.guild_id),
            reminder_cooldown_days=DEFAULT_REMINDER_COOLDOWN_DAYS,
        )
        await _send(interaction, subcommand_path="inattivi dms cooldown_reset", lines=[("days", DEFAULT_REMINDER_COOLDOWN_DAYS), ("result", "reset")], kind="success")

    @dms_group.command(name="invite_set", description="Set the invite link used in inactivity DMs.")
    @app_commands.describe(url="Invite URL sent to inactive members.")
    async def inactivity_dms_invite_set(interaction: discord.Interaction, url: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), invite_url=url)
        await _send(interaction, subcommand_path="inattivi dms invite_set", lines=[("invite_url", url), ("result", "updated")], kind="success")

    @dms_group.command(name="invite_show", description="Show the invite link used in inactivity DMs.")
    async def inactivity_dms_invite_show(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await _ensure_cfg(ctx, str(interaction.guild_id))
        await _send(interaction, subcommand_path="inattivi dms invite_show", lines=[("invite_url", cfg.get("invite_url") or "not set")])

    @dms_group.command(name="invite_reset", description="Reset the invite link used in inactivity DMs.")
    async def inactivity_dms_invite_reset(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), invite_url=None)
        await _send(interaction, subcommand_path="inattivi dms invite_reset", lines=[("result", "reset")], kind="success")

    @policy_group.command(name="default_set", description="Set the default inactivity policy.")
    @app_commands.describe(
        inactive_days="Days without activity before a member is considered inactive.",
        window_days="Message analysis window in days.",
        min_messages="Minimum messages required in the window.",
        mode="Policy mode: OR or AND.",
        min_account_age_days="Minimum account age in days.",
    )
    async def inactivity_policy_default_set(
        interaction: discord.Interaction,
        inactive_days: app_commands.Range[int, 1, 3650],
        window_days: app_commands.Range[int, 1, 3650],
        min_messages: app_commands.Range[int, 0, 100000],
        mode: str,
        min_account_age_days: app_commands.Range[int, 0, 3650] = 0,
    ) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        try:
            payload = _policy_payload(inactive_days, window_days, min_messages, mode, min_account_age_days)
        except ValueError as exc:
            await _send(interaction, subcommand_path="inattivi policy default_set", lines=[("error", str(exc))], kind="error")
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), default_policy_json=payload)
        await _send(interaction, subcommand_path="inattivi policy default_set", lines=[("policy", _policy_summary(_policy_dict(payload))), ("result", "updated")], kind="success")

    @policy_group.command(name="default_show", description="Show the default inactivity policy.")
    async def inactivity_policy_default_show(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await _ensure_cfg(ctx, str(interaction.guild_id))
        policy = _policy_dict(str(cfg.get("default_policy_json") or ""))
        await _send(interaction, subcommand_path="inattivi policy default_show", lines=[("policy", _policy_summary(policy))])

    @policy_group.command(name="default_reset", description="Reset the default inactivity policy.")
    async def inactivity_policy_default_reset(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), default_policy_json=DEFAULT_POLICY_JSON)
        await _send(interaction, subcommand_path="inattivi policy default_reset", lines=[("policy", _policy_summary(_policy_dict(DEFAULT_POLICY_JSON))), ("result", "reset")], kind="success")

    @policy_group.command(name="role_set", description="Set an inactivity policy for a role.")
    @app_commands.describe(
        role="Role that receives the custom inactivity policy.",
        inactive_days="Days without activity before a member is considered inactive.",
        window_days="Message analysis window in days.",
        min_messages="Minimum messages required in the window.",
        mode="Policy mode: OR or AND.",
        min_account_age_days="Minimum account age in days.",
        priority="Priority for this role policy.",
    )
    async def inactivity_policy_role_set(
        interaction: discord.Interaction,
        role: discord.Role,
        inactive_days: app_commands.Range[int, 1, 3650],
        window_days: app_commands.Range[int, 1, 3650],
        min_messages: app_commands.Range[int, 0, 100000],
        mode: str,
        min_account_age_days: app_commands.Range[int, 0, 3650] = 0,
        priority: int = 0,
    ) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        try:
            payload = _policy_payload(inactive_days, window_days, min_messages, mode, min_account_age_days)
        except ValueError as exc:
            await _send(interaction, subcommand_path="inattivi policy role_set", lines=[("error", str(exc))], kind="error")
            return
        await ctx.database.upsert_inactivity_role_policy(str(interaction.guild_id), str(role.id), payload, int(priority))
        await _send(interaction, subcommand_path="inattivi policy role_set", lines=[("role", role.mention), ("priority", int(priority)), ("policy", _policy_summary(_policy_dict(payload))), ("result", "updated")], kind="success")

    @policy_group.command(name="role_show", description="Show an inactivity policy for a role.")
    @app_commands.describe(role="Role to inspect.")
    async def inactivity_policy_role_show(interaction: discord.Interaction, role: discord.Role) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        rows = await ctx.database.list_inactivity_role_policies(str(interaction.guild_id))
        for row in rows:
            if str(row["role_id"]) == str(role.id):
                policy = _policy_dict(str(row["policy_json"] or ""))
                await _send(interaction, subcommand_path="inattivi policy role_show", lines=[("role", role.mention), ("priority", int(row["priority"])), ("policy", _policy_summary(policy))])
                return
        await _send(interaction, subcommand_path="inattivi policy role_show", lines=[("warning", "No inactivity role policy found.")], kind="warning")

    @policy_group.command(name="role_reset", description="Reset an inactivity policy for a role.")
    @app_commands.describe(role="Role to reset.")
    async def inactivity_policy_role_reset(interaction: discord.Interaction, role: discord.Role) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.delete_inactivity_role_policy(str(interaction.guild_id), str(role.id))
        await _send(interaction, subcommand_path="inattivi policy role_reset", lines=[("role", role.mention), ("result", "reset")], kind="success")

    @policy_group.command(name="exceptions_add", description="Add a role to the inactivity exception list.")
    @app_commands.describe(role="Role to exclude from inactivity moderation.")
    async def inactivity_policy_exceptions_add(interaction: discord.Interaction, role: discord.Role) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await _ensure_cfg(ctx, str(interaction.guild_id))
        current = set(_role_exception_ids(cfg))
        current.add(str(role.id))
        await ctx.database.upsert_inactivity_config(
            str(interaction.guild_id),
            excluded_role_ids_json=json.dumps(sorted(current)),
        )
        await _send(interaction, subcommand_path="inattivi policy exceptions_add", lines=[("role", role.mention), ("result", "added")], kind="success")

    @policy_group.command(name="exceptions_remove", description="Remove a role from the inactivity exception list.")
    @app_commands.describe(role="Role to remove from inactivity exceptions.")
    async def inactivity_policy_exceptions_remove(interaction: discord.Interaction, role: discord.Role) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await _ensure_cfg(ctx, str(interaction.guild_id))
        current = set(_role_exception_ids(cfg))
        current.discard(str(role.id))
        await ctx.database.upsert_inactivity_config(
            str(interaction.guild_id),
            excluded_role_ids_json=json.dumps(sorted(current)),
        )
        await _send(interaction, subcommand_path="inattivi policy exceptions_remove", lines=[("role", role.mention), ("result", "removed")], kind="success")

    @policy_group.command(name="exceptions_show", description="Show whether a role is excluded from inactivity moderation.")
    @app_commands.describe(role="Role to inspect.")
    async def inactivity_policy_exceptions_show(interaction: discord.Interaction, role: discord.Role) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await _ensure_cfg(ctx, str(interaction.guild_id))
        current = set(_role_exception_ids(cfg))
        status = "yes" if str(role.id) in current else "no"
        await _send(interaction, subcommand_path="inattivi policy exceptions_show", lines=[("role", role.mention), ("excluded", status)])

    @policy_group.command(name="exceptions_list", description="List all inactivity exception roles.")
    async def inactivity_policy_exceptions_list(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None or interaction.guild is None:
            return
        cfg = await _ensure_cfg(ctx, str(interaction.guild_id))
        role_ids = _role_exception_ids(cfg)
        lines = [f"• {mention}" for mention in _role_mentions(interaction.guild, role_ids)]
        await _send_lines_with_txt(
            interaction,
            subcommand_path="inattivi policy exceptions_list",
            title="Inactivity exception roles",
            lines=lines,
            txt_prefix="inactivity_exceptions",
        )

    @inactivity_group.command(name="run", description="Run the inactivity moderation scan now.")
    async def inactivity_run(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        if ctx.inactive_members_moderation is None:
            await _send(interaction, subcommand_path="inattivi run", lines=[("error", "Inactivity moderation service is not available.")], kind="error")
            return
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)
        await ctx.inactive_members_moderation.handle_post_activity_report(
            str(interaction.guild_id),
            str(interaction.channel_id),
        )
        await _send(interaction, subcommand_path="inattivi run", lines=[("result", "completed")], kind="success")
