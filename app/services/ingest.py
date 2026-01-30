from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from app.services.database import DatabaseService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    event_type: str
    platform: str
    ts: str
    guild_id: Optional[str]
    channel_id: Optional[str]
    thread_id: Optional[str]
    author_id: Optional[str]
    content: Optional[str]
    meta: dict[str, Any] = field(default_factory=dict)
    raw: Optional[dict[str, Any]] = None


EventConsumer = Callable[[EventEnvelope], Awaitable[None]]


class IngestService:
    def __init__(self, database: DatabaseService) -> None:
        self._database = database
        self._consumers: list[EventConsumer] = []
        self._metrics = {
            "processed": 0,
            "errors": 0,
            "last_event_ts": None,
        }

    def register_consumer(self, consumer: EventConsumer) -> None:
        self._consumers.append(consumer)

    async def emit(self, envelope: EventEnvelope) -> None:
        try:
            await self._store_event(envelope)
            await self._notify_consumers(envelope)
            self._metrics["processed"] += 1
            self._metrics["last_event_ts"] = envelope.ts
        except Exception:  # noqa: BLE001 - log and continue
            logger.exception("Failed to ingest event %s", envelope.event_type)
            self._metrics["errors"] += 1

    async def _notify_consumers(self, envelope: EventEnvelope) -> None:
        if not self._consumers:
            return
        await asyncio.gather(*(consumer(envelope) for consumer in self._consumers))

    async def _store_event(self, envelope: EventEnvelope) -> None:
        meta = dict(envelope.meta)
        await self._database.insert_event(
            ts=envelope.ts,
            event_type=envelope.event_type,
            platform=envelope.platform,
            guild_id=envelope.guild_id,
            channel_id=envelope.channel_id,
            actor_id=envelope.author_id,
            target_id=meta.get("target_id"),
            meta=meta,
        )

    def status(self) -> dict[str, Any]:
        return {
            "active": True,
            "state": "running",
            "metrics": dict(self._metrics),
        }
