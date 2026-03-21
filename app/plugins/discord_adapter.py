from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

import discord

from app.core.service_registry import ServiceRegistry
from app.services.backfill import BackfillResult
from app.services.ingest import EventEnvelope, IngestService
from app.shared.safety.pii import redact_pii

logger = logging.getLogger(__name__)
_DISCORD_NATIVE_MOD_AUDIT_WINDOW_SECONDS = 15
_DISCORD_NATIVE_MOD_AUDIT_ATTEMPTS = 3
_DISCORD_NATIVE_MOD_AUDIT_RETRY_SECONDS = 0.75


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bool_int(value: bool) -> int:
    return 1 if value else 0


def _normalize_optional_reason(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _build_native_moderation_operation_id(
    *,
    guild_id: str,
    user_id: str,
    action_type: str,
    entry_id: Any,
    created_at: Any,
) -> str | None:
    entry_text = str(entry_id or "").strip()
    if entry_text:
        return f"discord_native:{guild_id}:{action_type}:{entry_text}"
    created_text = str(created_at or "").strip()
    if created_text:
        return f"discord_native:{guild_id}:{action_type}:{user_id}:{created_text}"
    return None


def setup(registry: ServiceRegistry) -> None:
    bot: discord.Client = registry.get("bot")
    database = registry.get("database")
    ingest: IngestService = registry.get("ingest")
    trigger_engine = registry.get("trigger_engine") if registry.has("trigger_engine") else None
    backfill = registry.get("backfill") if registry.has("backfill") else None
    config = registry.get("config")
    aura_rolling = registry.get("aura_rolling") if registry.has("aura_rolling") else None
    member_flow_notifications = registry.get("member_flow_notifications") if registry.has("member_flow_notifications") else None
    warned_disabled_channels: set[str] = set()
    channel_runtime_fingerprint: dict[str, tuple[str, str, str | None, int, int]] = {}
    voice_event_dedupe: dict[tuple[str, str, str, str | None, str | None], datetime] = {}

    def _get_audit_action(action_name: str) -> Any | None:
        audit_enum = getattr(discord, "AuditLogAction", None)
        return getattr(audit_enum, action_name, None) if audit_enum is not None else None

    def _normalize_audit_timestamp(value: Any) -> datetime | None:
        if not isinstance(value, datetime):
            return None
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    async def _fetch_recent_audit_entry(
        guild: discord.Guild,
        *,
        action_name: str,
        target_id: str,
        window_seconds: int = _DISCORD_NATIVE_MOD_AUDIT_WINDOW_SECONDS,
    ) -> dict[str, Any] | None:
        action = _get_audit_action(action_name)
        audit_logs = getattr(guild, "audit_logs", None)
        if action is None or audit_logs is None:
            return None
        try:
            async for entry in audit_logs(limit=6, action=action):
                entry_target = getattr(entry, "target", None)
                if str(getattr(entry_target, "id", "")) != target_id:
                    continue
                created_at = _normalize_audit_timestamp(getattr(entry, "created_at", None))
                if created_at is not None and (datetime.now(timezone.utc) - created_at) > timedelta(seconds=window_seconds):
                    continue
                moderator = getattr(entry, "user", None)
                return {
                    "entry_id": str(getattr(entry, "id", "")) or None,
                    "reason": str(getattr(entry, "reason", "")).strip() or None,
                    "moderator_id": str(getattr(moderator, "id", "")) or None,
                    "moderator": moderator,
                    "created_at": created_at.isoformat() if created_at is not None else None,
                    "action_type": "ban" if action_name == "ban" else "kick",
                }
        except (discord.Forbidden, discord.HTTPException):
            logger.info("Native moderation audit log unavailable guild=%s action=%s", guild.id, action_name, exc_info=True)
        except Exception:
            logger.warning("Native moderation audit log lookup failed guild=%s action=%s", guild.id, action_name, exc_info=True)
        return None

    async def _resolve_native_departure(member: discord.Member) -> dict[str, Any] | None:
        guild_id = str(member.guild.id)
        user_id = str(member.id)
        recent_departure_getter = getattr(member_flow_notifications, "get_recent_departure_action", None)
        if recent_departure_getter is not None:
            recent_action = recent_departure_getter(guild_id, user_id)
            if recent_action in {"ban", "kick", "tempban", "inactive_kick", "inactive_tempban"}:
                action_type = "ban" if recent_action in {"ban", "tempban", "inactive_tempban"} else "kick"
                return {
                    "action_type": action_type,
                    "reason": None,
                    "moderator_id": None,
                    "moderator": None,
                    "entry_id": None,
                    "created_at": None,
                    "source": "departure_memory",
                    "skip_logging": True,
                }

        for attempt in range(_DISCORD_NATIVE_MOD_AUDIT_ATTEMPTS):
            ban_match = await _fetch_recent_audit_entry(member.guild, action_name="ban", target_id=user_id)
            if ban_match is not None:
                return {**ban_match, "source": "audit_log", "skip_logging": False}
            kick_match = await _fetch_recent_audit_entry(member.guild, action_name="kick", target_id=user_id)
            if kick_match is not None:
                return {**kick_match, "source": "audit_log", "skip_logging": False}
            if attempt + 1 < _DISCORD_NATIVE_MOD_AUDIT_ATTEMPTS:
                await asyncio.sleep(_DISCORD_NATIVE_MOD_AUDIT_RETRY_SECONDS)
        return None

    async def _log_member_flow_action(
        *,
        guild: discord.Guild,
        user: discord.abc.User | discord.Member,
        action_type: str,
        reason: str | None,
        moderator_id: str | None = None,
        moderator: discord.abc.User | discord.Member | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if member_flow_notifications is None:
            return None
        result = await member_flow_notifications.log_action(
            guild_id=str(guild.id),
            user_id=str(user.id),
            moderator_id=moderator_id,
            action_type=action_type,
            reason=reason,
            metadata=metadata,
        )
        if result.get("canonical_written") and result.get("canonical_visible"):
            await member_flow_notifications.send_notification(
                guild=guild,
                user=user,
                action_type=action_type,
                reason=reason,
                moderator=moderator,
                canonical_event=result.get("canonical_event"),
            )
        return result

    async def ensure_channel_record(channel: discord.abc.GuildChannel) -> bool:
        channel_id = str(channel.id)
        enabled = await database.is_channel_enabled(channel_id)
        fingerprint = (
            channel.name,
            str(channel.type),
            str(channel.category_id) if channel.category_id else None,
            _bool_int(getattr(channel, "is_nsfw", lambda: False)()),
            int(getattr(channel, "slowmode_delay", 0) or 0),
        )
        if channel_runtime_fingerprint.get(channel_id) != fingerprint:
            try:
                await database.upsert_channel(
                    channel_id=channel_id,
                    guild_id=str(channel.guild.id),
                    name=channel.name,
                    enabled=_bool_int(enabled),
                    channel_type=str(channel.type),
                    category_id=str(channel.category_id) if channel.category_id else None,
                    is_nsfw=_bool_int(getattr(channel, "is_nsfw", lambda: False)()),
                    slowmode_delay=getattr(channel, "slowmode_delay", 0),
                )
                channel_runtime_fingerprint[channel_id] = fingerprint
            except Exception as exc:  # noqa: BLE001
                if "database is locked" in str(exc).lower():
                    logger.warning("Channel upsert skipped due to SQLite lock channel_id=%s", channel_id)
                else:
                    raise
        if not enabled:
            channel_id = str(channel.id)
            if channel_id not in warned_disabled_channels:
                warned_disabled_channels.add(channel_id)
                logger.info(
                    "Channel %s is disabled for ingestion. Enable with /admin check on",
                    channel_id,
                )
        return enabled

    async def record_user(member: discord.abc.User, guild: Optional[discord.Guild], increment_message: bool, ts: str) -> None:
        display_name = member.display_name if hasattr(member, "display_name") else member.name
        avatar_url = str(member.display_avatar.url) if member.display_avatar else None
        await database.upsert_user(
            user_id=str(member.id),
            username=member.name,
            global_name=getattr(member, "global_name", None),
            display_name=display_name,
            avatar_url=avatar_url,
            is_bot=member.bot,
            ts=ts,
            increment_message=increment_message,
        )
        if guild is not None:
            joined_at = None
            nickname = None
            if isinstance(member, discord.Member):
                joined_at = member.joined_at.isoformat() if member.joined_at else None
                nickname = member.nick
            await database.upsert_guild_membership(
                guild_id=str(guild.id),
                user_id=str(member.id),
                nickname=nickname,
                joined_at=joined_at,
                last_seen_ts=ts,
            )

    async def emit_event(
        event_type: str,
        guild_id: Optional[str],
        channel_id: Optional[str],
        author_id: Optional[str],
        content: Optional[str],
        meta: dict,
        raw: Optional[dict] = None,
        ts: Optional[str] = None,
    ) -> None:
        envelope = EventEnvelope(
            event_id=str(uuid4()),
            event_type=event_type,
            platform="discord",
            ts=ts or _now_iso(),
            guild_id=guild_id,
            channel_id=channel_id,
            thread_id=None,
            author_id=author_id,
            content=content,
            meta=meta,
            raw=raw,
        )
        await ingest.emit(envelope)

    async def handle_ready() -> None:
        logger.info("Discord bot ready as %s", bot.user)

    bot.add_listener(handle_ready, "on_ready")

    async def backfill_handler(start: datetime, end: datetime) -> BackfillResult:
        await bot.wait_until_ready()
        enabled_channels = await database.fetch_enabled_channels()
        messages = 0
        events = 0
        errors = 0
        for row in enabled_channels:
            channel = bot.get_channel(int(row["channel_id"]))
            if channel is None:
                continue
            if not isinstance(channel, discord.abc.Messageable):
                continue
            try:
                async for message in channel.history(
                    after=start,
                    before=end,
                    oldest_first=True,
                    limit=None,
                ):
                    if message.author.bot and config.ignore_bots:
                        continue
                    if not message.guild:
                        continue
                    if await database.message_exists(str(message.id)):
                        continue
                    ts = message.created_at.replace(tzinfo=timezone.utc).isoformat()
                    await record_user(message.author, message.guild, True, ts)
                    reply_to = str(message.reference.message_id) if message.reference else None
                    content_redacted, _ = redact_pii(message.content)
                    await database.insert_message(
                        message_id=str(message.id),
                        guild_id=str(message.guild.id),
                        channel_id=str(message.channel.id),
                        author_id=str(message.author.id),
                        ts=ts,
                        content=content_redacted,
                        reply_to_message_id=reply_to,
                        mentions=[str(user.id) for user in message.mentions],
                        attachments=[{"id": str(att.id), "url": att.url, "filename": att.filename} for att in message.attachments],
                        embeds=[embed.to_dict() for embed in message.embeds],
                    )
                    await database.upsert_channel_activity(
                        guild_id=str(message.guild.id),
                        channel_id=str(message.channel.id),
                        last_message_at=ts,
                    )
                    await emit_event(
                        "message.create",
                        guild_id=str(message.guild.id),
                        channel_id=str(message.channel.id),
                        author_id=str(message.author.id),
                        content=content_redacted,
                        meta={"message_id": str(message.id), "backfill": True},
                        ts=ts,
                    )
                    messages += 1
                    events += 1
            except Exception:  # noqa: BLE001
                logger.exception("Backfill failed for channel %s", row["channel_id"])
                errors += 1

        return BackfillResult(
            messages=messages,
            events=events,
            channels=len(enabled_channels),
            errors=errors,
        )

    if backfill is not None:
        backfill.register_handler(backfill_handler)
    else:
        logger.info("Backfill service not registered; skipping backfill handler setup")

    @bot.event
    async def on_message(message: discord.Message) -> None:
        if message.author.bot and config.ignore_bots:
            return
        if not message.guild:
            return
        enabled = await ensure_channel_record(message.channel)
        if not enabled:
            return
        voice_meta: Optional[dict] = None
        message_channel_id = str(message.channel.id)
        settings_rows = await database.fetchall("SELECT key, value FROM settings WHERE key LIKE 'voice_ingest.%'")
        voice_configs: dict[str, dict[str, str]] = {}
        legacy_settings: dict[str, str] = {}
        for row in settings_rows:
            key = row["key"]
            parts = key.split(".")
            if len(parts) == 3:
                _, bot_id, setting_key = parts
                voice_configs.setdefault(bot_id, {})[setting_key] = row["value"]
            elif len(parts) == 2:
                _, setting_key = parts
                legacy_settings[setting_key] = row["value"]
        for settings in voice_configs.values():
            enabled_flag = settings.get("enabled", "").lower() in {"1", "true", "yes", "y"}
            if not enabled_flag:
                continue
            target_text_id = settings.get("target_text_channel_id")
            target_voice_id = settings.get("target_voice_channel_id")
            if not target_text_id or not target_voice_id:
                continue
            if message_channel_id != target_text_id:
                continue
            session = await database.get_active_voice_session(str(message.guild.id), target_voice_id)
            if session:
                started_ts = datetime.fromisoformat(session["started_ts"])
                if started_ts.tzinfo is None:
                    started_ts = started_ts.replace(tzinfo=timezone.utc)
                message_ts = message.created_at
                if message_ts.tzinfo is None:
                    message_ts = message_ts.replace(tzinfo=timezone.utc)
                call_offset_ms = int((message_ts - started_ts).total_seconds() * 1000)
                voice_meta = {
                    "voice_session_id": session["voice_session_id"],
                    "voice_channel_id": target_voice_id,
                    "call_offset_ms": call_offset_ms,
                }
                break
        if voice_meta is None:
            legacy_enabled = legacy_settings.get("enabled", "").lower() in {"1", "true", "yes", "y"}
            target_text_id = legacy_settings.get("target_text_channel_id")
            target_voice_id = legacy_settings.get("target_voice_channel_id")
            if legacy_enabled and target_text_id and target_voice_id and message_channel_id == target_text_id:
                session = await database.get_active_voice_session(str(message.guild.id), target_voice_id)
                if session:
                    started_ts = datetime.fromisoformat(session["started_ts"])
                    if started_ts.tzinfo is None:
                        started_ts = started_ts.replace(tzinfo=timezone.utc)
                    message_ts = message.created_at
                    if message_ts.tzinfo is None:
                        message_ts = message_ts.replace(tzinfo=timezone.utc)
                    call_offset_ms = int((message_ts - started_ts).total_seconds() * 1000)
                    voice_meta = {
                        "voice_session_id": session["voice_session_id"],
                        "voice_channel_id": target_voice_id,
                        "call_offset_ms": call_offset_ms,
                    }
        ts = message.created_at.replace(tzinfo=timezone.utc).isoformat()
        await record_user(message.author, message.guild, True, ts)
        reply_to = str(message.reference.message_id) if message.reference else None
        embeds = [embed.to_dict() for embed in message.embeds]
        if voice_meta:
            embeds.append({"voice_meta": voice_meta})
        content_redacted, _ = redact_pii(message.content)
        await database.insert_message(
            message_id=str(message.id),
            guild_id=str(message.guild.id),
            channel_id=str(message.channel.id),
            author_id=str(message.author.id),
            ts=ts,
            content=content_redacted,
            reply_to_message_id=reply_to,
            mentions=[str(user.id) for user in message.mentions],
            attachments=[{"id": str(att.id), "url": att.url, "filename": att.filename} for att in message.attachments],
            embeds=embeds,
        )
        await database.upsert_channel_activity(
            guild_id=str(message.guild.id),
            channel_id=str(message.channel.id),
            last_message_at=ts,
        )
        await emit_event(
            "message.create",
            guild_id=str(message.guild.id),
            channel_id=str(message.channel.id),
            author_id=str(message.author.id),
            content=content_redacted,
            meta={"message_id": str(message.id)},
        )
        if aura_rolling is not None:
            await aura_rolling.on_message_saved(
                guild_id=str(message.guild.id),
                channel_id=str(message.channel.id),
                user_id=str(message.author.id),
                ts=ts,
                mentions=[str(user.id) for user in message.mentions],
                message_id=str(message.id),
                content=content_redacted,
            )
        if voice_meta:
            await emit_event(
                "chat.message",
                guild_id=str(message.guild.id),
                channel_id=str(message.channel.id),
                author_id=str(message.author.id),
                content=content_redacted,
                meta={"message_id": str(message.id), **voice_meta},
            )
        if trigger_engine is not None:
            mentions_bot = bot.user is not None and bot.user.mentioned_in(message)
            reply_to_bot = bool(
                message.reference
                and message.reference.resolved is not None
                and isinstance(message.reference.resolved, discord.Message)
                and bot.user is not None
                and message.reference.resolved.author.id == bot.user.id
            )
            if mentions_bot or reply_to_bot:
                try:
                    await trigger_engine.handle_message_qna(message)
                except Exception:  # noqa: BLE001
                    logger.exception("on_message qna handler failed", extra={"message_id": str(message.id)})

    @bot.event
    async def on_message_edit(before: discord.Message, after: discord.Message) -> None:
        if after.author.bot and config.ignore_bots:
            return
        if not after.guild:
            return
        enabled = await ensure_channel_record(after.channel)
        if not enabled:
            return
        edited_ts = _now_iso()
        content_redacted, _ = redact_pii(after.content)
        await database.update_message_edit(str(after.id), edited_ts, content_redacted)
        await emit_event(
            "message.edit",
            guild_id=str(after.guild.id),
            channel_id=str(after.channel.id),
            author_id=str(after.author.id),
            content=content_redacted,
            meta={"message_id": str(after.id)},
        )

    @bot.event
    async def on_message_delete(message: discord.Message) -> None:
        if not message.guild:
            return
        enabled = await ensure_channel_record(message.channel)
        if not enabled:
            return
        await database.mark_message_deleted(str(message.id))
        await emit_event(
            "message.delete",
            guild_id=str(message.guild.id),
            channel_id=str(message.channel.id),
            author_id=str(message.author.id) if message.author else None,
            content=None,
            meta={"message_id": str(message.id)},
        )

    @bot.event
    async def on_reaction_add(reaction: discord.Reaction, user: discord.User) -> None:
        if user.bot and config.ignore_bots:
            return
        if not reaction.message.guild:
            return
        enabled = await ensure_channel_record(reaction.message.channel)
        if not enabled:
            return
        ts = _now_iso()
        await record_user(user, reaction.message.guild, False, ts)
        await database.insert_reaction(str(reaction.message.id), str(user.id), str(reaction.emoji), ts)
        await emit_event(
            "reaction.add",
            guild_id=str(reaction.message.guild.id),
            channel_id=str(reaction.message.channel.id),
            author_id=str(user.id),
            content=None,
            meta={"message_id": str(reaction.message.id), "emoji": str(reaction.emoji)},
        )

    @bot.event
    async def on_reaction_remove(reaction: discord.Reaction, user: discord.User) -> None:
        if user.bot and config.ignore_bots:
            return
        if not reaction.message.guild:
            return
        enabled = await ensure_channel_record(reaction.message.channel)
        if not enabled:
            return
        await database.delete_reaction(str(reaction.message.id), str(user.id), str(reaction.emoji))
        await emit_event(
            "reaction.remove",
            guild_id=str(reaction.message.guild.id),
            channel_id=str(reaction.message.channel.id),
            author_id=str(user.id),
            content=None,
            meta={"message_id": str(reaction.message.id), "emoji": str(reaction.emoji)},
        )

    @bot.event
    async def on_member_join(member: discord.Member) -> None:
        ts = _now_iso()
        await record_user(member, member.guild, False, ts)
        await _log_member_flow_action(
            guild=member.guild,
            user=member,
            action_type="join",
            reason="Ingresso nel server",
            metadata={"source": "discord_adapter"},
        )
        await emit_event(
            "member.join",
            guild_id=str(member.guild.id),
            channel_id=None,
            author_id=str(member.id),
            content=None,
            meta={"target_id": str(member.id)},
        )

    @bot.event
    async def on_member_remove(member: discord.Member) -> None:
        ts = _now_iso()
        await record_user(member, member.guild, False, ts)
        native_departure = await _resolve_native_departure(member)
        action_type = str(native_departure.get("action_type") or "leave") if native_departure is not None else "leave"
        reason = (
            _normalize_optional_reason(native_departure.get("reason"))
            if native_departure is not None
            else None
        )
        if action_type == "kick":
            default_reason = "Allontanamento tramite moderazione nativa Discord"
        elif action_type == "ban":
            default_reason = "Ban tramite moderazione nativa Discord"
        else:
            default_reason = "Uscita dal server"
        metadata = {
            "source": "discord_adapter",
            "native_moderation": native_departure is not None,
            "greetings_reason": reason,
        }
        if native_departure is not None:
            operation_id = _build_native_moderation_operation_id(
                guild_id=str(member.guild.id),
                user_id=str(member.id),
                action_type=action_type,
                entry_id=native_departure.get("entry_id"),
                created_at=native_departure.get("created_at"),
            )
            metadata.update(
                {
                    "operation_id": operation_id,
                    "native_moderation_source": native_departure.get("source"),
                    "discord_audit_action": native_departure.get("action_type"),
                    "discord_audit_entry_id": native_departure.get("entry_id"),
                    "discord_audit_created_at": native_departure.get("created_at"),
                }
            )
        if not bool(native_departure and native_departure.get("skip_logging")):
            await _log_member_flow_action(
                guild=member.guild,
                user=member,
                action_type=action_type,
                reason=reason or default_reason,
                moderator_id=(
                    str(native_departure.get("moderator_id") or "").strip() or None
                    if native_departure is not None
                    else None
                ),
                moderator=native_departure.get("moderator") if native_departure is not None else None,
                metadata=metadata,
            )
        await emit_event(
            "member.leave",
            guild_id=str(member.guild.id),
            channel_id=None,
            author_id=str(member.id),
            content=None,
            meta={
                "target_id": str(member.id),
                "departure_type": action_type,
                "native_moderation": native_departure is not None,
            },
        )

    @bot.event
    async def on_member_ban(guild: discord.Guild, user: discord.abc.User) -> None:
        ts = _now_iso()
        await record_user(user, guild, False, ts)
        native_departure = await _fetch_recent_audit_entry(guild, action_name="ban", target_id=str(user.id))
        recent_departure_getter = getattr(member_flow_notifications, "get_recent_departure_action", None)
        if recent_departure_getter is not None and recent_departure_getter(str(guild.id), str(user.id)) in {"ban", "tempban", "inactive_tempban"}:
            native_departure = native_departure or {"action_type": "ban", "reason": None, "moderator_id": None, "moderator": None, "entry_id": None, "created_at": None}
        else:
            operation_id = _build_native_moderation_operation_id(
                guild_id=str(guild.id),
                user_id=str(user.id),
                action_type="ban",
                entry_id=native_departure.get("entry_id") if native_departure is not None else None,
                created_at=native_departure.get("created_at") if native_departure is not None else None,
            )
            metadata = {
                "source": "discord_adapter",
                "operation_id": operation_id,
                "native_moderation": True,
                "native_moderation_source": "member_ban_event",
                "discord_audit_action": "ban",
                "discord_audit_entry_id": native_departure.get("entry_id") if native_departure is not None else None,
                "discord_audit_created_at": native_departure.get("created_at") if native_departure is not None else None,
                "greetings_reason": _normalize_optional_reason(native_departure.get("reason") if native_departure is not None else None),
            }
            await _log_member_flow_action(
                guild=guild,
                user=user,
                action_type="ban",
                reason=(native_departure.get("reason") if native_departure is not None else None) or "Ban tramite moderazione nativa Discord",
                moderator_id=(native_departure.get("moderator_id") if native_departure is not None else None),
                moderator=(native_departure.get("moderator") if native_departure is not None else None),
                metadata=metadata,
            )
        await emit_event(
            "member.ban",
            guild_id=str(guild.id),
            channel_id=None,
            author_id=str(user.id),
            content=None,
            meta={"target_id": str(user.id)},
        )

    @bot.event
    async def on_member_unban(guild: discord.Guild, user: discord.abc.User) -> None:
        ts = _now_iso()
        await record_user(user, guild, False, ts)
        native_departure = await _fetch_recent_audit_entry(guild, action_name="unban", target_id=str(user.id))
        if member_flow_notifications is not None:
            await member_flow_notifications.log_action(
                guild_id=str(guild.id),
                user_id=str(user.id),
                moderator_id=(native_departure.get("moderator_id") if native_departure is not None else None),
                action_type="unban",
                reason=(native_departure.get("reason") if native_departure is not None else None) or "Revoca ban tramite moderazione nativa Discord",
                metadata={
                    "source": "discord_adapter",
                    "native_moderation": True,
                    "native_moderation_source": "member_unban_event",
                    "discord_audit_action": "unban",
                    "discord_audit_entry_id": native_departure.get("entry_id") if native_departure is not None else None,
                    "discord_audit_created_at": native_departure.get("created_at") if native_departure is not None else None,
                },
            )
        await emit_event(
            "member.unban",
            guild_id=str(guild.id),
            channel_id=None,
            author_id=str(user.id),
            content=None,
            meta={"target_id": str(user.id)},
        )

    @bot.event
    async def on_member_update(before: discord.Member, after: discord.Member) -> None:
        ts = _now_iso()
        await record_user(after, after.guild, False, ts)
        await emit_event(
            "member.update",
            guild_id=str(after.guild.id),
            channel_id=None,
            author_id=str(after.id),
            content=None,
            meta={
                "target_id": str(after.id),
                "roles": [str(role.id) for role in after.roles],
                "nickname": after.nick,
            },
        )

    async def _record_voice_event(
        *,
        event_type: str,
        member: discord.Member,
        voice_channel_id: str,
        ts: str,
        from_channel_id: str | None,
        to_channel_id: str | None,
    ) -> None:
        now_dt = datetime.fromisoformat(ts)
        dedupe_key = (str(member.guild.id), str(member.id), event_type, from_channel_id, to_channel_id)
        last = voice_event_dedupe.get(dedupe_key)
        if last is not None and (now_dt - last) < timedelta(seconds=2):
            return
        voice_event_dedupe[dedupe_key] = now_dt
        await database.insert_voice_participant_event(
            event_id=str(uuid4()),
            guild_id=str(member.guild.id),
            voice_channel_id=voice_channel_id,
            user_id=str(member.id),
            username=member.display_name,
            event_type=event_type,
            ts=ts,
            from_channel_id=from_channel_id,
            to_channel_id=to_channel_id,
            meta={"source": "discord_adapter.voice_state"},
        )

    @bot.event
    async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if member.bot and config.ignore_bots:
            return
        if not member.guild:
            return
        ts = _now_iso()
        before_channel = before.channel
        after_channel = after.channel
        if before_channel == after_channel:
            return

        if before_channel is not None:
            event_type = "switch" if after_channel is not None else "leave"
            await _record_voice_event(
                event_type=event_type,
                member=member,
                voice_channel_id=str(before_channel.id),
                ts=ts,
                from_channel_id=str(before_channel.id),
                to_channel_id=str(after_channel.id) if after_channel else None,
            )
            if aura_rolling is not None:
                join_row = await database.fetch_latest_voice_participant_join(
                    guild_id=str(member.guild.id),
                    voice_channel_id=str(before_channel.id),
                    user_id=str(member.id),
                    before_ts=ts,
                )
                if join_row is not None:
                    try:
                        joined_ts = datetime.fromisoformat(str(join_row["ts"]))
                        if joined_ts.tzinfo is None:
                            joined_ts = joined_ts.replace(tzinfo=timezone.utc)
                        now_dt = datetime.fromisoformat(ts)
                        if now_dt.tzinfo is None:
                            now_dt = now_dt.replace(tzinfo=timezone.utc)
                        minutes = int(max(0, (now_dt - joined_ts).total_seconds()) // 60)
                    except Exception:  # noqa: BLE001
                        minutes = 0
                    if minutes > 0:
                        await aura_rolling.on_voice_participation(
                            guild_id=str(member.guild.id),
                            voice_channel_id=str(before_channel.id),
                            user_id=str(member.id),
                            minutes=minutes,
                            ts=ts,
                            voice_session_id=None,
                        )

        if after_channel is not None:
            if before_channel is None:
                await _record_voice_event(
                    event_type="join",
                    member=member,
                    voice_channel_id=str(after_channel.id),
                    ts=ts,
                    from_channel_id=None,
                    to_channel_id=str(after_channel.id),
                )
            if aura_rolling is not None:
                await aura_rolling.on_voice_join(
                    guild_id=str(member.guild.id),
                    voice_channel_id=str(after_channel.id),
                    user_id=str(member.id),
                    ts=ts,
                    event_id=f"voice-join:{member.id}:{after_channel.id}:{int(datetime.fromisoformat(ts).timestamp())}",
                )
                non_bot_members = [m for m in after_channel.members if not m.bot]
                if len(non_bot_members) == 1:
                    await aura_rolling.on_voice_starter(
                        guild_id=str(member.guild.id),
                        voice_channel_id=str(after_channel.id),
                        user_id=str(member.id),
                        ts=ts,
                        day_key=datetime.fromisoformat(ts).date().isoformat(),
                    )
    if trigger_engine is not None:
        ingest.register_consumer(trigger_engine.on_event)
