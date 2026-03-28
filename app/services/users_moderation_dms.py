from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import discord

from app.services.database import DatabaseService
from app.shared.discord.dm_embed_builder import build_standard_dm_embed

DEFAULT_USERS_DM_COOLDOWN_DAYS = 14
DEFAULT_USERS_DM_GRACE_TEMPLATE = (
    "Hi {user}, you have entered a manual grace period in {server}. "
    "It will expire on {expires_at_utc}. {reason_line}{invite_line}"
)
DEFAULT_USERS_DM_TEMPBAN_TEMPLATE = (
    "Hi {user}, your manual grace period in {server} has expired and an automatic temporary ban "
    "has started for {duration_human}. {reason_line}{invite_line}"
)
USERS_DM_SUPPORTED_PLACEHOLDERS: tuple[str, ...] = (
    "user",
    "username",
    "display_name",
    "user_id",
    "server",
    "guild_id",
    "event_type",
    "duration_seconds",
    "duration_human",
    "expires_at_utc",
    "reason",
    "reason_line",
    "invite_url",
    "invite_line",
)

USERS_DM_SERVICE_NAME = "inactivity_moderation"


class UsersModerationDmService:
    def __init__(self, database: DatabaseService, bot: discord.Client | None = None) -> None:
        self._database = database
        self._bot = bot

    async def get_config(self, guild_id: str) -> dict[str, Any]:
        get_cfg = getattr(self._database, "get_users_dm_config", None)
        if get_cfg is None:
            return {
                "enabled": 0,
                "grace_template": None,
                "tempban_template": None,
                "cooldown_days": DEFAULT_USERS_DM_COOLDOWN_DAYS,
                "invite_url": None,
            }
        row = await get_cfg(guild_id)
        base: dict[str, Any] = {
            "enabled": 1,
            "grace_template": None,
            "tempban_template": None,
            "cooldown_days": DEFAULT_USERS_DM_COOLDOWN_DAYS,
            "invite_url": None,
        }
        if row is not None:
            base.update(dict(row))
        return base

    async def send_for_event_by_user_id(
        self,
        *,
        guild: discord.Guild,
        user_id: str,
        event_type: str,
        duration_seconds: int | None = None,
        expires_at: datetime | None = None,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        guild_id = str(guild.id)
        clean_user_id = str(user_id)
        if self._bot is None:
            await self._log_delivery(
                guild_id=guild_id,
                user_id=clean_user_id,
                event_type=event_type,
                reason=reason,
                outcome="skipped",
                error_summary="bot_unavailable",
                metadata=metadata,
            )
            return {"sent": False, "skipped": "bot_unavailable"}
        getter = getattr(guild, "get_member", None)
        target_user: discord.abc.User | None = getter(int(user_id)) if callable(getter) else None
        if target_user is None:
            try:
                target_user = await self._bot.fetch_user(int(user_id))
            except Exception:
                await self._log_delivery(
                    guild_id=guild_id,
                    user_id=clean_user_id,
                    event_type=event_type,
                    reason=reason,
                    outcome="skipped",
                    error_summary="user_unavailable",
                    metadata=metadata,
                )
                return {"sent": False, "skipped": "user_unavailable"}
        return await self.send_for_event(
            guild=guild,
            user=target_user,
            event_type=event_type,
            duration_seconds=duration_seconds,
            expires_at=expires_at,
            reason=reason,
            metadata=metadata,
        )

    async def send_for_event(
        self,
        *,
        guild: discord.Guild,
        user: discord.abc.User,
        event_type: str,
        duration_seconds: int | None = None,
        expires_at: datetime | None = None,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        guild_id = str(guild.id)
        user_id = str(user.id)
        cfg = await self.get_config(guild_id)
        if int(cfg.get("enabled", 1) or 0) <= 0:
            await self._log_delivery(
                guild_id=guild_id,
                user_id=user_id,
                event_type=event_type,
                reason=reason,
                outcome="skipped",
                error_summary="disabled",
                metadata=metadata,
            )
            return {"sent": False, "skipped": "disabled"}

        cooldown_days = max(1, int(cfg.get("cooldown_days", DEFAULT_USERS_DM_COOLDOWN_DAYS) or DEFAULT_USERS_DM_COOLDOWN_DAYS))
        latest_lookup = getattr(self._database, "get_latest_users_dm_delivery", None)
        latest = await latest_lookup(guild_id, user_id, event_type) if latest_lookup is not None else None
        latest_outcome = ""
        if latest is not None:
            try:
                latest_outcome = str(latest["outcome"] or "").lower()
            except Exception:
                latest_outcome = "success"
        if latest and latest["sent_at"] and latest_outcome == "success":
            try:
                last_sent = datetime.fromisoformat(str(latest["sent_at"]).replace("Z", "+00:00"))
                if last_sent.tzinfo is None:
                    last_sent = last_sent.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - last_sent < timedelta(days=cooldown_days):
                    await self._log_delivery(
                        guild_id=guild_id,
                        user_id=user_id,
                        event_type=event_type,
                        reason=reason,
                        outcome="skipped",
                        error_summary="cooldown",
                        metadata={**(metadata or {}), "cooldown_days": cooldown_days},
                    )
                    return {"sent": False, "skipped": "cooldown"}
            except Exception:
                pass

        template = self._template_for_event(cfg, event_type)
        body = self._render_template(
            template,
            guild=guild,
            user=user,
            event_type=event_type,
            duration_seconds=duration_seconds,
            expires_at=expires_at,
            reason=reason,
            invite_url=str(cfg.get("invite_url") or "").strip(),
        )
        title, emoji = self._title_for_event(event_type)
        dm_embed = await build_standard_dm_embed(
            service_name=USERS_DM_SERVICE_NAME,
            canonical_top_level_command="inattivi",
            title=title,
            title_emoji=emoji,
            description=body,
            color=discord.Colour.orange() if event_type == "tempban" else discord.Colour.blurple(),
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            await user.send(embed=dm_embed)
            await self._log_delivery(
                guild_id=guild_id,
                user_id=user_id,
                event_type=event_type,
                reason=reason,
                sent_at=now_iso,
                outcome="success",
                metadata=metadata,
            )
            return {"sent": True}
        except Exception as exc:  # noqa: BLE001
            try:
                await user.send(body)
                await self._log_delivery(
                    guild_id=guild_id,
                    user_id=user_id,
                    event_type=event_type,
                    reason=reason,
                    sent_at=now_iso,
                    outcome="success",
                    metadata={**(metadata or {}), "delivery_fallback": "text"},
                )
                return {"sent": True, "fallback": "text"}
            except Exception:
                pass
            await self._log_delivery(
                guild_id=guild_id,
                user_id=user_id,
                event_type=event_type,
                reason=reason,
                sent_at=now_iso,
                outcome="fail",
                error_summary=exc.__class__.__name__,
                metadata=metadata,
            )
            return {"sent": False, "skipped": "error", "error": exc.__class__.__name__}

    async def _log_delivery(
        self,
        *,
        guild_id: str,
        user_id: str,
        event_type: str,
        outcome: str,
        reason: str | None = None,
        sent_at: str | None = None,
        error_summary: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        log_method = getattr(self._database, "log_users_dm_delivery", None)
        if log_method is None:
            return
        await log_method(
            guild_id=guild_id,
            user_id=user_id,
            event_type=event_type,
            reason=reason,
            sent_at=sent_at,
            outcome=outcome,
            error_summary=error_summary,
            metadata={**(metadata or {}), "source": "users_moderation_dms"},
        )

    @staticmethod
    def _template_for_event(cfg: dict[str, Any], event_type: str) -> str:
        if event_type == "tempban":
            return str(cfg.get("tempban_template") or DEFAULT_USERS_DM_TEMPBAN_TEMPLATE)
        return str(cfg.get("grace_template") or DEFAULT_USERS_DM_GRACE_TEMPLATE)

    @staticmethod
    def _duration_human(duration_seconds: int | None) -> str:
        if duration_seconds is None or duration_seconds <= 0:
            return "0m"
        total = int(duration_seconds)
        days, rem = divmod(total, 86400)
        hours, rem = divmod(rem, 3600)
        mins, _ = divmod(rem, 60)
        if days > 0:
            return f"{days}d {hours}h"
        if hours > 0:
            return f"{hours}h {mins}m"
        return f"{max(1, mins)}m"

    @staticmethod
    def _title_for_event(event_type: str) -> tuple[str, str]:
        if event_type == "tempban":
            return "Ban temporaneo automatico", "🔨"
        return "Grace manuale attivato", "🛡️"

    @classmethod
    def _render_template(
        cls,
        template: str,
        *,
        guild: discord.Guild,
        user: discord.abc.User,
        event_type: str,
        duration_seconds: int | None,
        expires_at: datetime | None,
        reason: str | None,
        invite_url: str,
    ) -> str:
        safe_reason = str(reason or "").strip()
        safe_invite = str(invite_url or "").strip()
        expires = expires_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if expires_at else "n/a"
        payload = {
            "user": user.mention,
            "username": str(getattr(user, "name", "")),
            "display_name": str(getattr(user, "display_name", getattr(user, "name", ""))),
            "user_id": str(user.id),
            "server": guild.name,
            "guild_id": str(guild.id),
            "event_type": event_type,
            "duration_seconds": int(duration_seconds or 0),
            "duration_human": cls._duration_human(duration_seconds),
            "expires_at_utc": expires,
            "reason": safe_reason,
            "reason_line": f"Reason: {safe_reason}. " if safe_reason else "",
            "invite_url": safe_invite,
            "invite_line": f"Invite: {safe_invite}" if safe_invite else "",
        }
        try:
            return template.format(**payload)
        except Exception:
            return template
