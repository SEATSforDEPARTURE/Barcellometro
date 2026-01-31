from __future__ import annotations

from typing import Any

from app.services.database import DatabaseService


class StatusService:
    def __init__(self, database: DatabaseService) -> None:
        self._database = database
        self._components: dict[str, Any] = {}

    def register_component(self, name: str, component: Any) -> None:
        self._components[name] = component

    def list_components(self) -> dict[str, Any]:
        return dict(self._components)

    async def general_status(self) -> dict[str, Any]:
        return {
            "db_path": self._database.db_path,
            "retention_days": int((await self._database.get_setting("retention_days")) or 0),
            "enabled_channels": await self._database.count_enabled_channels(),
            "users_count": await self._database.count_table("users"),
            "messages_count": await self._database.count_table("messages"),
            "events_count": await self._database.count_table("events"),
            "last_event_ts": await self._database.latest_event_ts(),
        }

    def component_status(self, name: str) -> dict[str, Any]:
        component = self._components.get(name)
        if component is None:
            return {
                "active": False,
                "state": "missing",
                "metrics": {},
            }
        status = component.status() if hasattr(component, "status") else {}
        return {
            "active": True,
            "state": status.get("state", "unknown"),
            "metrics": status.get("metrics", {}),
        }
