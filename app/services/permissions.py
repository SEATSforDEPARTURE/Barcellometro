from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.services.database import DatabaseService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Policy:
    usage_limit: Optional[int]
    cooldown_seconds: Optional[int]
    source: str


@dataclass(frozen=True)
class PermissionResult:
    allowed: bool
    reason: str
    remaining: Optional[int]
    cooldown_remaining: Optional[int]


class CommandGuardService:
    def __init__(self, database: DatabaseService) -> None:
        self._database = database
        self._metrics = {
            "checks": 0,
            "denied": 0,
        }

    async def check_command(
        self,
        *,
        guild_id: Optional[int],
        user_id: int,
        role_ids: list[int],
        command: str,
        is_admin: bool,
    ) -> PermissionResult:
        self._metrics["checks"] += 1
        if is_admin:
            return PermissionResult(True, "admin", None, None)
        if guild_id is None:
            self._metrics["denied"] += 1
            return PermissionResult(False, "Solo admin o policy configurata.", None, None)

        policy = await self._resolve_policy(str(guild_id), str(user_id), [str(role_id) for role_id in role_ids], command)
        if policy is None:
            self._metrics["denied"] += 1
            return PermissionResult(False, "Solo admin o policy configurata.", None, None)

        cooldown_remaining = await self._check_cooldown(str(guild_id), str(user_id), command, policy.cooldown_seconds)
        if cooldown_remaining is not None:
            self._metrics["denied"] += 1
            return PermissionResult(False, "Cooldown attivo.", None, cooldown_remaining)

        remaining = await self._consume_usage_limit(str(guild_id), str(user_id), command, policy.usage_limit)
        if remaining is None and policy.usage_limit is not None:
            self._metrics["denied"] += 1
            return PermissionResult(False, "Limite utilizzi raggiunto.", 0, None)

        return PermissionResult(True, "ok", remaining, None)

    async def _resolve_policy(
        self,
        guild_id: str,
        user_id: str,
        role_ids: list[str],
        command: str,
    ) -> Optional[Policy]:
        user_policy = await self._database.fetch_user_policy(guild_id, user_id, command)
        if user_policy:
            return Policy(
                usage_limit=user_policy["usage_limit"],
                cooldown_seconds=user_policy["cooldown_seconds"],
                source="user",
            )

        role_policies = []
        for role_id in role_ids:
            row = await self._database.fetch_role_policy(guild_id, role_id, command)
            if row:
                role_policies.append(row)
        if not role_policies:
            return None

        usage_limit = min(
            (row["usage_limit"] for row in role_policies if row["usage_limit"] is not None),
            default=None,
        )
        cooldown_seconds = max(
            (row["cooldown_seconds"] for row in role_policies if row["cooldown_seconds"] is not None),
            default=None,
        )
        return Policy(usage_limit=usage_limit, cooldown_seconds=cooldown_seconds, source="role")

    async def _check_cooldown(
        self,
        guild_id: str,
        user_id: str,
        command: str,
        cooldown_seconds: Optional[int],
    ) -> Optional[int]:
        if cooldown_seconds is None:
            return None
        today = datetime.now(timezone.utc).date().isoformat()
        counter = await self._database.fetch_usage_counter(guild_id, user_id, command, today)
        if counter is None or counter["last_used_ts"] is None:
            return None
        last_used = datetime.fromisoformat(counter["last_used_ts"])
        if last_used.tzinfo is None:
            last_used = last_used.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - last_used
        remaining = cooldown_seconds - int(delta.total_seconds())
        return remaining if remaining > 0 else None

    async def _consume_usage_limit(
        self,
        guild_id: str,
        user_id: str,
        command: str,
        usage_limit: Optional[int],
    ) -> Optional[int]:
        if usage_limit is None:
            await self._touch_usage_counter(guild_id, user_id, command)
            return None
        today = datetime.now(timezone.utc).date().isoformat()
        counter = await self._database.fetch_usage_counter(guild_id, user_id, command, today)
        used = counter["used_count"] if counter else 0
        if used >= usage_limit:
            return None
        used += 1
        await self._database.upsert_usage_counter(
            guild_id=guild_id,
            user_id=user_id,
            command=command,
            window_date=today,
            used_count=used,
            last_used_ts=datetime.now(timezone.utc).isoformat(),
        )
        return max(usage_limit - used, 0)

    async def _touch_usage_counter(self, guild_id: str, user_id: str, command: str) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        await self._database.upsert_usage_counter(
            guild_id=guild_id,
            user_id=user_id,
            command=command,
            window_date=today,
            used_count=0,
            last_used_ts=datetime.now(timezone.utc).isoformat(),
        )

    def status(self) -> dict[str, object]:
        return {
            "active": True,
            "state": "running",
            "metrics": dict(self._metrics),
        }
