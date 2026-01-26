from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.services.database import DatabaseService

logger = logging.getLogger(__name__)


class RetentionService:
    def __init__(self, database: DatabaseService, default_days: int) -> None:
        self._database = database
        self._default_days = default_days
        self._retention_days: int = default_days
        self._task: Optional[asyncio.Task[None]] = None
        self._metrics = {
            "last_run_ts": None,
            "errors": 0,
            "last_deleted_messages": 0,
            "last_deleted_events": 0,
        }

    async def load_retention(self) -> None:
        stored = await self._database.get_setting("retention_days")
        if stored is None:
            await self._database.set_setting("retention_days", str(self._default_days))
            self._retention_days = self._default_days
        else:
            self._retention_days = int(stored)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001
                logger.exception("Retention task failed")
                self._metrics["errors"] += 1
            await asyncio.sleep(6 * 60 * 60)

    async def run_once(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
        cutoff_iso = cutoff.isoformat()
        deleted_messages = await self._database.prune_messages(cutoff_iso)
        deleted_events = await self._database.prune_events(cutoff_iso)
        logger.info(
            "Retention prune completed: messages=%s events=%s",
            deleted_messages,
            deleted_events,
        )
        self._metrics["last_run_ts"] = datetime.now(timezone.utc).isoformat()
        self._metrics["last_deleted_messages"] = deleted_messages
        self._metrics["last_deleted_events"] = deleted_events

    async def get_retention_days(self) -> int:
        return self._retention_days

    async def set_retention_days(self, days: int) -> None:
        self._retention_days = days
        await self._database.set_setting("retention_days", str(days))

    def status(self) -> dict[str, Any]:
        return {
            "active": True,
            "state": "running",
            "retention_days": self._retention_days,
            "metrics": dict(self._metrics),
        }
