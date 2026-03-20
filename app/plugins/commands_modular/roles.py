from __future__ import annotations

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import canonical_permission_key, check_permission
from app.shared.discord.command_embeds import CommandEmbedSection, send_standard_response


def _format_role_label(guild: discord.Guild | None, role_id: object) -> str:
    raw_role_id = str(role_id)
    if raw_role_id.isdigit() and guild is not None:
        role = guild.get_role(int(raw_role_id))
        if role is not None:
            return f"{role.mention} ({role.name})"
    return f"Deleted role (ID: {raw_role_id})"


def _format_user_label(guild: discord.Guild | None, user_id: object) -> str:
    raw_user_id = str(user_id)
    if raw_user_id.isdigit() and guild is not None:
        member = guild.get_member(int(raw_user_id))
        if member is not None:
            return f"{member.mention} ({member.display_name})"
    return f"Unknown user (ID: {raw_user_id})"


def _policy_line(command: str, usage_limit: int | None, cooldown_seconds: int | None) -> str:
    limit = usage_limit if usage_limit is not None else "∞"
    cooldown = cooldown_seconds if cooldown_seconds is not None else "∞"
    return f"limit={limit} cooldown={cooldown}"


def _canonical_policy_command(command: str) -> str:
    return canonical_permission_key(command)


def _policy_command_matches(row_command: str, command_filter: str) -> bool:
    return _canonical_policy_command(row_command) == _canonical_policy_command(command_filter)


async def _send_roles_response(
    interaction: discord.Interaction,
    ctx: CommandContext,
    *,
    subcommand_path: str,
    subtitle_args: list[object] | None = None,
    lines: list[tuple[str, object]] | None = None,
    sections: list[CommandEmbedSection] | None = None,
    kind: str = "info",
    footer_service: object | None = None,
) -> None:
    await send_standard_response(
        interaction,
        top_level="admin",
        subcommand_path=subcommand_path,
        visual_top_level="roles",
        subtitle_args=subtitle_args,
        lines=lines,
        sections=sections,
        kind=kind,
        footer_service=ctx.footer if footer_service is None else footer_service,
    )


async def _check_policy_values(interaction: discord.Interaction, ctx: CommandContext, usage_limit: int | None, cooldown_seconds: int | None, subcommand_path: str) -> bool:
    if usage_limit is not None and usage_limit <= 0:
        await _send_roles_response(interaction, ctx, subcommand_path=subcommand_path, lines=[("error", "Please provide a valid usage limit.")], kind="error")
        return False
    if cooldown_seconds is not None and cooldown_seconds < 0:
        await _send_roles_response(interaction, ctx, subcommand_path=subcommand_path, lines=[("error", "Please provide a valid cooldown.")], kind="error")
        return False
    return True


def register_roles(commandguard_group: app_commands.Group, ctx: CommandContext) -> None:
    @commandguard_group.command(name="role_add", description="Add a role command policy.")
    @app_commands.describe(role="Target role.", command="Command path.", usage_limit="Optional daily usage limit.", cooldown_seconds="Optional cooldown in seconds.")
    async def role_add_command(interaction: discord.Interaction, role: discord.Role, command: str, usage_limit: int | None = None, cooldown_seconds: int | None = None) -> None:
        if not await check_permission(interaction, "admin.commandguard.role_add", ctx):
            return
        if not await _check_policy_values(interaction, ctx, usage_limit, cooldown_seconds, "roles role_add"):
            return
        canonical_command = _canonical_policy_command(command)
        await ctx.database.upsert_role_policy(guild_id=str(interaction.guild_id), role_id=str(role.id), command=canonical_command, usage_limit=usage_limit, cooldown_seconds=cooldown_seconds)
        await _send_roles_response(interaction, ctx, subcommand_path="roles role_add", subtitle_args=[role, canonical_command], lines=[("role", role.mention), ("command", canonical_command), ("result", "added")], kind="success", footer_service=ctx.footer)

    @commandguard_group.command(name="role_edit", description="Edit a role command policy.")
    @app_commands.describe(role="Target role.", command="Command path.", usage_limit="Optional daily usage limit.", cooldown_seconds="Optional cooldown in seconds.")
    async def role_edit_command(interaction: discord.Interaction, role: discord.Role, command: str, usage_limit: int | None = None, cooldown_seconds: int | None = None) -> None:
        if not await check_permission(interaction, "admin.commandguard.role_edit", ctx):
            return
        if not await _check_policy_values(interaction, ctx, usage_limit, cooldown_seconds, "roles role_edit"):
            return
        canonical_command = _canonical_policy_command(command)
        await ctx.database.upsert_role_policy(guild_id=str(interaction.guild_id), role_id=str(role.id), command=canonical_command, usage_limit=usage_limit, cooldown_seconds=cooldown_seconds)
        await _send_roles_response(interaction, ctx, subcommand_path="roles role_edit", subtitle_args=[role, canonical_command], lines=[("role", role.mention), ("command", canonical_command), ("result", "updated")], kind="success", footer_service=ctx.footer)

    @commandguard_group.command(name="role_remove", description="Remove a role command policy.")
    @app_commands.describe(role="Target role.", command="Command path.")
    async def role_remove_command(interaction: discord.Interaction, role: discord.Role, command: str) -> None:
        if not await check_permission(interaction, "admin.commandguard.role_remove", ctx):
            return
        await ctx.database.delete_role_policy(guild_id=str(interaction.guild_id), role_id=str(role.id), command=_canonical_policy_command(command))
        await _send_roles_response(interaction, ctx, subcommand_path="roles role_remove", subtitle_args=[role, _canonical_policy_command(command)], lines=[("role", role.mention), ("command", _canonical_policy_command(command)), ("result", "removed")], kind="success", footer_service=ctx.footer)

    @commandguard_group.command(name="role_show", description="Show role policies.")
    @app_commands.describe(role="Target role.", command="Optional command path filter.")
    async def role_show_command(interaction: discord.Interaction, role: discord.Role, command: str | None = None) -> None:
        if not await check_permission(interaction, "admin.commandguard.role_show", ctx):
            return
        rows = await ctx.database.fetch_role_policies(str(interaction.guild_id), str(role.id))
        if command is not None:
            rows = [row for row in rows if _policy_command_matches(row["command"], command)]
        if not rows:
            await _send_roles_response(interaction, ctx, subcommand_path="roles role_show", subtitle_args=[role, command] if command is not None else [role], lines=[("warning", "No policies found for that role.")], kind="warning", footer_service=ctx.footer)
            return
        await _send_roles_response(interaction, ctx, subcommand_path="roles role_show", subtitle_args=[role, command] if command is not None else [role], lines=[("role", role.mention), ("policies", len(rows))], sections=[CommandEmbedSection(title="Details", lines=[(_canonical_policy_command(row["command"]), _policy_line(_canonical_policy_command(row["command"]), row["usage_limit"], row["cooldown_seconds"])) for row in rows])], footer_service=ctx.footer)

    @commandguard_group.command(name="role_list", description="List all role policies.")
    async def role_list_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.commandguard.role_list", ctx):
            return
        rows = await ctx.database.list_role_policies(str(interaction.guild_id))
        if not rows:
            await _send_roles_response(interaction, ctx, subcommand_path="roles role_list", lines=[("warning", "No role policies configured.")], kind="warning", footer_service=ctx.footer)
            return
        await _send_roles_response(interaction, ctx, subcommand_path="roles role_list", lines=[("policies", len(rows))], sections=[CommandEmbedSection(title="Details", lines=[(_format_role_label(interaction.guild, row['role_id']), f"command={_canonical_policy_command(row['command'])} · {_policy_line(_canonical_policy_command(row['command']), row['usage_limit'], row['cooldown_seconds'])}") for row in rows])], footer_service=ctx.footer)

    @commandguard_group.command(name="role_reset", description="Reset all policies for a role.")
    @app_commands.describe(role="Target role.")
    async def role_reset_command(interaction: discord.Interaction, role: discord.Role) -> None:
        if not await check_permission(interaction, "admin.commandguard.role_reset", ctx):
            return
        await ctx.database.delete_role_policies(str(interaction.guild_id), str(role.id))
        await _send_roles_response(interaction, ctx, subcommand_path="roles role_reset", subtitle_args=[role], lines=[("role", role.mention), ("result", "reset")], kind="success", footer_service=ctx.footer)

    @commandguard_group.command(name="user_add", description="Add a user command policy.")
    @app_commands.describe(user="Target user.", command="Command path.", usage_limit="Optional daily usage limit.", cooldown_seconds="Optional cooldown in seconds.")
    async def user_add_command(interaction: discord.Interaction, user: discord.User, command: str, usage_limit: int | None = None, cooldown_seconds: int | None = None) -> None:
        if not await check_permission(interaction, "admin.commandguard.user_add", ctx):
            return
        if not await _check_policy_values(interaction, ctx, usage_limit, cooldown_seconds, "roles user_add"):
            return
        canonical_command = _canonical_policy_command(command)
        await ctx.database.upsert_user_policy(guild_id=str(interaction.guild_id), user_id=str(user.id), command=canonical_command, usage_limit=usage_limit, cooldown_seconds=cooldown_seconds)
        await _send_roles_response(interaction, ctx, subcommand_path="roles user_add", subtitle_args=[user, canonical_command], lines=[("user", getattr(user, "mention", user.display_name)), ("command", canonical_command), ("result", "added")], kind="success", footer_service=ctx.footer)

    @commandguard_group.command(name="user_edit", description="Edit a user command policy.")
    @app_commands.describe(user="Target user.", command="Command path.", usage_limit="Optional daily usage limit.", cooldown_seconds="Optional cooldown in seconds.")
    async def user_edit_command(interaction: discord.Interaction, user: discord.User, command: str, usage_limit: int | None = None, cooldown_seconds: int | None = None) -> None:
        if not await check_permission(interaction, "admin.commandguard.user_edit", ctx):
            return
        if not await _check_policy_values(interaction, ctx, usage_limit, cooldown_seconds, "roles user_edit"):
            return
        canonical_command = _canonical_policy_command(command)
        await ctx.database.upsert_user_policy(guild_id=str(interaction.guild_id), user_id=str(user.id), command=canonical_command, usage_limit=usage_limit, cooldown_seconds=cooldown_seconds)
        await _send_roles_response(interaction, ctx, subcommand_path="roles user_edit", subtitle_args=[user, canonical_command], lines=[("user", getattr(user, "mention", user.display_name)), ("command", canonical_command), ("result", "updated")], kind="success", footer_service=ctx.footer)

    @commandguard_group.command(name="user_remove", description="Remove a user command policy.")
    @app_commands.describe(user="Target user.", command="Command path.")
    async def user_remove_command(interaction: discord.Interaction, user: discord.User, command: str) -> None:
        if not await check_permission(interaction, "admin.commandguard.user_remove", ctx):
            return
        await ctx.database.delete_user_policy(guild_id=str(interaction.guild_id), user_id=str(user.id), command=_canonical_policy_command(command))
        await _send_roles_response(interaction, ctx, subcommand_path="roles user_remove", subtitle_args=[user, _canonical_policy_command(command)], lines=[("user", getattr(user, "mention", user.display_name)), ("command", _canonical_policy_command(command)), ("result", "removed")], kind="success", footer_service=ctx.footer)

    @commandguard_group.command(name="user_show", description="Show user policies.")
    @app_commands.describe(user="Target user.", command="Optional command path filter.")
    async def user_show_command(interaction: discord.Interaction, user: discord.User, command: str | None = None) -> None:
        if not await check_permission(interaction, "admin.commandguard.user_show", ctx):
            return
        rows = await ctx.database.fetch_user_policies(str(interaction.guild_id), str(user.id))
        if command is not None:
            rows = [row for row in rows if _policy_command_matches(row["command"], command)]
        if not rows:
            await _send_roles_response(interaction, ctx, subcommand_path="roles user_show", subtitle_args=[user, command] if command is not None else [user], lines=[("warning", "No policies found for that user.")], kind="warning", footer_service=ctx.footer)
            return
        await _send_roles_response(interaction, ctx, subcommand_path="roles user_show", subtitle_args=[user, command] if command is not None else [user], lines=[("user", getattr(user, "mention", user.display_name)), ("policies", len(rows))], sections=[CommandEmbedSection(title="Details", lines=[(_canonical_policy_command(row["command"]), _policy_line(_canonical_policy_command(row["command"]), row["usage_limit"], row["cooldown_seconds"])) for row in rows])], footer_service=ctx.footer)

    @commandguard_group.command(name="user_list", description="List all user policies.")
    async def user_list_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.commandguard.user_list", ctx):
            return
        rows = await ctx.database.list_user_policies(str(interaction.guild_id))
        if not rows:
            await _send_roles_response(interaction, ctx, subcommand_path="roles user_list", lines=[("warning", "No user policies configured.")], kind="warning", footer_service=ctx.footer)
            return
        await _send_roles_response(interaction, ctx, subcommand_path="roles user_list", lines=[("policies", len(rows))], sections=[CommandEmbedSection(title="Details", lines=[(_format_user_label(interaction.guild, row['user_id']), f"command={_canonical_policy_command(row['command'])} · {_policy_line(_canonical_policy_command(row['command']), row['usage_limit'], row['cooldown_seconds'])}") for row in rows])], footer_service=ctx.footer)

    @commandguard_group.command(name="user_reset", description="Reset all policies for a user.")
    @app_commands.describe(user="Target user.")
    async def user_reset_command(interaction: discord.Interaction, user: discord.User) -> None:
        if not await check_permission(interaction, "admin.commandguard.user_reset", ctx):
            return
        await ctx.database.delete_user_policies(str(interaction.guild_id), str(user.id))
        await _send_roles_response(interaction, ctx, subcommand_path="roles user_reset", subtitle_args=[user], lines=[("user", getattr(user, "mention", user.display_name)), ("result", "reset")], kind="success", footer_service=ctx.footer)
