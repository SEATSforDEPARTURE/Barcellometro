from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

from app.services.database import DatabaseService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackfillResult:
    messages: int
    events: int
    channels: int
    errors: int


BackfillHandler = Callable[[datetime, datetime], Awaitable[BackfillResult]]


class BackfillService:
    def __init__(self, database: DatabaseService, default_days: int) -> None:
        self._database = database
        self._default_days = default_days
        self._backfill_days = default_days
        self._enabled = False
        self._handler: Optional[BackfillHandler] = None
        self._task: Optional[asyncio.Task[None]] = None
        self._lock = asyncio.Lock()
        self._metrics = {
            "last_run_ts": None,
            "last_start_ts": None,
            "last_end_ts": None,
            "messages": 0,
            "events": 0,
            "channels": 0,
            "errors": 0,
        }

    async def load_settings(self) -> None:
        enabled = await self._database.get_setting("backfill_enabled")
        days = await self._database.get_setting("backfill_days")
        if enabled is None:
            await self._database.set_setting("backfill_enabled", "false")
            self._enabled = False
        else:
            self._enabled = enabled.lower() in {"1", "true", "yes", "y"}
        if days is None:
            await self._database.set_setting("backfill_days", str(self._default_days))
            self._backfill_days = self._default_days
        else:
            self._backfill_days = int(days)

    def register_handler(self, handler: BackfillHandler) -> None:
        self._handler = handler

    def start(self) -> None:
        if self._enabled and self._task is None:
            self._task = asyncio.create_task(self.run_once())

    async def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        await self._database.set_setting("backfill_enabled", "true" if enabled else "false")

    async def set_backfill_days(self, days: int) -> None:
        self._backfill_days = days
        await self._database.set_setting("backfill_days", str(days))

    async def get_backfill_days(self) -> int:
        return self._backfill_days

    async def is_enabled(self) -> bool:
        return self._enabled

    async def run_once(self) -> BackfillResult:
        async with self._lock:
            if not self._enabled:
                logger.info("Backfill skipped because it is disabled")
                return BackfillResult(messages=0, events=0, channels=0, errors=0)
            if self._handler is None:
                logger.warning("Backfill handler not registered")
                return BackfillResult(messages=0, events=0, channels=0, errors=0)

            now = datetime.now(timezone.utc)
            desired_start = now - timedelta(days=self._backfill_days)

            last_event_dt: Optional[datetime] = None
            last_event_ts = await self._database.latest_event_ts()
            if last_event_ts:
                try:
                    last_event_dt = datetime.fromisoformat(last_event_ts)
                    if last_event_dt.tzinfo is None:
                        last_event_dt = last_event_dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    logger.warning("Invalid last event timestamp in database: %s", last_event_ts)

            earliest_event_dt: Optional[datetime] = None
            earliest_event_ts = await self._database.earliest_event_ts()
            if earliest_event_ts:
                try:
                    earliest_event_dt = datetime.fromisoformat(earliest_event_ts)
                    if earliest_event_dt.tzinfo is None:
                        earliest_event_dt = earliest_event_dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    logger.warning("Invalid earliest event timestamp in database: %s", earliest_event_ts)

            windows: list[tuple[datetime, datetime]] = []
            recent_start = max(desired_start, last_event_dt) if last_event_dt else desired_start
            if recent_start < now:
                windows.append((recent_start, now))

            if earliest_event_dt and earliest_event_dt > desired_start:
                early_end = min(earliest_event_dt, recent_start)
                if desired_start < early_end:
                    windows.append((desired_start, early_end))

            if not windows:
                logger.info("Backfill not needed (no gap detected)")
                return BackfillResult(messages=0, events=0, channels=0, errors=0)

            total_messages = 0
            total_events = 0
            total_errors = 0
            total_channels = 0
            earliest_window_start = min(start for start, _ in windows)
            latest_window_end = max(end for _, end in windows)
            for start, end in windows:
                result = await self._handler(start, end)
                total_messages += result.messages
                total_events += result.events
                total_errors += result.errors
                total_channels = max(total_channels, result.channels)

            self._metrics["last_run_ts"] = datetime.now(timezone.utc).isoformat()
            self._metrics["last_start_ts"] = earliest_window_start.isoformat()
            self._metrics["last_end_ts"] = latest_window_end.isoformat()
            self._metrics["messages"] = total_messages
            self._metrics["events"] = total_events
            self._metrics["channels"] = total_channels
            self._metrics["errors"] = total_errors
            return BackfillResult(
                messages=total_messages,
                events=total_events,
                channels=total_channels,
                errors=total_errors,
            )

    def status(self) -> dict[str, Any]:
        return {
            "active": True,
            "state": "running" if self._enabled else "disabled",
            "metrics": {
                **self._metrics,
                "enabled": self._enabled,
                "backfill_days": self._backfill_days,
            },
        }
