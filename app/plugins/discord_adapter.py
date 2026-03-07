from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import discord

from app.core.service_registry import ServiceRegistry
from app.services.backfill import BackfillResult
from app.services.ingest import EventEnvelope, IngestService
from app.utils.pii import redact_pii

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bool_int(value: bool) -> int:
    return 1 if value else 0


def setup(registry: ServiceRegistry) -> None:
    bot: discord.Client = registry.get("bot")
    database = registry.get("database")
    ingest: IngestService = registry.get("ingest")
    trigger_engine = registry.get("trigger_engine") if registry.has("trigger_engine") else None
    backfill = registry.get("backfill") if registry.has("backfill") else None
    config = registry.get("config")
    aura_rolling = registry.get("aura_rolling") if registry.has("aura_rolling") else None
    warned_disabled_channels: set[str] = set()

    async def ensure_channel_record(channel: discord.abc.GuildChannel) -> bool:
        enabled = await database.is_channel_enabled(str(channel.id))
        await database.upsert_channel(
            channel_id=str(channel.id),
            guild_id=str(channel.guild.id),
            name=channel.name,
            enabled=_bool_int(enabled),
            channel_type=str(channel.type),
            category_id=str(channel.category_id) if channel.category_id else None,
            is_nsfw=_bool_int(getattr(channel, "is_nsfw", lambda: False)()),
            slowmode_delay=getattr(channel, "slowmode_delay", 0),
        )
        if not enabled:
            channel_id = str(channel.id)
            if channel_id not in warned_disabled_channels:
                warned_disabled_channels.add(channel_id)
                logger.info(
                    "Channel %s is disabled for ingestion. Enable with /barcellometro check on",
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
        await emit_event(
            "member.leave",
            guild_id=str(member.guild.id),
            channel_id=None,
            author_id=str(member.id),
            content=None,
            meta={"target_id": str(member.id)},
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
    if trigger_engine is not None:
        ingest.register_consumer(trigger_engine.on_event)
