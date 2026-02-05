from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from app.services.config_file_loader import load_json_file
from app.services.database import DatabaseService

logger = logging.getLogger(__name__)

DEFAULT_ENTITLEMENTS_PROFILE_MAP = json.dumps(
    {
        "profiles": {"base": {"priority": 0}, "mod": {"priority": 100}},
        "role_to_profile": {},
    }
)
DEFAULT_ENTITLEMENTS_POLICIES = json.dumps(
    {
        "commands": {},
        "features": {"ai": {"allowed_profiles": []}},
    }
)
DEFAULT_MOD_ROLE_IDS = json.dumps([])


class ConfigOverridesService:
    """Apply entitlements/mod role overrides from a JSON file into DB settings.

    Default path: app/settings/entitlements.json
    ENV override: ENTITLEMENTS_CONFIG_PATH=/path/to/entitlements.json
    Optional reload: ENTITLEMENTS_CONFIG_RELOAD=true (polling)
    JSON: standard .json (or .jsonc with comments stripped)

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
        self._missing_logged = False

    async def apply_overrides_once(self) -> None:
        seeded = await self._seed_defaults_if_missing()
        if seeded:
            logger.info("Seeded defaults for %s", ", ".join(seeded))

        if not os.path.exists(self._config_path):
            if not self._missing_logged:
                logger.info("Overrides file not found at %s, using defaults", self._config_path)
                self._missing_logged = True
            return
        self._missing_logged = False

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
            logger.info("Applied overrides from %s at %s: %s", self._config_path, ts, ", ".join(updated_keys))

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

    async def _seed_defaults_if_missing(self) -> list[str]:
        seeded: list[str] = []
        if await self._database.get_setting("entitlements.profile_map") is None:
            await self._database.set_setting("entitlements.profile_map", DEFAULT_ENTITLEMENTS_PROFILE_MAP)
            seeded.append("entitlements.profile_map")
        if await self._database.get_setting("entitlements.policies") is None:
            await self._database.set_setting("entitlements.policies", DEFAULT_ENTITLEMENTS_POLICIES)
            seeded.append("entitlements.policies")
        if await self._database.get_setting("mod.role_ids") is None:
            await self._database.set_setting("mod.role_ids", DEFAULT_MOD_ROLE_IDS)
            seeded.append("mod.role_ids")
        return seeded

    @staticmethod
    def _to_json(value: Any) -> str:
        return json.dumps(value)
