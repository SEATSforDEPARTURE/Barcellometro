from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.services.greetings_copy_service import GreetingsCopyService
from app.services.member_flow_notifications import format_duration_human, parse_duration_input
from app.shared.discord.command_embeds import CommandEmbedSection, build_command_embeds, send_command_embeds, send_standard_response

PERM = "mod"


def _normalize_optional_reason(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


async def _send_lines(
    interaction: discord.Interaction,
    ctx: CommandContext,
    *,
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
        top_level="admin",
        subcommand_path=subcommand_path,
        visual_top_level="moderazione",
        lines=[("entries", len(lines))],
        sections=sections,
        footer_service=ctx.footer,
    )
    await send_command_embeds(interaction, embeds=embeds, ephemeral=True, files=[txt])


def _render_departure_action_label(action_type: str) -> str:
    labels = {
        "kick": "allontanamento",
        "inactive_kick": "allontanamento per inattività",
    }
    return labels.get(action_type, action_type)


def register_moderazione_utenti(mod_group: app_commands.Group, ctx: CommandContext) -> None:
    users_group = app_commands.Group(name="users", description="Moderation actions for users")
    mod_group.add_command(users_group)
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
            top_level="admin",
            subcommand_path=subcommand_path,
            visual_top_level="moderazione",
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

    @users_group.command(name="kick", description="Remove a user from the server.")
    @app_commands.describe(user="Member to kick.", reason="Optional reason override.")
    async def mod_users_kick(interaction: discord.Interaction, user: discord.Member, reason: str | None = None) -> None:
        if not await _ensure(interaction) or interaction.guild is None:
            return
        explicit_reason = _normalize_optional_reason(reason)
        resolved_reason = explicit_reason or await _default_reason("kick", user=user, guild=interaction.guild, moderator=interaction.user)
        _remember_departure(interaction.guild, user, "kick")
        try:
            await user.kick(reason=resolved_reason)
        except Exception:
            _forget_departure(interaction.guild, user)
            raise
        await _notify_action(guild=interaction.guild, user=user, action_type="kick", reason=resolved_reason, greetings_reason=explicit_reason, moderator=interaction.user)
        await _send(
            interaction,
            subcommand_path="moderazione users kick",
            subtitle_args=[user],
            lines=[("user", user.mention), ("result", "allontanato"), ("reason", resolved_reason)],
            kind="success",
        )

    @users_group.command(name="kick_list", description="List recent user removals.")
    async def mod_users_kick_list(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        rows = await ctx.database.list_recent_kicked_users(str(interaction.guild_id))
        lines = [
            f"• <@{row['user_id']}> · {_render_departure_action_label(str(row['action_type'] or 'kick'))} · {str(row['created_at'])[:16]} · {row['reason'] or 'n/a'}"
            for row in rows
        ]
        await _send_lines(interaction, ctx, subcommand_path="moderazione users kick_list", title="Recent allontanamenti", lines=lines, prefix="mod_users_kick_list")

    @users_group.command(name="ban", description="Ban a user permanently.")
    @app_commands.describe(user="Member to ban.", reason="Optional reason override.")
    async def mod_users_ban(interaction: discord.Interaction, user: discord.Member, reason: str | None = None) -> None:
        if not await _ensure(interaction) or interaction.guild is None:
            return
        explicit_reason = _normalize_optional_reason(reason)
        resolved_reason = explicit_reason or await _default_reason("ban", user=user, guild=interaction.guild, moderator=interaction.user)
        _remember_departure(interaction.guild, user, "ban")
        try:
            await interaction.guild.ban(user, reason=resolved_reason, delete_message_seconds=0)
        except Exception:
            _forget_departure(interaction.guild, user)
            raise
        await _notify_action(guild=interaction.guild, user=user, action_type="ban", reason=resolved_reason, greetings_reason=explicit_reason, moderator=interaction.user)
        await _send(
            interaction,
            subcommand_path="moderazione users ban",
            subtitle_args=[user],
            lines=[("user", user.mention), ("result", "banned"), ("reason", resolved_reason)],
            kind="success",
        )

    @users_group.command(name="ban_list", description="List active permanent bans.")
    async def mod_users_ban_list(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        rows = await ctx.database.list_active_bans(str(interaction.guild_id))
        lines = [f"• <@{row['user_id']}> · ban · {str(row['created_at'])[:16]} · {row['reason'] or 'n/a'}" for row in rows]
        await _send_lines(interaction, ctx, subcommand_path="moderazione users ban_list", title="Active permanent bans", lines=lines, prefix="mod_users_ban_list")

    @users_group.command(name="tempban", description="Ban a user temporarily.")
    @app_commands.describe(user="Member to ban temporarily.", duration="Duration like 7d or 12h.", reason="Optional reason override.")
    async def mod_users_tempban(interaction: discord.Interaction, user: discord.Member, duration: str, reason: str | None = None) -> None:
        if not await _ensure(interaction) or interaction.guild is None:
            return
        duration_seconds = parse_duration_input(duration)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
        explicit_reason = _normalize_optional_reason(reason)
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
        await _notify_action(guild=interaction.guild, user=user, action_type="tempban", reason=resolved_reason, greetings_reason=explicit_reason, moderator=interaction.user, duration_seconds=duration_seconds, expires_at=expires_at)
        await _send(
            interaction,
            subcommand_path="moderazione users tempban",
            subtitle_args=[user, format_duration_human(duration_seconds)],
            lines=[
                ("user", user.mention),
                ("duration", format_duration_human(duration_seconds)),
                ("expires_at", expires_at.strftime("%d/%m/%Y %H:%M UTC")),
                ("reason", resolved_reason),
            ],
            kind="success",
        )

    @users_group.command(name="tempban_list", description="List active temporary bans.")
    async def mod_users_tempban_list(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        rows = await ctx.database.list_active_tempbans(str(interaction.guild_id))
        lines = [f"• <@{row['user_id']}> · {row['action_type'] or 'tempban'} · expires {str(row['expires_at'])[:16]} · {row['reason'] or 'n/a'}" for row in rows]
        await _send_lines(interaction, ctx, subcommand_path="moderazione users tempban_list", title="Active temporary bans", lines=lines, prefix="mod_users_tempban_list")

    @users_group.command(name="grace", description="Assign a manual grace period to a user.")
    @app_commands.describe(user="Member that receives the grace period.", duration="Optional duration like 7d or 12h.", reason="Optional reason override.")
    async def mod_users_grace(interaction: discord.Interaction, user: discord.Member, duration: str | None = None, reason: str | None = None) -> None:
        if not await _ensure(interaction) or interaction.guild is None:
            return
        cfg = await ctx.database.get_inactivity_config(str(interaction.guild.id)) or {}
        duration_seconds = parse_duration_input(duration) if duration else int(cfg.get("grace_days_after_reminder", 7)) * 86400
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
        await _notify_action(guild=interaction.guild, user=user, action_type="grace", reason=resolved_reason, greetings_reason=explicit_reason, moderator=interaction.user, duration_seconds=duration_seconds, expires_at=expires_at)
        await _send(
            interaction,
            subcommand_path="moderazione users grace",
            subtitle_args=[user],
            lines=[
                ("user", user.mention),
                ("protected_until", expires_at.strftime("%d/%m/%Y %H:%M UTC")),
                ("reason", resolved_reason),
            ],
            kind="success",
        )

    @users_group.command(name="grace_list", description="List active grace periods.")
    async def mod_users_grace_list(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        rows = await ctx.database.list_active_grace_users(str(interaction.guild_id))
        lines = [f"• <@{row['user_id']}> · {row['action_type']} · expires {str(row['expires_at'])[:16]} · {row['reason'] or 'n/a'}" for row in rows]
        await _send_lines(interaction, ctx, subcommand_path="moderazione users grace_list", title="Active grace periods", lines=lines, prefix="mod_users_grace_list")
