from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from app.services.config_file_loader import load_json_file
from app.services.database import DatabaseService

logger = logging.getLogger(__name__)


class ConfigOverridesService:
    """Apply entitlements/mod role overrides from a JSON file into DB settings.

    Default path: app/settings/entitlements.json
    ENV override: ENTITLEMENTS_CONFIG_PATH=/path/to/entitlements.json
    Optional reload: ENTITLEMENTS_CONFIG_RELOAD=true (polling)

    JSON structure:
    {
      "mod": { "role_ids": ["..."] },
      "entitlements": {
        "profile_map": { ... },
        "policies": { ... }
      }
    }
    """

    def __init__(self, database: DatabaseService, *, config_path: str | None = None) -> None:
        self._database = database
        self._config_path = config_path or os.getenv(
            "ENTITLEMENTS_CONFIG_PATH",
            os.path.join("app", "settings", "entitlements.json"),
        )
        self._last_mtime: float | None = None

    async def apply_overrides_once(self) -> None:
        payload = load_json_file(self._config_path)
        if not payload:
            return
        updated_keys: list[str] = []
        entitlements = payload.get("entitlements") if isinstance(payload, dict) else None
        if isinstance(entitlements, dict):
            if "profile_map" in entitlements:
                await self._database.set_setting("entitlements.profile_map", self._to_json(entitlements["profile_map"]))
                updated_keys.append("entitlements.profile_map")
            if "policies" in entitlements:
                await self._database.set_setting("entitlements.policies", self._to_json(entitlements["policies"]))
                updated_keys.append("entitlements.policies")
        mod = payload.get("mod") if isinstance(payload, dict) else None
        if isinstance(mod, dict) and "role_ids" in mod:
            await self._database.set_setting("mod.role_ids", self._to_json(mod["role_ids"]))
            updated_keys.append("mod.role_ids")
        if updated_keys:
            ts = datetime.now(timezone.utc).isoformat()
            logger.info("Applied config overrides at %s: %s", ts, ", ".join(updated_keys))

    async def watch_for_changes(self, *, poll_seconds: int = 15) -> None:
        while True:
            try:
                mtime = self._get_mtime()
                if mtime is not None and (self._last_mtime is None or mtime > self._last_mtime):
                    self._last_mtime = mtime
                    await self.apply_overrides_once()
                    logger.info("Reloaded entitlements config from %s", self._config_path)
                elif mtime is None and self._last_mtime is not None:
                    self._last_mtime = None
                await asyncio.sleep(poll_seconds)
            except Exception:
                logger.exception("Failed while reloading entitlements config")
                await asyncio.sleep(poll_seconds)

    def _get_mtime(self) -> float | None:
        try:
            return os.path.getmtime(self._config_path)
        except OSError:
            return None

    @staticmethod
    def _to_json(value: Any) -> str:
        import json

        return json.dumps(value)
