from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.database import DatabaseService

ROME_TZ = ZoneInfo("Europe/Rome")


@dataclass
class InactivityEntry:
    user_id: int
    last_seen_ts: str | None
    days_inactive: int


class InactivityService:
    def __init__(self, database: DatabaseService) -> None:
        self._database = database

    async def compute_inactive_users_for_channel(
        self,
        *,
        guild_id: str,
        channel_id: str,
        reference_end_ts: str,
        threshold_days: int = 14,
        lookback_days: int = 90,
        limit: int = 10,
    ) -> list[InactivityEntry]:
        reference_dt = datetime.fromisoformat(reference_end_ts.replace("Z", "+00:00"))
        if reference_dt.tzinfo is None:
            reference_dt = reference_dt.replace(tzinfo=timezone.utc)
        since_dt = reference_dt - timedelta(days=max(1, lookback_days))
        last_seen = await self._database.last_seen_by_user_in_channel(guild_id, channel_id, since_dt.isoformat())
        entries: list[InactivityEntry] = []
        for user_id, ts in last_seen.items():
            last_seen_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if last_seen_dt.tzinfo is None:
                last_seen_dt = last_seen_dt.replace(tzinfo=timezone.utc)
            days = max(0, int((reference_dt - last_seen_dt).total_seconds() // 86400))
            if days >= threshold_days:
                entries.append(InactivityEntry(user_id=user_id, last_seen_ts=ts, days_inactive=days))
        entries.sort(key=lambda item: item.days_inactive, reverse=True)
        return entries[: max(1, limit)]
