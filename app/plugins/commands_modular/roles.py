from __future__ import annotations

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.utils.command_embeds import CommandEmbedSection, send_standard_response


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


async def _check_policy_values(interaction: discord.Interaction, ctx: CommandContext, usage_limit: int | None, cooldown_seconds: int | None, subcommand_path: str) -> bool:
    if usage_limit is not None and usage_limit <= 0:
        await send_standard_response(interaction, top_level="bm", subcommand_path=subcommand_path, lines=[("error", "Please provide a valid usage limit.")], kind="error", footer_service=ctx.footer)
        return False
    if cooldown_seconds is not None and cooldown_seconds < 0:
        await send_standard_response(interaction, top_level="bm", subcommand_path=subcommand_path, lines=[("error", "Please provide a valid cooldown.")], kind="error", footer_service=ctx.footer)
        return False
    return True


def register_roles(commandguard_group: app_commands.Group, ctx: CommandContext) -> None:
    @commandguard_group.command(name="role_add", description="Add a role command policy.")
    @app_commands.describe(role="Target role.", command="Command path.", usage_limit="Optional daily usage limit.", cooldown_seconds="Optional cooldown in seconds.")
    async def role_add_command(interaction: discord.Interaction, role: discord.Role, command: str, usage_limit: int | None = None, cooldown_seconds: int | None = None) -> None:
        if not await check_permission(interaction, "bm.commandguard.role_add", ctx, legacy_aliases=["bm.role.set_role"]):
            return
        if not await _check_policy_values(interaction, ctx, usage_limit, cooldown_seconds, "roles role_add"):
            return
        await ctx.database.upsert_role_policy(guild_id=str(interaction.guild_id), role_id=str(role.id), command=command, usage_limit=usage_limit, cooldown_seconds=cooldown_seconds)
        await send_standard_response(interaction, top_level="bm", subcommand_path="roles role_add", lines=[("role", role.mention), ("command", command), ("result", "added")], kind="success", footer_service=ctx.footer)

    @commandguard_group.command(name="role_edit", description="Edit a role command policy.")
    @app_commands.describe(role="Target role.", command="Command path.", usage_limit="Optional daily usage limit.", cooldown_seconds="Optional cooldown in seconds.")
    async def role_edit_command(interaction: discord.Interaction, role: discord.Role, command: str, usage_limit: int | None = None, cooldown_seconds: int | None = None) -> None:
        if not await check_permission(interaction, "bm.commandguard.role_edit", ctx, legacy_aliases=["bm.role.set_role"]):
            return
        if not await _check_policy_values(interaction, ctx, usage_limit, cooldown_seconds, "roles role_edit"):
            return
        await ctx.database.upsert_role_policy(guild_id=str(interaction.guild_id), role_id=str(role.id), command=command, usage_limit=usage_limit, cooldown_seconds=cooldown_seconds)
        await send_standard_response(interaction, top_level="bm", subcommand_path="roles role_edit", lines=[("role", role.mention), ("command", command), ("result", "updated")], kind="success", footer_service=ctx.footer)

    @commandguard_group.command(name="role_remove", description="Remove a role command policy.")
    @app_commands.describe(role="Target role.", command="Command path.")
    async def role_remove_command(interaction: discord.Interaction, role: discord.Role, command: str) -> None:
        if not await check_permission(interaction, "bm.commandguard.role_remove", ctx, legacy_aliases=["bm.role.clear_role"]):
            return
        await ctx.database.delete_role_policy(guild_id=str(interaction.guild_id), role_id=str(role.id), command=command)
        await send_standard_response(interaction, top_level="bm", subcommand_path="roles role_remove", lines=[("role", role.mention), ("command", command), ("result", "removed")], kind="success", footer_service=ctx.footer)

    @commandguard_group.command(name="role_show", description="Show role policies.")
    @app_commands.describe(role="Target role.", command="Optional command path filter.")
    async def role_show_command(interaction: discord.Interaction, role: discord.Role, command: str | None = None) -> None:
        if not await check_permission(interaction, "bm.commandguard.role_show", ctx, legacy_aliases=["bm.role.show_role"]):
            return
        rows = await ctx.database.fetch_role_policies(str(interaction.guild_id), str(role.id))
        if command is not None:
            rows = [row for row in rows if row["command"] == command]
        if not rows:
            await send_standard_response(interaction, top_level="bm", subcommand_path="roles role_show", lines=[("warning", "No policies found for that role.")], kind="warning", footer_service=ctx.footer)
            return
        await send_standard_response(interaction, top_level="bm", subcommand_path="roles role_show", lines=[("role", role.mention), ("policies", len(rows))], sections=[CommandEmbedSection(title="Details", lines=[(row["command"], _policy_line(row["command"], row["usage_limit"], row["cooldown_seconds"])) for row in rows])], footer_service=ctx.footer)

    @commandguard_group.command(name="role_list", description="List all role policies.")
    async def role_list_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.commandguard.role_list", ctx, legacy_aliases=["bm.role.show_role"]):
            return
        rows = await ctx.database.list_role_policies(str(interaction.guild_id))
        if not rows:
            await send_standard_response(interaction, top_level="bm", subcommand_path="roles role_list", lines=[("warning", "No role policies configured.")], kind="warning", footer_service=ctx.footer)
            return
        await send_standard_response(interaction, top_level="bm", subcommand_path="roles role_list", lines=[("policies", len(rows))], sections=[CommandEmbedSection(title="Details", lines=[(_format_role_label(interaction.guild, row['role_id']), f"command={row['command']} · {_policy_line(row['command'], row['usage_limit'], row['cooldown_seconds'])}") for row in rows])], footer_service=ctx.footer)

    @commandguard_group.command(name="role_reset", description="Reset all policies for a role.")
    @app_commands.describe(role="Target role.")
    async def role_reset_command(interaction: discord.Interaction, role: discord.Role) -> None:
        if not await check_permission(interaction, "bm.commandguard.role_reset", ctx, legacy_aliases=["bm.role.clear_role"]):
            return
        await ctx.database.delete_role_policies(str(interaction.guild_id), str(role.id))
        await send_standard_response(interaction, top_level="bm", subcommand_path="roles role_reset", lines=[("role", role.mention), ("result", "reset")], kind="success", footer_service=ctx.footer)

    @commandguard_group.command(name="user_add", description="Add a user command policy.")
    @app_commands.describe(user="Target user.", command="Command path.", usage_limit="Optional daily usage limit.", cooldown_seconds="Optional cooldown in seconds.")
    async def user_add_command(interaction: discord.Interaction, user: discord.User, command: str, usage_limit: int | None = None, cooldown_seconds: int | None = None) -> None:
        if not await check_permission(interaction, "bm.commandguard.user_add", ctx, legacy_aliases=["bm.role.set_user"]):
            return
        if not await _check_policy_values(interaction, ctx, usage_limit, cooldown_seconds, "roles user_add"):
            return
        await ctx.database.upsert_user_policy(guild_id=str(interaction.guild_id), user_id=str(user.id), command=command, usage_limit=usage_limit, cooldown_seconds=cooldown_seconds)
        await send_standard_response(interaction, top_level="bm", subcommand_path="roles user_add", lines=[("user", getattr(user, "mention", user.display_name)), ("command", command), ("result", "added")], kind="success", footer_service=ctx.footer)

    @commandguard_group.command(name="user_edit", description="Edit a user command policy.")
    @app_commands.describe(user="Target user.", command="Command path.", usage_limit="Optional daily usage limit.", cooldown_seconds="Optional cooldown in seconds.")
    async def user_edit_command(interaction: discord.Interaction, user: discord.User, command: str, usage_limit: int | None = None, cooldown_seconds: int | None = None) -> None:
        if not await check_permission(interaction, "bm.commandguard.user_edit", ctx, legacy_aliases=["bm.role.set_user"]):
            return
        if not await _check_policy_values(interaction, ctx, usage_limit, cooldown_seconds, "roles user_edit"):
            return
        await ctx.database.upsert_user_policy(guild_id=str(interaction.guild_id), user_id=str(user.id), command=command, usage_limit=usage_limit, cooldown_seconds=cooldown_seconds)
        await send_standard_response(interaction, top_level="bm", subcommand_path="roles user_edit", lines=[("user", getattr(user, "mention", user.display_name)), ("command", command), ("result", "updated")], kind="success", footer_service=ctx.footer)

    @commandguard_group.command(name="user_remove", description="Remove a user command policy.")
    @app_commands.describe(user="Target user.", command="Command path.")
    async def user_remove_command(interaction: discord.Interaction, user: discord.User, command: str) -> None:
        if not await check_permission(interaction, "bm.commandguard.user_remove", ctx, legacy_aliases=["bm.role.clear_user"]):
            return
        await ctx.database.delete_user_policy(guild_id=str(interaction.guild_id), user_id=str(user.id), command=command)
        await send_standard_response(interaction, top_level="bm", subcommand_path="roles user_remove", lines=[("user", getattr(user, "mention", user.display_name)), ("command", command), ("result", "removed")], kind="success", footer_service=ctx.footer)

    @commandguard_group.command(name="user_show", description="Show user policies.")
    @app_commands.describe(user="Target user.", command="Optional command path filter.")
    async def user_show_command(interaction: discord.Interaction, user: discord.User, command: str | None = None) -> None:
        if not await check_permission(interaction, "bm.commandguard.user_show", ctx, legacy_aliases=["bm.role.show_user"]):
            return
        rows = await ctx.database.fetch_user_policies(str(interaction.guild_id), str(user.id))
        if command is not None:
            rows = [row for row in rows if row["command"] == command]
        if not rows:
            await send_standard_response(interaction, top_level="bm", subcommand_path="roles user_show", lines=[("warning", "No policies found for that user.")], kind="warning", footer_service=ctx.footer)
            return
        await send_standard_response(interaction, top_level="bm", subcommand_path="roles user_show", lines=[("user", getattr(user, "mention", user.display_name)), ("policies", len(rows))], sections=[CommandEmbedSection(title="Details", lines=[(row["command"], _policy_line(row["command"], row["usage_limit"], row["cooldown_seconds"])) for row in rows])], footer_service=ctx.footer)

    @commandguard_group.command(name="user_list", description="List all user policies.")
    async def user_list_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.commandguard.user_list", ctx, legacy_aliases=["bm.role.show_user"]):
            return
        rows = await ctx.database.list_user_policies(str(interaction.guild_id))
        if not rows:
            await send_standard_response(interaction, top_level="bm", subcommand_path="roles user_list", lines=[("warning", "No user policies configured.")], kind="warning", footer_service=ctx.footer)
            return
        await send_standard_response(interaction, top_level="bm", subcommand_path="roles user_list", lines=[("policies", len(rows))], sections=[CommandEmbedSection(title="Details", lines=[(_format_user_label(interaction.guild, row['user_id']), f"command={row['command']} · {_policy_line(row['command'], row['usage_limit'], row['cooldown_seconds'])}") for row in rows])], footer_service=ctx.footer)

    @commandguard_group.command(name="user_reset", description="Reset all policies for a user.")
    @app_commands.describe(user="Target user.")
    async def user_reset_command(interaction: discord.Interaction, user: discord.User) -> None:
        if not await check_permission(interaction, "bm.commandguard.user_reset", ctx, legacy_aliases=["bm.role.clear_user"]):
            return
        await ctx.database.delete_user_policies(str(interaction.guild_id), str(user.id))
        await send_standard_response(interaction, top_level="bm", subcommand_path="roles user_reset", lines=[("user", getattr(user, "mention", user.display_name)), ("result", "reset")], kind="success", footer_service=ctx.footer)
