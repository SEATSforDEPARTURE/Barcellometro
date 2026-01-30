from __future__ import annotations

from typing import Any

from app.services.database import DatabaseService


class AiService:
    def __init__(self, database: DatabaseService) -> None:
        self._database = database
        self._enabled = False
        self._metrics = {
            "last_updated_ts": None,
        }

    async def load_settings(self) -> None:
        stored = await self._database.get_setting("ai_enabled")
        if stored is None:
            await self._database.set_setting("ai_enabled", "false")
            self._enabled = False
        else:
            self._enabled = stored.lower() in {"1", "true", "yes", "y"}

    async def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        await self._database.set_setting("ai_enabled", "true" if enabled else "false")

    def is_enabled(self) -> bool:
        return self._enabled

    def status(self) -> dict[str, Any]:
        return {
            "active": True,
            "state": "running" if self._enabled else "disabled",
            "metrics": dict(self._metrics),
        }
