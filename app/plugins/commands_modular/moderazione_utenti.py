from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.time_windows import (
    TimeWindowResult,
    resolve_ieri_window,
    resolve_oggi_window,
    resolve_range_window,
    resolve_ultimi_window,
    rolling_window_timedelta,
)
from app.services.greetings_copy_service import GreetingsCopyService
from app.services.member_flow_notifications import format_duration_human
from app.shared.discord.command_embeds import CommandEmbedSection, build_command_embeds, send_command_embeds, send_standard_response

logger = logging.getLogger(__name__)

PERM = "users"
WINDOW_UNIT_CHOICES = [
    app_commands.Choice(name="minuti", value="minuti"),
    app_commands.Choice(name="ore", value="ore"),
    app_commands.Choice(name="giorni", value="giorni"),
    app_commands.Choice(name="settimane", value="settimane"),
]
WINDOW_UNIT_CHOICES_EN = [
    app_commands.Choice(name="minutes", value="minuti"),
    app_commands.Choice(name="hours", value="ore"),
    app_commands.Choice(name="days", value="giorni"),
    app_commands.Choice(name="weeks", value="settimane"),
]
WINDOW_ACTION_LABELS = {
    "unban": "ban",
    "untempban": "temp ban",
    "ungrace": "grace",
}
USERS_GRACE_TEMPBAN_DEFAULT_SECONDS = 0


def _users_grace_tempban_setting_key(guild_id: int | str) -> str:
    return f"users.grace.tempban.default_seconds.{guild_id}"


def _normalize_optional_reason(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_lookup_key(value: str | None) -> str:
    return " ".join(str(value or "").strip().casefold().split())


class _ResolvedModerationUser:
    def __init__(self, *, user_id: str, display_name: str | None = None) -> None:
        clean_display = str(display_name or "").strip()
        self.id = int(user_id)
        self.name = clean_display or f"ID {user_id}"
        self.display_name = self.name
        self.mention = f"<@{user_id}>"


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

    async def _unban_impl(
        interaction: discord.Interaction,
        user: _ResolvedModerationUser,
        reason: str | None = None,
        *,
        subcommand_path: str = "users unban",
        success_result: str = "ban revocato",
        send_response: bool = True,
    ) -> None:
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
        if not send_response:
            return
        response_lines = [("user", user.mention), ("reason", resolved_reason)]
        if discord_unban_result == "unbanned":
            response_lines.insert(1, ("result", success_result))
        else:
            response_lines.extend([
                ("result", "nessun ban attivo trovato su Discord"),
                ("sync", "stati locali riallineati"),
            ])
        await _send(
            interaction,
            subcommand_path=subcommand_path,
            subtitle_args=[user],
            lines=response_lines,
            kind="success",
        )

    def _resolve_duration_seconds(quantity: int, unit: str) -> int:
        return int(rolling_window_timedelta(quantity, unit).total_seconds())

    async def _get_users_grace_tempban_default_seconds(guild_id: int | str) -> int:
        raw = await ctx.database.get_setting(_users_grace_tempban_setting_key(guild_id))
        if raw is None:
            return USERS_GRACE_TEMPBAN_DEFAULT_SECONDS
        try:
            return max(0, int(str(raw).strip()))
        except Exception:
            return USERS_GRACE_TEMPBAN_DEFAULT_SECONDS

    async def _set_users_grace_tempban_default_seconds(guild_id: int | str, seconds: int) -> int:
        normalized = max(0, int(seconds))
        await ctx.database.set_setting(_users_grace_tempban_setting_key(guild_id), str(normalized))
        return normalized

    async def _tempban_impl(
        interaction: discord.Interaction,
        user: discord.Member,
        quantity: int,
        unit: str,
        reason: str | None = None,
    ) -> None:
        if not await _ensure(interaction) or interaction.guild is None:
            return
        duration_seconds = _resolve_duration_seconds(quantity, unit)
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
            subtitle_args=[user, quantity, unit],
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

    async def _grace_impl(
        interaction: discord.Interaction,
        user: discord.Member,
        quantity: int,
        unit: str,
        reason: str | None = None,
    ) -> None:
        if not await _ensure(interaction) or interaction.guild is None:
            return
        duration_seconds = _resolve_duration_seconds(quantity, unit)
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

    async def _ungrace_impl(
        interaction: discord.Interaction,
        user: discord.User,
        reason: str | None = None,
        *,
        subcommand_path: str = "users ungrace",
        send_response: bool = True,
    ) -> None:
        if not await _ensure(interaction) or interaction.guild is None:
            return
        explicit_reason = _normalize_optional_reason(reason)
        resolved_reason = explicit_reason or "Grace period revoked manually"
        now_iso = datetime.now(timezone.utc).isoformat()
        await ctx.database.revoke_user_grace_state(str(interaction.guild.id), str(user.id), now_iso=now_iso)
        if not send_response:
            return
        await _send(
            interaction,
            subcommand_path=subcommand_path,
            subtitle_args=[user],
            lines=[("user", user.mention), ("result", "grace revoked"), ("reason", resolved_reason)],
            kind="success",
        )

    def _resolve_window_bounds(window: TimeWindowResult) -> tuple[str, str]:
        return (
            window.start_dt.astimezone(timezone.utc).isoformat(),
            window.end_dt.astimezone(timezone.utc).isoformat(),
        )

    async def _list_revocable_users_in_window(
        guild_id: str,
        *,
        mode: str,
        window: TimeWindowResult,
    ) -> list[_ResolvedModerationUser]:
        if mode not in {"unban", "untempban", "ungrace"}:
            return []
        start_iso, end_iso = _resolve_window_bounds(window)
        if mode == "unban":
            rows = await ctx.database.list_active_bans(
                guild_id,
                limit=500,
                created_from_iso=start_iso,
                created_to_iso=end_iso,
            )
        elif mode == "untempban":
            rows = await ctx.database.list_active_tempbans(
                guild_id,
                created_from_iso=start_iso,
                created_to_iso=end_iso,
            )
        else:
            rows = await ctx.database.list_active_grace_users(
                guild_id,
                created_from_iso=start_iso,
                created_to_iso=end_iso,
            )
        resolved: list[_ResolvedModerationUser] = []
        seen: set[str] = set()
        for row in rows:
            raw_user_id = str(row["user_id"] or "").strip()
            if not raw_user_id or raw_user_id in seen:
                continue
            seen.add(raw_user_id)
            display = await ctx.database.fetch_user_display_name(guild_id=guild_id, user_id=raw_user_id)
            resolved.append(_ResolvedModerationUser(user_id=raw_user_id, display_name=display))
        return resolved

    async def _run_window_batch(
        interaction: discord.Interaction,
        *,
        mode: str,
        reason: str | None,
        window: TimeWindowResult,
        subcommand_path: str,
    ) -> None:
        if not await _ensure(interaction) or interaction.guild is None or interaction.guild_id is None:
            return
        users = await _list_revocable_users_in_window(str(interaction.guild_id), mode=mode, window=window)
        if not users:
            await _send(
                interaction,
                subcommand_path=subcommand_path,
                lines=[
                    ("period", window.label_periodo),
                    ("result", f"no active {WINDOW_ACTION_LABELS[mode]} entries in selected window"),
                ],
                kind="info",
            )
            return

        processed = 0
        for user in users:
            if mode in {"unban", "untempban"}:
                await _unban_impl(
                    interaction,
                    user,
                    reason,
                    subcommand_path=subcommand_path,
                    success_result="temporary ban revoked" if mode == "untempban" else "ban revocato",
                    send_response=False,
                )
            else:
                await _ungrace_impl(
                    interaction,
                    user,
                    reason,
                    subcommand_path=subcommand_path,
                    send_response=False,
                )
            processed += 1
        sample_mentions = ", ".join(user.mention for user in users[:5])
        await _send(
            interaction,
            subcommand_path=subcommand_path,
            lines=[
                ("period", window.label_periodo),
                ("processed", processed),
                ("state", f"{WINDOW_ACTION_LABELS[mode]} revoked"),
                ("sample", sample_mentions or "n/a"),
            ],
            kind="success",
        )

    async def _resolve_moderation_user(
        interaction: discord.Interaction,
        *,
        nick_or_id: str,
        mode: str,
    ) -> _ResolvedModerationUser | None:
        raw_value = str(nick_or_id or "").strip()
        if not raw_value or interaction.guild_id is None:
            await _send(
                interaction,
                subcommand_path=f"users {mode}",
                lines=[("error", "Inserisci un ID utente o un nickname noto.")],
                kind="error",
            )
            return None
        guild_id = str(interaction.guild_id)

        if re.fullmatch(r"\d+", raw_value):
            resolved_name = await ctx.database.fetch_user_display_name(guild_id=guild_id, user_id=raw_value)
            return _ResolvedModerationUser(user_id=raw_value, display_name=resolved_name)

        if mode in {"unban", "untempban"}:
            candidate_rows = await ctx.database.list_active_tempbans(guild_id)
            if mode == "unban":
                candidate_rows.extend(await ctx.database.list_active_bans(guild_id, limit=200))
        else:
            candidate_rows = await ctx.database.list_active_grace_users(guild_id)

        candidate_ids = sorted(
            {
                str(row["user_id"])
                for row in candidate_rows
                if row["user_id"] is not None
            }
        )
        if not candidate_ids:
            await _send(
                interaction,
                subcommand_path=f"users {mode}",
                lines=[("error", "Nessun utente attualmente in stato revocabile.")],
                kind="error",
            )
            return None

        matches: list[tuple[str, str]] = []
        target_key = _normalize_lookup_key(raw_value)
        for user_id in candidate_ids:
            display = await ctx.database.fetch_user_display_name(guild_id=guild_id, user_id=user_id)
            display_key = _normalize_lookup_key(display)
            if display_key and display_key == target_key:
                matches.append((user_id, str(display or "").strip() or user_id))

        if not matches:
            await _send(
                interaction,
                subcommand_path=f"users {mode}",
                lines=[("error", f"Nessun utente trovato per '{raw_value}'. Usa ID o ultimo nick noto.")],
                kind="error",
            )
            return None
        if len(matches) > 1:
            hints = ", ".join(f"{name} (ID {uid})" for uid, name in matches[:5])
            await _send(
                interaction,
                subcommand_path=f"users {mode}",
                lines=[
                    ("error", f"Nickname ambiguo: '{raw_value}'."),
                    ("matches", hints),
                    ("hint", "Specifica l'ID utente."),
                ],
                kind="error",
            )
            return None
        matched_id, matched_name = matches[0]
        return _ResolvedModerationUser(user_id=matched_id, display_name=matched_name)

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

    def _resolve_last_window(quantita: int, unita: str) -> tuple[TimeWindowResult | None, str | None]:
        return resolve_ultimi_window(quantita, unita, ctx.config)

    def _resolve_range_batch_window(start_at: str, end_at: str) -> tuple[TimeWindowResult | None, str | None]:
        return resolve_range_window(start_at, end_at, ctx.config)

    unban_group = app_commands.Group(name="unban", description="Revoke bans by user or time window.")

    @unban_group.command(name="user", description="Revoke an active ban for one user.")
    @app_commands.describe(nick_or_id="Last known nickname or user ID.", reason="Optional reason override.")
    async def users_unban_user(interaction: discord.Interaction, nick_or_id: str, reason: str | None = None) -> None:
        user = await _resolve_moderation_user(interaction, nick_or_id=nick_or_id, mode="unban")
        if user is None:
            return
        await _unban_impl(interaction, user, reason, subcommand_path="users unban user")

    @unban_group.command(name="today", description="Revoke bans created today.")
    @app_commands.describe(reason="Optional reason override.")
    async def users_unban_today(interaction: discord.Interaction, reason: str | None = None) -> None:
        await _run_window_batch(interaction, mode="unban", reason=reason, window=resolve_oggi_window(), subcommand_path="users unban today")

    @unban_group.command(name="yesterday", description="Revoke bans created yesterday.")
    @app_commands.describe(reason="Optional reason override.")
    async def users_unban_yesterday(interaction: discord.Interaction, reason: str | None = None) -> None:
        await _run_window_batch(interaction, mode="unban", reason=reason, window=resolve_ieri_window(), subcommand_path="users unban yesterday")

    @unban_group.command(name="last", description="Revoke bans created in the last rolling window.")
    @app_commands.describe(quantity="Rolling quantity.", unit="Rolling unit.", reason="Optional reason override.")
    @app_commands.choices(unit=WINDOW_UNIT_CHOICES_EN)
    async def users_unban_last(
        interaction: discord.Interaction,
        quantity: int,
        unit: app_commands.Choice[str],
        reason: str | None = None,
    ) -> None:
        window, error = _resolve_last_window(quantity, unit.value)
        if window is None:
            await _send(interaction, subcommand_path="users unban last", lines=[("error", error or "Invalid window.")], kind="error")
            return
        await _run_window_batch(interaction, mode="unban", reason=reason, window=window, subcommand_path="users unban last")

    @unban_group.command(name="range", description="Revoke bans created in an explicit range.")
    @app_commands.describe(from_at="Start in DD/MM/YYYY HH:MM.", to="End in DD/MM/YYYY HH:MM.", reason="Optional reason override.")
    @app_commands.rename(from_at="from")
    async def users_unban_range(interaction: discord.Interaction, from_at: str, to: str, reason: str | None = None) -> None:
        window, error = _resolve_range_batch_window(from_at, to)
        if window is None:
            await _send(interaction, subcommand_path="users unban range", lines=[("error", error or "Invalid range.")], kind="error")
            return
        await _run_window_batch(interaction, mode="unban", reason=reason, window=window, subcommand_path="users unban range")

    users_group.add_command(unban_group)

    untempban_group = app_commands.Group(name="untempban", description="Revoke temporary bans by user or time window.")

    @untempban_group.command(name="user", description="Revoke an active temporary ban for one user.")
    @app_commands.describe(nick_or_id="Last known nickname or user ID.", reason="Optional reason override.")
    async def users_untempban_user(interaction: discord.Interaction, nick_or_id: str, reason: str | None = None) -> None:
        user = await _resolve_moderation_user(interaction, nick_or_id=nick_or_id, mode="untempban")
        if user is None:
            return
        await _unban_impl(interaction, user, reason, subcommand_path="users untempban user", success_result="temporary ban revoked")

    @untempban_group.command(name="today", description="Revoke temporary bans created today.")
    @app_commands.describe(reason="Optional reason override.")
    async def users_untempban_today(interaction: discord.Interaction, reason: str | None = None) -> None:
        await _run_window_batch(interaction, mode="untempban", reason=reason, window=resolve_oggi_window(), subcommand_path="users untempban today")

    @untempban_group.command(name="yesterday", description="Revoke temporary bans created yesterday.")
    @app_commands.describe(reason="Optional reason override.")
    async def users_untempban_yesterday(interaction: discord.Interaction, reason: str | None = None) -> None:
        await _run_window_batch(interaction, mode="untempban", reason=reason, window=resolve_ieri_window(), subcommand_path="users untempban yesterday")

    @untempban_group.command(name="last", description="Revoke temporary bans created in the last rolling window.")
    @app_commands.describe(quantity="Rolling quantity.", unit="Rolling unit.", reason="Optional reason override.")
    @app_commands.choices(unit=WINDOW_UNIT_CHOICES_EN)
    async def users_untempban_last(
        interaction: discord.Interaction,
        quantity: int,
        unit: app_commands.Choice[str],
        reason: str | None = None,
    ) -> None:
        window, error = _resolve_last_window(quantity, unit.value)
        if window is None:
            await _send(interaction, subcommand_path="users untempban last", lines=[("error", error or "Invalid window.")], kind="error")
            return
        await _run_window_batch(interaction, mode="untempban", reason=reason, window=window, subcommand_path="users untempban last")

    @untempban_group.command(name="range", description="Revoke temporary bans created in an explicit range.")
    @app_commands.describe(from_at="Start in DD/MM/YYYY HH:MM.", to="End in DD/MM/YYYY HH:MM.", reason="Optional reason override.")
    @app_commands.rename(from_at="from")
    async def users_untempban_range(interaction: discord.Interaction, from_at: str, to: str, reason: str | None = None) -> None:
        window, error = _resolve_range_batch_window(from_at, to)
        if window is None:
            await _send(interaction, subcommand_path="users untempban range", lines=[("error", error or "Invalid range.")], kind="error")
            return
        await _run_window_batch(interaction, mode="untempban", reason=reason, window=window, subcommand_path="users untempban range")

    users_group.add_command(untempban_group)

    @users_group.command(name="tempban", description="Ban a user temporarily.")
    @app_commands.describe(
        user="Member to ban temporarily.",
        quantity="Duration quantity (for example 10, 3, 7, 2).",
        unit="Duration unit.",
        reason="Optional reason override.",
    )
    @app_commands.choices(unit=WINDOW_UNIT_CHOICES)
    async def users_tempban(
        interaction: discord.Interaction,
        user: discord.Member,
        quantity: int,
        unit: app_commands.Choice[str],
        reason: str | None = None,
    ) -> None:
        await _tempban_impl(interaction, user, quantity, unit.value, reason)

    @users_group.command(name="tempban_list", description="List active temporary bans.")
    async def users_tempban_list(interaction: discord.Interaction) -> None:
        await _tempban_list_impl(interaction)

    grace_group = app_commands.Group(name="grace", description="Manual grace commands and follow-up tempban defaults.")

    @grace_group.command(name="manual", description="Assign a manual grace period to a user.")
    @app_commands.describe(
        user="Member that receives the grace period.",
        quantity="Duration quantity (for example 10, 3, 7, 2).",
        unit="Duration unit.",
        reason="Optional reason override.",
    )
    @app_commands.choices(unit=WINDOW_UNIT_CHOICES)
    async def users_grace_manual(
        interaction: discord.Interaction,
        user: discord.Member,
        quantity: int,
        unit: app_commands.Choice[str],
        reason: str | None = None,
    ) -> None:
        await _grace_impl(interaction, user, quantity, unit.value, reason)

    @grace_group.command(name="tempban_set", description="Set the default tempban applied when a manual grace expires.")
    @app_commands.describe(quantity="Duration quantity.", unit="Duration unit.")
    @app_commands.choices(unit=WINDOW_UNIT_CHOICES)
    async def users_grace_tempban_set(
        interaction: discord.Interaction,
        quantity: int,
        unit: app_commands.Choice[str],
    ) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        duration_seconds = _resolve_duration_seconds(quantity, unit.value)
        stored = await _set_users_grace_tempban_default_seconds(interaction.guild_id, duration_seconds)
        await _send(
            interaction,
            subcommand_path="users grace tempban_set",
            subtitle_args=[quantity, unit],
            lines=[("default_tempban", format_duration_human(stored)), ("result", "updated")],
            kind="success",
        )

    @grace_group.command(name="tempban_show", description="Show the default tempban applied when a manual grace expires.")
    async def users_grace_tempban_show(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        seconds = await _get_users_grace_tempban_default_seconds(interaction.guild_id)
        await _send(
            interaction,
            subcommand_path="users grace tempban_show",
            lines=[("default_tempban", format_duration_human(seconds)), ("seconds", seconds)],
        )

    @grace_group.command(name="tempban_reset", description="Disable the automatic tempban applied after manual grace.")
    async def users_grace_tempban_reset(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        stored = await _set_users_grace_tempban_default_seconds(interaction.guild_id, 0)
        await _send(
            interaction,
            subcommand_path="users grace tempban_reset",
            lines=[("default_tempban", format_duration_human(stored)), ("result", "reset")],
            kind="success",
        )

    users_group.add_command(grace_group)

    @users_group.command(name="grace_list", description="List active grace periods.")
    async def users_grace_list(interaction: discord.Interaction) -> None:
        await _grace_list_impl(interaction)

    ungrace_group = app_commands.Group(name="ungrace", description="Revoke grace periods by user or time window.")

    @ungrace_group.command(name="user", description="Revoke an active grace period for one user.")
    @app_commands.describe(nick_or_id="Last known nickname or user ID.", reason="Optional reason override.")
    async def users_ungrace_user(interaction: discord.Interaction, nick_or_id: str, reason: str | None = None) -> None:
        user = await _resolve_moderation_user(interaction, nick_or_id=nick_or_id, mode="ungrace")
        if user is None:
            return
        await _ungrace_impl(interaction, user, reason, subcommand_path="users ungrace user")

    @ungrace_group.command(name="today", description="Revoke grace periods created today.")
    @app_commands.describe(reason="Optional reason override.")
    async def users_ungrace_today(interaction: discord.Interaction, reason: str | None = None) -> None:
        await _run_window_batch(interaction, mode="ungrace", reason=reason, window=resolve_oggi_window(), subcommand_path="users ungrace today")

    @ungrace_group.command(name="yesterday", description="Revoke grace periods created yesterday.")
    @app_commands.describe(reason="Optional reason override.")
    async def users_ungrace_yesterday(interaction: discord.Interaction, reason: str | None = None) -> None:
        await _run_window_batch(interaction, mode="ungrace", reason=reason, window=resolve_ieri_window(), subcommand_path="users ungrace yesterday")

    @ungrace_group.command(name="last", description="Revoke grace periods created in the last rolling window.")
    @app_commands.describe(quantity="Rolling quantity.", unit="Rolling unit.", reason="Optional reason override.")
    @app_commands.choices(unit=WINDOW_UNIT_CHOICES_EN)
    async def users_ungrace_last(
        interaction: discord.Interaction,
        quantity: int,
        unit: app_commands.Choice[str],
        reason: str | None = None,
    ) -> None:
        window, error = _resolve_last_window(quantity, unit.value)
        if window is None:
            await _send(interaction, subcommand_path="users ungrace last", lines=[("error", error or "Invalid window.")], kind="error")
            return
        await _run_window_batch(interaction, mode="ungrace", reason=reason, window=window, subcommand_path="users ungrace last")

    @ungrace_group.command(name="range", description="Revoke grace periods created in an explicit range.")
    @app_commands.describe(from_at="Start in DD/MM/YYYY HH:MM.", to="End in DD/MM/YYYY HH:MM.", reason="Optional reason override.")
    @app_commands.rename(from_at="from")
    async def users_ungrace_range(interaction: discord.Interaction, from_at: str, to: str, reason: str | None = None) -> None:
        window, error = _resolve_range_batch_window(from_at, to)
        if window is None:
            await _send(interaction, subcommand_path="users ungrace range", lines=[("error", error or "Invalid range.")], kind="error")
            return
        await _run_window_batch(interaction, mode="ungrace", reason=reason, window=window, subcommand_path="users ungrace range")

    users_group.add_command(ungrace_group)

    if alias_commands is not None:
        def _build_alias_revocation_group(name: str, mode: str, description: str) -> app_commands.Group:
            group = app_commands.Group(name=name, description=description)

            @group.command(name="user", description="Alias of /users {mode} user.".format(mode=mode))
            @app_commands.describe(nick_or_id="Last known nickname or user ID.", reason="Optional reason override.")
            async def _alias_user(interaction: discord.Interaction, nick_or_id: str, reason: str | None = None) -> None:
                user = await _resolve_moderation_user(interaction, nick_or_id=nick_or_id, mode=mode)
                if user is None:
                    return
                if mode == "ungrace":
                    await _ungrace_impl(interaction, user, reason, subcommand_path=f"{name} user")
                    return
                await _unban_impl(
                    interaction,
                    user,
                    reason,
                    subcommand_path=f"{name} user",
                    success_result="temporary ban revoked" if mode == "untempban" else "ban revocato",
                )

            @group.command(name="oggi", description="Revoca le azioni create oggi.")
            @app_commands.describe(reason="Motivazione opzionale.")
            async def _alias_today(interaction: discord.Interaction, reason: str | None = None) -> None:
                await _run_window_batch(interaction, mode=mode, reason=reason, window=resolve_oggi_window(), subcommand_path=f"{name} oggi")

            @group.command(name="ieri", description="Revoca le azioni create ieri.")
            @app_commands.describe(reason="Motivazione opzionale.")
            async def _alias_yesterday(interaction: discord.Interaction, reason: str | None = None) -> None:
                await _run_window_batch(interaction, mode=mode, reason=reason, window=resolve_ieri_window(), subcommand_path=f"{name} ieri")

            @group.command(name="ultimi", description="Revoca le azioni create nella finestra mobile.")
            @app_commands.describe(quantita="Quantità.", unita="Unità.", reason="Motivazione opzionale.")
            @app_commands.choices(unita=WINDOW_UNIT_CHOICES)
            async def _alias_last(
                interaction: discord.Interaction,
                quantita: int,
                unita: app_commands.Choice[str],
                reason: str | None = None,
            ) -> None:
                window, error = _resolve_last_window(quantita, unita.value)
                if window is None:
                    await _send(interaction, subcommand_path=f"{name} ultimi", lines=[("error", error or "Finestra non valida.")], kind="error")
                    return
                await _run_window_batch(interaction, mode=mode, reason=reason, window=window, subcommand_path=f"{name} ultimi")

            @group.command(name="intervallo", description="Revoca le azioni create in un intervallo esplicito.")
            @app_commands.describe(da="Inizio DD/MM/YYYY HH:MM.", a="Fine DD/MM/YYYY HH:MM.", reason="Motivazione opzionale.")
            async def _alias_range(interaction: discord.Interaction, da: str, a: str, reason: str | None = None) -> None:
                window, error = _resolve_range_batch_window(da, a)
                if window is None:
                    await _send(
                        interaction,
                        subcommand_path=f"{name} intervallo",
                        lines=[("error", error or "Intervallo non valido.")],
                        kind="error",
                    )
                    return
                await _run_window_batch(interaction, mode=mode, reason=reason, window=window, subcommand_path=f"{name} intervallo")

            return group

        @app_commands.command(name="kick", description="Alias of /users kick.")
        @app_commands.describe(user="Member to kick.", reason="Optional reason override.")
        async def kick_alias(interaction: discord.Interaction, user: discord.Member, reason: str | None = None) -> None:
            await _kick_impl(interaction, user, reason)

        @app_commands.command(name="ban", description="Alias of /users ban.")
        @app_commands.describe(user="Member to ban.", reason="Optional reason override.")
        async def ban_alias(interaction: discord.Interaction, user: discord.Member, reason: str | None = None) -> None:
            await _ban_impl(interaction, user, reason)

        unban_alias_group = _build_alias_revocation_group(
            name="unban",
            mode="unban",
            description="Alias of /users unban.",
        )

        untempban_alias_group = _build_alias_revocation_group(
            name="untempban",
            mode="untempban",
            description="Alias of /users untempban.",
        )

        @app_commands.command(name="tempban", description="Alias of /users tempban.")
        @app_commands.describe(
            user="Member to ban temporarily.",
            quantity="Duration quantity (for example 10, 3, 7, 2).",
            unit="Duration unit.",
            reason="Optional reason override.",
        )
        @app_commands.choices(unit=WINDOW_UNIT_CHOICES)
        async def tempban_alias(
            interaction: discord.Interaction,
            user: discord.Member,
            quantity: int,
            unit: app_commands.Choice[str],
            reason: str | None = None,
        ) -> None:
            await _tempban_impl(interaction, user, quantity, unit.value, reason)

        @app_commands.command(name="grace", description="Alias of /users grace.")
        @app_commands.describe(
            user="Member that receives the grace period.",
            quantity="Duration quantity (for example 10, 3, 7, 2).",
            unit="Duration unit.",
            reason="Optional reason override.",
        )
        @app_commands.choices(unit=WINDOW_UNIT_CHOICES)
        async def grace_alias(
            interaction: discord.Interaction,
            user: discord.Member,
            quantity: int,
            unit: app_commands.Choice[str],
            reason: str | None = None,
        ) -> None:
            await _grace_impl(interaction, user, quantity, unit.value, reason)

        ungrace_alias_group = _build_alias_revocation_group(
            name="ungrace",
            mode="ungrace",
            description="Alias of /users ungrace.",
        )

        alias_commands.extend([kick_alias, ban_alias, unban_alias_group, tempban_alias, untempban_alias_group, grace_alias, ungrace_alias_group])
