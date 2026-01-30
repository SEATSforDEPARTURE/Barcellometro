from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from app.core.service_registry import ServiceRegistry
from app.services.ingest import EventEnvelope

logger = logging.getLogger(__name__)


class ExampleConsumer:
    def __init__(self) -> None:
        self._counts = defaultdict(int)
        self._errors = 0
        self._last_event_ts = None

    async def handle(self, envelope: EventEnvelope) -> None:
        try:
            self._counts[envelope.event_type] += 1
            self._last_event_ts = envelope.ts
        except Exception:  # noqa: BLE001
            logger.exception("Consumer error")
            self._errors += 1

    def status(self) -> dict[str, Any]:
        return {
            "state": "idle",
            "metrics": {
                "events_by_type": dict(self._counts),
                "errors": self._errors,
                "last_event_ts": self._last_event_ts,
            },
        }


def setup(registry: ServiceRegistry) -> None:
    ingest = registry.get("ingest")
    status_service = registry.get("status")

    consumer = ExampleConsumer()
    ingest.register_consumer(consumer.handle)
    status_service.register_component("example_consumer", consumer)
