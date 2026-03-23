from __future__ import annotations

import io
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.services.greetings_copy_service import GreetingsCopyService
from app.services.member_flow_notifications import format_duration_human, parse_duration_input
from app.shared.discord.command_embeds import CommandEmbedSection, build_command_embeds, send_command_embeds, send_standard_response

logger = logging.getLogger(__name__)

PERM = "users"


def _normalize_optional_reason(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


async def _send_lines(
    interaction: discord.Interaction,
    ctx: CommandContext,
    *,
    top_level: str,
    visual_top_level: str,
    subcommand_path: str,
    title: str,
    lines: list[str],
    prefix: str,
) -> None:
    payload = "\n".join(lines) if lines else "No results."
    txt = discord.File(
        io.BytesIO(payload.encode("utf-8")),
        filename=f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.txt",
    )
    sections = [CommandEmbedSection(title=title, lines=lines or ["No results."])]
    embeds = await build_command_embeds(
        top_level=top_level,
        subcommand_path=subcommand_path,
        visual_top_level=visual_top_level,
        lines=[("entries", len(lines))],
        sections=sections,
        footer_service=ctx.footer,
    )
    await send_command_embeds(
        interaction,
        embeds=embeds,
        ephemeral=True,
        files=[txt],
        footer_service=ctx.footer,
        author_service=getattr(ctx, "author", None),
        default_service_name="users",
    )


def _render_departure_action_label(action_type: str) -> str:
    labels = {
        "kick": "allontanamento",
        "inactive_kick": "allontanamento per inattività",
    }
    return labels.get(action_type, action_type)


def register_moderazione_utenti(
    users_group: app_commands.Group,
    ctx: CommandContext,
    *,
    top_level: str = "users",
    visual_top_level: str = "users",
    alias_commands: list[app_commands.Command] | None = None,
) -> None:
    greetings_copy_service = GreetingsCopyService(ctx.database, barcello_service=getattr(ctx, "barcello_service", None))

    async def _ensure(interaction: discord.Interaction) -> bool:
        return await check_permission(interaction, PERM, ctx)

    async def _send(
        interaction: discord.Interaction,
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
            top_level=top_level,
            subcommand_path=subcommand_path,
            visual_top_level=visual_top_level,
            subtitle_args=subtitle_args,
            lines=lines,
            sections=sections,
            kind=kind,
            footer_service=ctx.footer if footer_service is None else footer_service,
        )

    async def _default_reason(
        action_type: str,
        *,
        user: discord.abc.User | discord.Member,
        guild: discord.Guild,
        moderator: discord.abc.User | discord.Member | None,
        duration_seconds: int | None = None,
        expires_at: datetime | None = None,
    ) -> str:
        rendered = await greetings_copy_service.render_event_copy(
            user=user,
            guild=guild,
            event_type_key=action_type,
            moderator=moderator,
            duration_seconds=duration_seconds,
            expires_at=expires_at,
            occurrence_number=1,
            metadata={},
        )
        return rendered.narrative

    async def _notify_action(
        *,
        guild: discord.Guild,
        user: discord.abc.User | discord.Member,
        action_type: str,
        reason: str,
        greetings_reason: str | None,
        moderator: discord.Member | discord.User,
        duration_seconds: int | None = None,
        expires_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> None:
        if ctx.member_flow_notifications is None:
            return
        metadata_dict = {
            **(metadata or {}),
            "source": "moderazione_utenti",
            "greetings_reason": greetings_reason,
        }
        result = await ctx.member_flow_notifications.log_action(
            guild_id=str(guild.id),
            user_id=str(user.id),
            moderator_id=str(moderator.id),
            action_type=action_type,
            reason=reason,
            duration_seconds=duration_seconds,
            expires_at=expires_at.isoformat() if expires_at else None,
            metadata=metadata_dict,
        )
        if result.get("canonical_written") and result.get("canonical_visible"):
            await ctx.member_flow_notifications.send_notification(
                guild=guild,
                user=user,
                action_type=action_type,
                reason=reason,
                moderator=moderator,
                duration_seconds=duration_seconds,
                expires_at=expires_at,
                metadata=metadata_dict,
                canonical_event=result.get("canonical_event"),
            )

    def _remember_departure(guild: discord.Guild, user: discord.abc.User | discord.Member, action_type: str) -> None:
        if ctx.member_flow_notifications is None:
            return
        remember = getattr(ctx.member_flow_notifications, "remember_departure_action", None)
        if remember is None:
            return
        remember(str(guild.id), str(user.id), action_type)

    def _forget_departure(guild: discord.Guild, user: discord.abc.User | discord.Member) -> None:
        if ctx.member_flow_notifications is None:
            return
        forget = getattr(ctx.member_flow_notifications, "forget_departure_action", None)
        if forget is None:
            return
        forget(str(guild.id), str(user.id))

    async def _kick_impl(interaction: discord.Interaction, user: discord.Member, reason: str | None = None) -> None:
        if not await _ensure(interaction) or interaction.guild is None:
            return
        explicit_reason = _normalize_optional_reason(reason)
        resolved_reason = explicit_reason or await _default_reason("kick", user=user, guild=interaction.guild, moderator=interaction.user)
        operation_id = str(uuid4())
        _remember_departure(interaction.guild, user, "kick")
        try:
            await user.kick(reason=resolved_reason)
        except Exception:
            _forget_departure(interaction.guild, user)
            raise
        await _notify_action(
            guild=interaction.guild,
            user=user,
            action_type="kick",
            reason=resolved_reason,
            greetings_reason=explicit_reason,
            moderator=interaction.user,
            metadata={"operation_id": operation_id},
        )
        await _send(
            interaction,
            subcommand_path="users kick",
            subtitle_args=[user],
            lines=[("user", user.mention), ("result", "allontanato"), ("reason", resolved_reason)],
            kind="success",
        )

    async def _kick_list_impl(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        rows = await ctx.database.list_recent_kicked_users(str(interaction.guild_id))
        lines = [
            f"• <@{row['user_id']}> · {_render_departure_action_label(str(row['action_type'] or 'kick'))} · {str(row['created_at'])[:16]} · {row['reason'] or 'n/a'}"
            for row in rows
        ]
        await _send_lines(
            interaction,
            ctx,
            top_level=top_level,
            visual_top_level=visual_top_level,
            subcommand_path="users kick_list",
            title="Recent allontanamenti",
            lines=lines,
            prefix="users_kick_list",
        )

    async def _ban_impl(interaction: discord.Interaction, user: discord.Member, reason: str | None = None) -> None:
        if not await _ensure(interaction) or interaction.guild is None:
            return
        explicit_reason = _normalize_optional_reason(reason)
        resolved_reason = explicit_reason or await _default_reason("ban", user=user, guild=interaction.guild, moderator=interaction.user)
        operation_id = str(uuid4())
        _remember_departure(interaction.guild, user, "ban")
        try:
            await interaction.guild.ban(user, reason=resolved_reason, delete_message_seconds=0)
        except Exception:
            _forget_departure(interaction.guild, user)
            raise
        await _notify_action(
            guild=interaction.guild,
            user=user,
            action_type="ban",
            reason=resolved_reason,
            greetings_reason=explicit_reason,
            moderator=interaction.user,
            metadata={"operation_id": operation_id},
        )
        await _send(
            interaction,
            subcommand_path="users ban",
            subtitle_args=[user],
            lines=[("user", user.mention), ("result", "banned"), ("reason", resolved_reason)],
            kind="success",
        )

    async def _ban_list_impl(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        rows = await ctx.database.list_active_bans(str(interaction.guild_id))
        lines = [f"• <@{row['user_id']}> · ban · {str(row['created_at'])[:16]} · {row['reason'] or 'n/a'}" for row in rows]
        await _send_lines(
            interaction,
            ctx,
            top_level=top_level,
            visual_top_level=visual_top_level,
            subcommand_path="users ban_list",
            title="Active permanent bans",
            lines=lines,
            prefix="users_ban_list",
        )

    async def _unban_impl(interaction: discord.Interaction, user: discord.User, reason: str | None = None) -> None:
        if not await _ensure(interaction) or interaction.guild is None:
            return
        explicit_reason = _normalize_optional_reason(reason)
        resolved_reason = explicit_reason or "Revoca ban manuale"
        discord_unban_result = "unbanned"
        try:
            await interaction.guild.unban(user, reason=resolved_reason)
        except discord.NotFound as exc:
            if exc.code != 10026:
                raise
            discord_unban_result = "discord_ban_missing"
            logger.info(
                "users unban: discord ban already missing guild=%s user=%s",
                interaction.guild.id,
                user.id,
            )
        await ctx.database.clear_user_ban_state(str(interaction.guild.id), str(user.id))
        _forget_departure(interaction.guild, user)
        await _notify_action(
            guild=interaction.guild,
            user=user,
            action_type="unban",
            reason=resolved_reason,
            greetings_reason=explicit_reason,
            moderator=interaction.user,
            metadata={"discord_unban_result": discord_unban_result},
        )
        response_lines = [("user", user.mention), ("reason", resolved_reason)]
        if discord_unban_result == "unbanned":
            response_lines.insert(1, ("result", "ban revocato"))
        else:
            response_lines.extend([
                ("result", "nessun ban attivo trovato su Discord"),
                ("sync", "stati locali riallineati"),
            ])
        await _send(
            interaction,
            subcommand_path="users unban",
            subtitle_args=[user],
            lines=response_lines,
            kind="success",
        )

    async def _tempban_impl(interaction: discord.Interaction, user: discord.Member, duration: str, reason: str | None = None) -> None:
        if not await _ensure(interaction) or interaction.guild is None:
            return
        duration_seconds = parse_duration_input(duration)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
        explicit_reason = _normalize_optional_reason(reason)
        operation_id = str(uuid4())
        resolved_reason = explicit_reason or await _default_reason(
            "tempban",
            user=user,
            guild=interaction.guild,
            moderator=interaction.user,
            duration_seconds=duration_seconds,
            expires_at=expires_at,
        )
        _remember_departure(interaction.guild, user, "tempban")
        try:
            await interaction.guild.ban(user, reason=resolved_reason, delete_message_seconds=0)
        except Exception:
            _forget_departure(interaction.guild, user)
            raise
        await ctx.database.add_temp_ban(str(interaction.guild.id), str(user.id), expires_at.isoformat(), resolved_reason)
        await _notify_action(
            guild=interaction.guild,
            user=user,
            action_type="tempban",
            reason=resolved_reason,
            greetings_reason=explicit_reason,
            moderator=interaction.user,
            duration_seconds=duration_seconds,
            expires_at=expires_at,
            metadata={"operation_id": operation_id},
        )
        await _send(
            interaction,
            subcommand_path="users tempban",
            subtitle_args=[user, format_duration_human(duration_seconds)],
            lines=[
                ("user", user.mention),
                ("duration", format_duration_human(duration_seconds)),
                ("expires_at", expires_at.strftime("%d/%m/%Y %H:%M UTC")),
                ("reason", resolved_reason),
            ],
            kind="success",
        )

    async def _tempban_list_impl(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        rows = await ctx.database.list_active_tempbans(str(interaction.guild_id))
        lines = [f"• <@{row['user_id']}> · {row['action_type'] or 'tempban'} · expires {str(row['expires_at'])[:16]} · {row['reason'] or 'n/a'}" for row in rows]
        await _send_lines(
            interaction,
            ctx,
            top_level=top_level,
            visual_top_level=visual_top_level,
            subcommand_path="users tempban_list",
            title="Active temporary bans",
            lines=lines,
            prefix="users_tempban_list",
        )

    async def _grace_impl(interaction: discord.Interaction, user: discord.Member, duration: str, reason: str | None = None) -> None:
        if not await _ensure(interaction) or interaction.guild is None:
            return
        duration_seconds = parse_duration_input(duration)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
        await ctx.database.extend_user_grace(str(interaction.guild.id), str(user.id), datetime.now(timezone.utc).isoformat())
        explicit_reason = _normalize_optional_reason(reason)
        resolved_reason = explicit_reason or await _default_reason(
            "grace",
            user=user,
            guild=interaction.guild,
            moderator=interaction.user,
            duration_seconds=duration_seconds,
            expires_at=expires_at,
        )
        await _notify_action(
            guild=interaction.guild,
            user=user,
            action_type="grace",
            reason=resolved_reason,
            greetings_reason=explicit_reason,
            moderator=interaction.user,
            duration_seconds=duration_seconds,
            expires_at=expires_at,
        )
        await _send(
            interaction,
            subcommand_path="users grace",
            subtitle_args=[user],
            lines=[
                ("user", user.mention),
                ("duration", format_duration_human(duration_seconds)),
                ("protected_until", expires_at.strftime("%d/%m/%Y %H:%M UTC")),
                ("reason", resolved_reason),
            ],
            kind="success",
        )

    async def _grace_list_impl(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        rows = await ctx.database.list_active_grace_users(str(interaction.guild_id))
        lines = [f"• <@{row['user_id']}> · {row['action_type']} · expires {str(row['expires_at'])[:16]} · {row['reason'] or 'n/a'}" for row in rows]
        await _send_lines(
            interaction,
            ctx,
            top_level=top_level,
            visual_top_level=visual_top_level,
            subcommand_path="users grace_list",
            title="Active grace periods",
            lines=lines,
            prefix="users_grace_list",
        )

    @users_group.command(name="kick", description="Remove a user from the server.")
    @app_commands.describe(user="Member to kick.", reason="Optional reason override.")
    async def users_kick(interaction: discord.Interaction, user: discord.Member, reason: str | None = None) -> None:
        await _kick_impl(interaction, user, reason)

    @users_group.command(name="kick_list", description="List recent user removals.")
    async def users_kick_list(interaction: discord.Interaction) -> None:
        await _kick_list_impl(interaction)

    @users_group.command(name="ban", description="Ban a user permanently.")
    @app_commands.describe(user="Member to ban.", reason="Optional reason override.")
    async def users_ban(interaction: discord.Interaction, user: discord.Member, reason: str | None = None) -> None:
        await _ban_impl(interaction, user, reason)

    @users_group.command(name="ban_list", description="List active permanent bans.")
    async def users_ban_list(interaction: discord.Interaction) -> None:
        await _ban_list_impl(interaction)

    @users_group.command(name="unban", description="Revoke an active ban for a user.")
    @app_commands.describe(user="User to unban.", reason="Optional reason override.")
    async def users_unban(interaction: discord.Interaction, user: discord.User, reason: str | None = None) -> None:
        await _unban_impl(interaction, user, reason)

    @users_group.command(name="tempban", description="Ban a user temporarily.")
    @app_commands.describe(user="Member to ban temporarily.", duration="Duration like 7d or 12h.", reason="Optional reason override.")
    async def users_tempban(interaction: discord.Interaction, user: discord.Member, duration: str, reason: str | None = None) -> None:
        await _tempban_impl(interaction, user, duration, reason)

    @users_group.command(name="tempban_list", description="List active temporary bans.")
    async def users_tempban_list(interaction: discord.Interaction) -> None:
        await _tempban_list_impl(interaction)

    @users_group.command(name="grace", description="Assign a manual grace period to a user.")
    @app_commands.describe(user="Member that receives the grace period.", duration="Duration like 7d or 12h.", reason="Optional reason override.")
    async def users_grace(interaction: discord.Interaction, user: discord.Member, duration: str, reason: str | None = None) -> None:
        await _grace_impl(interaction, user, duration, reason)

    @users_group.command(name="grace_list", description="List active grace periods.")
    async def users_grace_list(interaction: discord.Interaction) -> None:
        await _grace_list_impl(interaction)

    if alias_commands is not None:
        @app_commands.command(name="kick", description="Alias of /users kick.")
        @app_commands.describe(user="Member to kick.", reason="Optional reason override.")
        async def kick_alias(interaction: discord.Interaction, user: discord.Member, reason: str | None = None) -> None:
            await _kick_impl(interaction, user, reason)

        @app_commands.command(name="ban", description="Alias of /users ban.")
        @app_commands.describe(user="Member to ban.", reason="Optional reason override.")
        async def ban_alias(interaction: discord.Interaction, user: discord.Member, reason: str | None = None) -> None:
            await _ban_impl(interaction, user, reason)

        @app_commands.command(name="tempban", description="Alias of /users tempban.")
        @app_commands.describe(user="Member to ban temporarily.", duration="Duration like 7d or 12h.", reason="Optional reason override.")
        async def tempban_alias(interaction: discord.Interaction, user: discord.Member, duration: str, reason: str | None = None) -> None:
            await _tempban_impl(interaction, user, duration, reason)

        @app_commands.command(name="grace", description="Alias of /users grace.")
        @app_commands.describe(user="Member that receives the grace period.", duration="Duration like 7d or 12h.", reason="Optional reason override.")
        async def grace_alias(interaction: discord.Interaction, user: discord.Member, duration: str, reason: str | None = None) -> None:
            await _grace_impl(interaction, user, duration, reason)

        alias_commands.extend([kick_alias, ban_alias, tempban_alias, grace_alias])
