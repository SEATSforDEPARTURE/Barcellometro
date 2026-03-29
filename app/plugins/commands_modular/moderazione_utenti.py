from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

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
from app.services.dm_template_preview import build_dm_template_preview_payload, render_dm_template_preview
from app.services.users_moderation_dms import (
    DEFAULT_USERS_DM_COOLDOWN_DAYS,
    USERS_DM_SUPPORTED_PLACEHOLDERS,
    UsersModerationDmService,
)
from app.shared.discord.command_embeds import CommandEmbedSection, build_command_embeds, send_command_embeds, send_standard_response

logger = logging.getLogger(__name__)

PERM = "users"
WINDOW_UNIT_CHOICES = [
    app_commands.Choice(name="secondi", value="secondi"),
    app_commands.Choice(name="minuti", value="minuti"),
    app_commands.Choice(name="ore", value="ore"),
    app_commands.Choice(name="giorni", value="giorni"),
    app_commands.Choice(name="settimane", value="settimane"),
]
WINDOW_UNIT_CHOICES_EN = [
    app_commands.Choice(name="seconds", value="secondi"),
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
USERS_DM_TEMPLATE_HELP = (
    "Supported placeholders: "
    + ", ".join(f"{{{name}}}" for name in USERS_DM_SUPPORTED_PLACEHOLDERS)
    + ". Example: {mention}, {expires_at_utc}, {expires_at_it}."
)
ROME_TZ = ZoneInfo("Europe/Rome")


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


_MENTION_RE = re.compile(r"^<@!?(\d+)>$")


def resolve_target_user(value: discord.Member | str, guild: discord.Guild) -> discord.Member | None:
    if isinstance(value, discord.Member):
        return value
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    mention_match = _MENTION_RE.fullmatch(raw_value)
    if mention_match:
        raw_value = mention_match.group(1)
    try:
        user_id = int(raw_value)
    except (TypeError, ValueError):
        return None
    return guild.get_member(user_id)


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


def _parse_iso_datetime(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_italian_datetime(value: object) -> str | None:
    dt = _parse_iso_datetime(value)
    if dt is None:
        return None
    return dt.astimezone(ROME_TZ).strftime("%d/%m/%Y %H:%M")


def _render_users_dm_template_preview(template: str, *, event_type: str = "tempban") -> str:
    safe_event_type = str(event_type or "").strip().lower() or "tempban"
    preview_presets: dict[str, dict[str, object]] = {
        "tempban": {
            "event_type": "tempban",
            "reason": "Automatic tempban after manual grace expiry",
            "duration_seconds": 2 * 86400,
            "extra_payload": {"reasoning": "users_manual_grace_expired_tempban"},
        },
        "kick": {
            "event_type": "kick",
            "reason": "Repeated abusive language",
            "duration_seconds": 0,
        },
        "ban": {
            "event_type": "ban",
            "reason": "Severe harassment",
            "duration_seconds": 0,
        },
        "grace": {
            "event_type": "grace",
            "reason": "Final warning before temporary ban",
            "duration_seconds": 2 * 86400,
        },
    }
    payload = build_dm_template_preview_payload(**preview_presets.get(safe_event_type, preview_presets["tempban"]))
    return render_dm_template_preview(template, payload)


def _fmt_utc(ts: object) -> str:
    if not ts:
        return "n/a"
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return str(ts)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _resolve_cooldown_seconds_from_users_cfg(cfg: dict[str, object]) -> int:
    if cfg.get("cooldown_seconds") is not None:
        return max(0, int(cfg.get("cooldown_seconds") or 0))
    return max(0, int(cfg.get("cooldown_days", DEFAULT_USERS_DM_COOLDOWN_DAYS) or DEFAULT_USERS_DM_COOLDOWN_DAYS) * 86400)


def _cooldown_seconds_to_quantity_unit(total_seconds: int) -> tuple[int, str]:
    seconds = max(0, int(total_seconds))
    if seconds == 0:
        return 0, "secondi"
    for unit, factor in (("settimane", 7 * 24 * 3600), ("giorni", 24 * 3600), ("ore", 3600), ("minuti", 60)):
        if seconds % factor == 0:
            return seconds // factor, unit
    return seconds, "secondi"


def _format_cooldown_label(total_seconds: int) -> str:
    seconds = max(0, int(total_seconds))
    if seconds == 0:
        return "disabled (0 seconds)"
    quantity, unit = _cooldown_seconds_to_quantity_unit(seconds)
    return f"{quantity} {unit}"


def _format_moderation_list_line(
    row: dict | object,
    *,
    list_kind: str,
    grace_post_tempban_seconds: int = 0,
) -> str:
    def _row_value(key: str) -> object:
        if isinstance(row, dict):
            return row.get(key)
        return row[key]

    user_id = str(_row_value("user_id") or "").strip()
    user_label = f"<@{user_id}>" if user_id else "utente sconosciuto"
    created_label = _format_italian_datetime(_row_value("created_at"))
    expires_label = _format_italian_datetime(_row_value("expires_at"))
    action_type = str(_row_value("action_type") or "").strip()

    parts = [user_label]
    if list_kind == "kick":
        event_label = _render_departure_action_label(action_type or "kick")
        parts.append(f"evento: {event_label}")
        if created_label:
            parts.append(f"avvenuto il {created_label}")
    elif list_kind == "ban":
        parts.append("evento: ban")
        if created_label:
            parts.append(f"avvenuto il {created_label}")
    elif list_kind == "tempban":
        parts.append("evento: tempban")
        if created_label:
            parts.append(f"avvenuto il {created_label}")
        if expires_label:
            parts.append(f"scade il {expires_label}")
    elif list_kind == "grace":
        parts.append("evento: grace")
        if created_label:
            parts.append(f"grace iniziato il {created_label}")
        if expires_label:
            parts.append(f"grace scade il {expires_label}")
        if grace_post_tempban_seconds > 0:
            parts.append(f"tempban successivo: {format_duration_human(grace_post_tempban_seconds)}")
            expires_dt = _parse_iso_datetime(_row_value("expires_at"))
            if expires_dt is not None:
                post_tempban_expiry = (expires_dt + timedelta(seconds=grace_post_tempban_seconds)).astimezone(ROME_TZ)
                parts.append(f"tempban previsto fino al {post_tempban_expiry.strftime('%d/%m/%Y %H:%M')}")

    return f"• {' · '.join(parts)}"


def register_moderazione_utenti(
    users_group: app_commands.Group,
    ctx: CommandContext,
    *,
    top_level: str = "users",
    visual_top_level: str = "users",
    alias_commands: list[app_commands.Command] | None = None,
) -> None:
    greetings_copy_service = GreetingsCopyService(ctx.database, barcello_service=getattr(ctx, "barcello_service", None))
    users_dm_service = UsersModerationDmService(
        ctx.database,
        bot=getattr(ctx, "bot", None) or getattr(ctx, "client", None),
    )

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

    def _render_dm_delivery_status(dm_result: dict[str, object] | None) -> str:
        payload = dm_result or {}
        if bool(payload.get("sent")):
            if str(payload.get("fallback") or "").strip().lower() == "text":
                return "delivered (text fallback)"
            return "delivered"
        skipped = str(payload.get("skipped") or "").strip()
        if skipped == "error":
            error_name = str(payload.get("error") or "error").strip() or "error"
            return f"failed ({error_name})"
        if skipped:
            return f"skipped ({skipped})"
        return "failed (unknown)"

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
        dm_result = await users_dm_service.send_for_event(
            guild=interaction.guild,
            user=user,
            event_type="kick",
            reason=resolved_reason,
            metadata={"source": "users_kick_manual", "operation_id": operation_id},
        )
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
            lines=[("user", user.mention), ("result", "allontanato"), ("reason", resolved_reason), ("dm", _render_dm_delivery_status(dm_result))],
            kind="success",
        )

    async def _kick_list_impl(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        rows = await ctx.database.list_recent_kicked_users(str(interaction.guild_id))
        lines = [_format_moderation_list_line(row, list_kind="kick") for row in rows]
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
        dm_result = await users_dm_service.send_for_event(
            guild=interaction.guild,
            user=user,
            event_type="ban",
            reason=resolved_reason,
            metadata={"source": "users_ban_manual", "operation_id": operation_id},
        )
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
            lines=[("user", user.mention), ("result", "banned"), ("reason", resolved_reason), ("dm", _render_dm_delivery_status(dm_result))],
            kind="success",
        )

    async def _ban_list_impl(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        rows = await ctx.database.list_active_bans(str(interaction.guild_id))
        lines = [_format_moderation_list_line(row, list_kind="ban") for row in rows]
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

    async def _ensure_users_dm_cfg(guild_id: str) -> dict[str, object]:
        row = await ctx.database.get_users_dm_config(guild_id)
        if row is None:
            await ctx.database.upsert_users_dm_config(guild_id)
            row = await ctx.database.get_users_dm_config(guild_id)
        return dict(row) if row else {}

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
        dm_result = await users_dm_service.send_for_event(
            guild=interaction.guild,
            user=user,
            event_type="tempban",
            duration_seconds=duration_seconds,
            expires_at=expires_at,
            reason=resolved_reason,
            reasoning="users_manual_tempban_direct",
            metadata={"source": "users_tempban_manual", "operation_id": operation_id},
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
                ("dm", _render_dm_delivery_status(dm_result)),
            ],
            kind="success",
        )

    async def _tempban_list_impl(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        rows = await ctx.database.list_active_tempbans(str(interaction.guild_id))
        lines = [_format_moderation_list_line(row, list_kind="tempban") for row in rows]
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
        dm_result = await users_dm_service.send_for_event(
            guild=interaction.guild,
            user=user,
            event_type="grace",
            duration_seconds=duration_seconds,
            expires_at=expires_at,
            reason=resolved_reason,
            metadata={"source": "users_grace_manual"},
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
                ("dm", _render_dm_delivery_status(dm_result)),
            ],
            kind="success",
        )

    async def _grace_list_impl(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        rows = await ctx.database.list_active_grace_users(str(interaction.guild_id))
        post_grace_tempban_seconds = await _get_users_grace_tempban_default_seconds(interaction.guild_id)
        lines = [
            _format_moderation_list_line(
                row,
                list_kind="grace",
                grace_post_tempban_seconds=post_grace_tempban_seconds,
            )
            for row in rows
        ]
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

    async def _resolve_live_member(
        interaction: discord.Interaction,
        *,
        nick_or_id: discord.Member | str,
        mode: str,
    ) -> discord.Member | None:
        raw_value = str(nick_or_id or "").strip()
        if isinstance(nick_or_id, str) and not raw_value:
            await _send(
                interaction,
                subcommand_path=f"users {mode}",
                lines=[("error", "Inserisci un ID utente, una mention o un nickname.")],
                kind="error",
            )
            return None
        guild = interaction.guild
        if guild is None:
            await _send(
                interaction,
                subcommand_path=f"users {mode}",
                lines=[("error", "Usa questo comando in un server.")],
                kind="error",
            )
            return None

        resolved = resolve_target_user(nick_or_id, guild)
        if resolved is not None:
            return resolved

        if isinstance(nick_or_id, str) and re.fullmatch(r"\d+", raw_value):
            member: discord.Member | None = None
            if hasattr(guild, "fetch_member"):
                try:
                    member = await guild.fetch_member(int(raw_value))
                except (discord.NotFound, discord.HTTPException):
                    member = None
            if member is not None:
                return member
            await _send(
                interaction,
                subcommand_path=f"users {mode}",
                lines=[("error", f"Nessun membro trovato con ID {raw_value}.")],
                kind="error",
            )
            return None

        target_key = _normalize_lookup_key(raw_value)
        members = list(getattr(guild, "members", []) or [])
        matches: list[discord.Member] = []
        for candidate in members:
            candidate_names = (
                str(getattr(candidate, "display_name", "") or "").strip(),
                str(getattr(candidate, "nick", "") or "").strip(),
                str(getattr(candidate, "global_name", "") or "").strip(),
                str(getattr(candidate, "name", "") or "").strip(),
            )
            keys = {_normalize_lookup_key(value) for value in candidate_names if value}
            if target_key in keys:
                matches.append(candidate)
        if not matches:
            await _send(
                interaction,
                subcommand_path=f"users {mode}",
                lines=[("error", f"Nessun membro trovato per '{nick_or_id}'. Usa ID o mention.")],
                kind="error",
            )
            return None
        if len(matches) > 1:
            hints = ", ".join(f"{candidate.display_name} (ID {candidate.id})" for candidate in matches[:5])
            await _send(
                interaction,
                subcommand_path=f"users {mode}",
                lines=[
                    ("error", f"Nickname ambiguo: '{nick_or_id}'."),
                    ("matches", hints),
                    ("hint", "Specifica l'ID utente."),
                ],
                kind="error",
            )
            return None
        return matches[0]

    @users_group.command(name="kick", description="Remove a user from the server.")
    @app_commands.describe(nick_or_id="Member ID, mention, or nickname.", reason="Optional reason override.")
    async def users_kick(interaction: discord.Interaction, nick_or_id: discord.Member, reason: str | None = None) -> None:
        user = await _resolve_live_member(interaction, nick_or_id=nick_or_id, mode="kick")
        if user is None:
            return
        await _kick_impl(interaction, user, reason)

    @users_group.command(name="kick_list", description="List recent user removals.")
    async def users_kick_list(interaction: discord.Interaction) -> None:
        await _kick_list_impl(interaction)

    @users_group.command(name="ban", description="Ban a user permanently.")
    @app_commands.describe(nick_or_id="Member ID, mention, or nickname.", reason="Optional reason override.")
    async def users_ban(interaction: discord.Interaction, nick_or_id: discord.Member, reason: str | None = None) -> None:
        user = await _resolve_live_member(interaction, nick_or_id=nick_or_id, mode="ban")
        if user is None:
            return
        await _ban_impl(interaction, user, reason)

    @users_group.command(name="ban_list", description="List active permanent bans.")
    async def users_ban_list(interaction: discord.Interaction) -> None:
        await _ban_list_impl(interaction)

    def _resolve_last_window(quantita: int, unita: str) -> tuple[TimeWindowResult | None, str | None]:
        return resolve_ultimi_window(quantita, unita, ctx.config)

    def _resolve_range_batch_window(start_at: str, end_at: str) -> tuple[TimeWindowResult | None, str | None]:
        return resolve_range_window(start_at, end_at, ctx.config)

    unban_group = app_commands.Group(name="unban", description="Revoke bans by time window.")

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

    untempban_group = app_commands.Group(name="untempban", description="Revoke temporary bans by time window.")

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
        nick_or_id="Member ID, mention, or nickname.",
        quantity="Duration quantity (for example 10, 3, 7, 2).",
        unit="Duration unit.",
        reason="Optional reason override.",
    )
    @app_commands.choices(unit=WINDOW_UNIT_CHOICES)
    async def users_tempban(
        interaction: discord.Interaction,
        nick_or_id: discord.Member,
        quantity: int,
        unit: app_commands.Choice[str],
        reason: str | None = None,
    ) -> None:
        user = await _resolve_live_member(interaction, nick_or_id=nick_or_id, mode="tempban")
        if user is None:
            return
        await _tempban_impl(interaction, user, quantity, unit.value, reason)

    @users_group.command(name="tempban_list", description="List active temporary bans.")
    async def users_tempban_list(interaction: discord.Interaction) -> None:
        await _tempban_list_impl(interaction)

    dms_group = app_commands.Group(name="dms", description="Direct message settings for manual grace and automatic tempban.")

    @dms_group.command(name="on", description="Enable USERS DMs for manual grace and auto-tempban.")
    async def users_dms_on(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.set_users_dm_enabled(str(interaction.guild_id), True)
        await _send(interaction, subcommand_path="users dms on", lines=[("result", "enabled"), ("dms", "on")], kind="success")

    @dms_group.command(name="off", description="Disable USERS DMs for manual grace and auto-tempban.")
    async def users_dms_off(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.set_users_dm_enabled(str(interaction.guild_id), False)
        await _send(interaction, subcommand_path="users dms off", lines=[("result", "disabled"), ("dms", "off")], kind="success")

    @dms_group.command(name="status", description="Show USERS DM status and delivery metrics.")
    async def users_dms_status(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        guild_id = str(interaction.guild_id)
        cfg = await _ensure_users_dm_cfg(guild_id)
        stats = await ctx.database.get_users_dm_delivery_stats(guild_id)
        recent_rows = await ctx.database.list_users_dm_delivery_events(guild_id, limit=5)
        by_event = stats.get("by_event") or []
        event_summary = ", ".join(f"{row['event_type']}={row['total']}" for row in by_event) if by_event else "none"
        latest_success = stats.get("latest_success") or {}
        latest_fail = stats.get("latest_fail") or {}
        recent_lines = [
            f"{_fmt_utc(row['sent_at'])} · user={row['user_id']} · event={row['event_type']} · outcome={row['outcome']}"
            + (f" · reason={row['reason']}" if row["reason"] else "")
            + (f" · error={row['error_summary']}" if row["error_summary"] else "")
            for row in recent_rows
        ]
        await _send(
            interaction,
            subcommand_path="users dms status",
            lines=[
                ("dms", "on" if bool(cfg.get("enabled", 1)) else "off"),
                ("template_grace", cfg.get("grace_template") or "not set"),
                ("template_tempban", cfg.get("tempban_template") or "not set"),
                ("template_kick", cfg.get("kick_template") or "not set"),
                ("template_ban", cfg.get("ban_template") or "not set"),
                ("cooldown", _format_cooldown_label(_resolve_cooldown_seconds_from_users_cfg(cfg))),
                ("cooldown_seconds", _resolve_cooldown_seconds_from_users_cfg(cfg)),
                ("cooldown_disabled", "yes" if _resolve_cooldown_seconds_from_users_cfg(cfg) == 0 else "no"),
                ("invite_url", cfg.get("invite_url") or "not set"),
                ("dm_sent_ok", int(stats.get("ok", 0))),
                ("dm_sent_fail", int(stats.get("fail", 0))),
                ("dm_sent_skipped", int(stats.get("skipped", 0))),
                ("dm_events_total", int(stats.get("total", 0))),
                ("dm_events_by_type", event_summary),
                ("last_success", f"user={latest_success.get('user_id', 'n/a')} at {_fmt_utc(latest_success.get('sent_at'))} reason={latest_success.get('reason') or 'n/a'}"),
                ("last_fail", f"user={latest_fail.get('user_id', 'n/a')} at {_fmt_utc(latest_fail.get('sent_at'))} reason={latest_fail.get('reason') or 'n/a'} error={latest_fail.get('error_summary') or 'n/a'}"),
            ],
            sections=[
                CommandEmbedSection(title="Recent DM deliveries", lines=recent_lines or ["No DM deliveries logged yet."]),
                CommandEmbedSection(
                    title="Supported placeholders",
                    lines=[f"{{{name}}}" for name in USERS_DM_SUPPORTED_PLACEHOLDERS],
                ),
            ],
        )

    @dms_group.command(name="template_grace_set", description="Set the DM template for manual grace entry.")
    @app_commands.describe(text=USERS_DM_TEMPLATE_HELP)
    async def users_dms_template_grace_set(interaction: discord.Interaction, text: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_users_dm_config(str(interaction.guild_id), grace_template=text)
        await _send(interaction, subcommand_path="users dms template_grace_set", lines=[("result", "updated")], kind="success")

    @dms_group.command(name="template_grace_show", description="Show the DM template for manual grace entry.")
    async def users_dms_template_grace_show(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await _ensure_users_dm_cfg(str(interaction.guild_id))
        template = str(cfg.get("grace_template") or "")
        preview = _render_users_dm_template_preview(template, event_type="grace") if template else "No custom template configured."
        await _send(
            interaction,
            subcommand_path="users dms template_grace_show",
            lines=[("template_grace", template or "not set")],
            sections=[CommandEmbedSection(title="Preview", lines=[preview])],
        )

    @dms_group.command(name="template_grace_reset", description="Reset the DM template for manual grace entry.")
    async def users_dms_template_grace_reset(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_users_dm_config(str(interaction.guild_id), grace_template=None)
        await _send(interaction, subcommand_path="users dms template_grace_reset", lines=[("result", "reset")], kind="success")

    @dms_group.command(name="template_tempban_set", description="Set the DM template for auto-tempban after manual grace.")
    @app_commands.describe(text=USERS_DM_TEMPLATE_HELP)
    async def users_dms_template_tempban_set(interaction: discord.Interaction, text: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_users_dm_config(str(interaction.guild_id), tempban_template=text)
        await _send(interaction, subcommand_path="users dms template_tempban_set", lines=[("result", "updated")], kind="success")

    @dms_group.command(name="template_tempban_show", description="Show the DM template for auto-tempban after manual grace.")
    async def users_dms_template_tempban_show(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await _ensure_users_dm_cfg(str(interaction.guild_id))
        template = str(cfg.get("tempban_template") or "")
        preview = _render_users_dm_template_preview(template, event_type="tempban") if template else "No custom template configured."
        await _send(
            interaction,
            subcommand_path="users dms template_tempban_show",
            lines=[("template_tempban", template or "not set")],
            sections=[CommandEmbedSection(title="Preview", lines=[preview])],
        )

    @dms_group.command(name="template_tempban_reset", description="Reset the DM template for auto-tempban after manual grace.")
    async def users_dms_template_tempban_reset(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_users_dm_config(str(interaction.guild_id), tempban_template=None)
        await _send(interaction, subcommand_path="users dms template_tempban_reset", lines=[("result", "reset")], kind="success")

    @dms_group.command(name="template_kick_set", description="Set the DM template for kick events.")
    @app_commands.describe(text=USERS_DM_TEMPLATE_HELP)
    async def users_dms_template_kick_set(interaction: discord.Interaction, text: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_users_dm_config(str(interaction.guild_id), kick_template=text)
        await _send(interaction, subcommand_path="users dms template_kick_set", lines=[("result", "updated")], kind="success")

    @dms_group.command(name="template_kick_show", description="Show the DM template for kick events.")
    async def users_dms_template_kick_show(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await _ensure_users_dm_cfg(str(interaction.guild_id))
        template = str(cfg.get("kick_template") or "")
        preview = _render_users_dm_template_preview(template, event_type="kick") if template else "No custom template configured."
        await _send(
            interaction,
            subcommand_path="users dms template_kick_show",
            lines=[("template_kick", template or "not set")],
            sections=[CommandEmbedSection(title="Preview", lines=[preview])],
        )

    @dms_group.command(name="template_kick_reset", description="Reset the DM template for kick events.")
    async def users_dms_template_kick_reset(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_users_dm_config(str(interaction.guild_id), kick_template=None)
        await _send(interaction, subcommand_path="users dms template_kick_reset", lines=[("result", "reset")], kind="success")

    @dms_group.command(name="template_ban_set", description="Set the DM template for ban events.")
    @app_commands.describe(text=USERS_DM_TEMPLATE_HELP)
    async def users_dms_template_ban_set(interaction: discord.Interaction, text: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_users_dm_config(str(interaction.guild_id), ban_template=text)
        await _send(interaction, subcommand_path="users dms template_ban_set", lines=[("result", "updated")], kind="success")

    @dms_group.command(name="template_ban_show", description="Show the DM template for ban events.")
    async def users_dms_template_ban_show(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await _ensure_users_dm_cfg(str(interaction.guild_id))
        template = str(cfg.get("ban_template") or "")
        preview = _render_users_dm_template_preview(template, event_type="ban") if template else "No custom template configured."
        await _send(
            interaction,
            subcommand_path="users dms template_ban_show",
            lines=[("template_ban", template or "not set")],
            sections=[CommandEmbedSection(title="Preview", lines=[preview])],
        )

    @dms_group.command(name="template_ban_reset", description="Reset the DM template for ban events.")
    async def users_dms_template_ban_reset(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_users_dm_config(str(interaction.guild_id), ban_template=None)
        await _send(interaction, subcommand_path="users dms template_ban_reset", lines=[("result", "reset")], kind="success")

    @dms_group.command(name="cooldown_set", description="Set the DM cooldown for USERS contexts.")
    @app_commands.describe(quantity="Cooldown quantity.", unit="Cooldown unit.")
    @app_commands.choices(unit=WINDOW_UNIT_CHOICES)
    async def users_dms_cooldown_set(
        interaction: discord.Interaction,
        quantity: app_commands.Range[int, 0, 1000000],
        unit: app_commands.Choice[str],
    ) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cooldown_seconds = int(rolling_window_timedelta(int(quantity), unit.value).total_seconds()) if int(quantity) > 0 else 0
        await ctx.database.upsert_users_dm_config(str(interaction.guild_id), cooldown_seconds=cooldown_seconds)
        await _send(
            interaction,
            subcommand_path="users dms cooldown_set",
            subtitle_args=[quantity, unit],
            lines=[
                ("cooldown", _format_cooldown_label(cooldown_seconds)),
                ("cooldown_seconds", cooldown_seconds),
                ("cooldown_disabled", "yes" if cooldown_seconds == 0 else "no"),
                ("result", "updated"),
            ],
            kind="success",
        )

    @dms_group.command(name="cooldown_show", description="Show the DM cooldown for USERS contexts.")
    async def users_dms_cooldown_show(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await _ensure_users_dm_cfg(str(interaction.guild_id))
        cooldown_seconds = _resolve_cooldown_seconds_from_users_cfg(cfg)
        quantity, unit = _cooldown_seconds_to_quantity_unit(cooldown_seconds)
        await _send(
            interaction,
            subcommand_path="users dms cooldown_show",
            lines=[
                ("cooldown", _format_cooldown_label(cooldown_seconds)),
                ("quantity", quantity),
                ("unit", unit),
                ("cooldown_seconds", cooldown_seconds),
                ("cooldown_disabled", "yes" if cooldown_seconds == 0 else "no"),
            ],
        )

    @dms_group.command(name="cooldown_reset", description="Reset the DM cooldown for USERS contexts.")
    async def users_dms_cooldown_reset(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_users_dm_config(str(interaction.guild_id), cooldown_seconds=0)
        await _send(
            interaction,
            subcommand_path="users dms cooldown_reset",
            lines=[("cooldown", "disabled (0 seconds)"), ("cooldown_seconds", 0), ("cooldown_disabled", "yes"), ("result", "reset_to_disabled")],
            kind="success",
        )

    @dms_group.command(name="invite_set", description="Set the invite link used in USERS DMs.")
    @app_commands.describe(url="Invite URL included in USERS DMs.")
    async def users_dms_invite_set(interaction: discord.Interaction, url: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_users_dm_config(str(interaction.guild_id), invite_url=url)
        await _send(interaction, subcommand_path="users dms invite_set", lines=[("invite_url", url), ("result", "updated")], kind="success")

    @dms_group.command(name="invite_show", description="Show the invite link used in USERS DMs.")
    async def users_dms_invite_show(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await _ensure_users_dm_cfg(str(interaction.guild_id))
        await _send(interaction, subcommand_path="users dms invite_show", lines=[("invite_url", cfg.get("invite_url") or "not set")])

    @dms_group.command(name="invite_reset", description="Reset the invite link used in USERS DMs.")
    async def users_dms_invite_reset(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_users_dm_config(str(interaction.guild_id), invite_url=None)
        await _send(interaction, subcommand_path="users dms invite_reset", lines=[("result", "reset")], kind="success")

    users_group.add_command(dms_group)

    grace_group = app_commands.Group(name="grace", description="Manual grace commands and follow-up tempban defaults.")

    @grace_group.command(name="manual", description="Assign a manual grace period to a user.")
    @app_commands.describe(
        nick_or_id="Member ID, mention, or nickname.",
        quantity="Duration quantity (for example 10, 3, 7, 2).",
        unit="Duration unit.",
        reason="Optional reason override.",
    )
    @app_commands.choices(unit=WINDOW_UNIT_CHOICES)
    async def users_grace_manual(
        interaction: discord.Interaction,
        nick_or_id: discord.Member,
        quantity: int,
        unit: app_commands.Choice[str],
        reason: str | None = None,
    ) -> None:
        user = await _resolve_live_member(interaction, nick_or_id=nick_or_id, mode="grace")
        if user is None:
            return
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

    ungrace_group = app_commands.Group(name="ungrace", description="Revoke grace periods by time window.")

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

            @group.command(name="oggi", description="Revoca le azioni create oggi.")
            @app_commands.describe(motivo="Motivazione opzionale.")
            async def _alias_today(interaction: discord.Interaction, motivo: str | None = None) -> None:
                await _run_window_batch(interaction, mode=mode, reason=motivo, window=resolve_oggi_window(), subcommand_path=f"{name} oggi")

            @group.command(name="ieri", description="Revoca le azioni create ieri.")
            @app_commands.describe(motivo="Motivazione opzionale.")
            async def _alias_yesterday(interaction: discord.Interaction, motivo: str | None = None) -> None:
                await _run_window_batch(interaction, mode=mode, reason=motivo, window=resolve_ieri_window(), subcommand_path=f"{name} ieri")

            @group.command(name="ultimi", description="Revoca le azioni create nella finestra mobile.")
            @app_commands.describe(quantità="Quantità.", unità="Unità.", motivo="Motivazione opzionale.")
            @app_commands.rename(quantità="quantity", unità="unit")
            @app_commands.choices(unità=WINDOW_UNIT_CHOICES)
            async def _alias_last(
                interaction: discord.Interaction,
                quantità: int,
                unità: app_commands.Choice[str],
                motivo: str | None = None,
            ) -> None:
                window, error = _resolve_last_window(quantità, unità.value)
                if window is None:
                    await _send(interaction, subcommand_path=f"{name} ultimi", lines=[("error", error or "Finestra non valida.")], kind="error")
                    return
                await _run_window_batch(interaction, mode=mode, reason=motivo, window=window, subcommand_path=f"{name} ultimi")

            @group.command(name="range", description="Revoca le azioni create in un intervallo esplicito.")
            @app_commands.describe(da="Inizio DD/MM/YYYY HH:MM.", a="Fine DD/MM/YYYY HH:MM.", motivo="Motivazione opzionale.")
            async def _alias_range(interaction: discord.Interaction, da: str, a: str, motivo: str | None = None) -> None:
                window, error = _resolve_range_batch_window(da, a)
                if window is None:
                    await _send(
                        interaction,
                        subcommand_path=f"{name} range",
                        lines=[("error", error or "Intervallo non valido.")],
                        kind="error",
                    )
                    return
                await _run_window_batch(interaction, mode=mode, reason=motivo, window=window, subcommand_path=f"{name} range")

            return group

        @app_commands.command(name="kick", description="Alias of /users kick.")
        @app_commands.describe(nick_o_id="ID membro, mention o nickname.", motivo="Motivo opzionale.")
        async def kick_alias(interaction: discord.Interaction, nick_o_id: discord.Member, motivo: str | None = None) -> None:
            user = await _resolve_live_member(interaction, nick_or_id=nick_o_id, mode="kick")
            if user is None:
                return
            await _kick_impl(interaction, user, motivo)

        @app_commands.command(name="ban", description="Alias of /users ban.")
        @app_commands.describe(nick_o_id="ID membro, mention o nickname.", motivo="Motivo opzionale.")
        async def ban_alias(interaction: discord.Interaction, nick_o_id: discord.Member, motivo: str | None = None) -> None:
            user = await _resolve_live_member(interaction, nick_or_id=nick_o_id, mode="ban")
            if user is None:
                return
            await _ban_impl(interaction, user, motivo)

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
            nick_o_id="ID membro, mention o nickname.",
            quantità="Quantità durata (esempio 10, 3, 7, 2).",
            unità="Unità durata.",
            motivo="Motivo opzionale.",
        )
        @app_commands.rename(quantità="quantity", unità="unit")
        @app_commands.choices(unità=WINDOW_UNIT_CHOICES)
        async def tempban_alias(
            interaction: discord.Interaction,
            nick_o_id: discord.Member,
            quantità: int,
            unità: app_commands.Choice[str],
            motivo: str | None = None,
        ) -> None:
            user = await _resolve_live_member(interaction, nick_or_id=nick_o_id, mode="tempban")
            if user is None:
                return
            await _tempban_impl(interaction, user, quantità, unità.value, motivo)

        @app_commands.command(name="grace", description="Alias of /users grace.")
        @app_commands.describe(
            nick_o_id="ID membro, mention o nickname.",
            quantità="Quantità durata (esempio 10, 3, 7, 2).",
            unità="Unità durata.",
            motivo="Motivo opzionale.",
        )
        @app_commands.rename(quantità="quantity", unità="unit")
        @app_commands.choices(unità=WINDOW_UNIT_CHOICES)
        async def grace_alias(
            interaction: discord.Interaction,
            nick_o_id: discord.Member,
            quantità: int,
            unità: app_commands.Choice[str],
            motivo: str | None = None,
        ) -> None:
            user = await _resolve_live_member(interaction, nick_or_id=nick_o_id, mode="grace")
            if user is None:
                return
            await _grace_impl(interaction, user, quantità, unità.value, motivo)

        ungrace_alias_group = _build_alias_revocation_group(
            name="ungrace",
            mode="ungrace",
            description="Alias of /users ungrace.",
        )

        alias_commands.extend([kick_alias, ban_alias, unban_alias_group, tempban_alias, untempban_alias_group, grace_alias, ungrace_alias_group])
