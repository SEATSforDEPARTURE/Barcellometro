from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.core.config_paths import ENTITLEMENTS_JSON
from app.config.file_loader import load_json_file

if TYPE_CHECKING:
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
        "commands": {
            "aura": {
                "profiles": {
                    "base": {
                        "allowed": True,
                        "features": {
                            "aura": {
                                "enabled": True,
                                "limits": {
                                    "max_range_days": 30,
                                    "max_lookback_days": 60,
                                    "cooldown_seconds": 90,
                                    "max_requests_per_day": 8,
                                    "allow_target_user": False,
                                    "allow_target_channel": False,
                                },
                                "render": {
                                    "details_embeds_max": 1,
                                    "details_title_prefix": "✨ Dettagli Aura",
                                    "sections": ["main.karma", "main.trend", "main.summary", "details.metrics_basic"],
                                },
                                "privacy": {"show_sensitive_penalties": False, "show_mod_flags": False},
                                "missions": {"enabled": False, "daily_count": 3, "daily_bonus_points": 8},
                                "eligibility": {
                                    "min_account_age_days": 7,
                                    "min_messages_in_range": 20,
                                    "exclude_bots": True,
                                    "exclude_roles": [],
                                    "exclude_if_flagged_fake": True,
                                },
                            }
                        },
                    },
                    "mod": {
                        "allowed": True,
                        "features": {
                            "aura": {
                                "enabled": True,
                                "limits": {
                                    "max_range_days": 30,
                                    "max_lookback_days": 180,
                                    "cooldown_seconds": 15,
                                    "max_requests_per_day": 100,
                                    "allow_target_user": True,
                                    "allow_target_channel": True,
                                },
                                "render": {
                                    "details_embeds_max": 3,
                                    "details_title_prefix": "✨ Dettagli Aura Mod",
                                    "sections": [
                                        "main.karma",
                                        "main.trend",
                                        "main.summary",
                                        "details.score_breakdown",
                                        "details.metrics_basic",
                                        "details.metrics_advanced",
                                        "details.interactions_top",
                                        "details.topics",
                                        "details.flags_mod",
                                        "details.missions"
                                    ],
                                },
                                "privacy": {"show_sensitive_penalties": True, "show_mod_flags": True},
                                "missions": {"enabled": True, "daily_count": 3, "daily_bonus_points": 8},
                                "eligibility": {
                                    "min_account_age_days": 7,
                                    "min_messages_in_range": 20,
                                    "exclude_bots": True,
                                    "exclude_roles": [],
                                    "exclude_if_flagged_fake": True,
                                },
                            }
                        },
                    },
                },
                "limits": {
                    "cooldown_seconds": {"base": 90, "mod": 15},
                    "max_requests_per_day": {"base": 8, "mod": 100},
                },
            }
        },
        "features": {"ai": {"allowed_profiles": []}},
    }
)
DEFAULT_MOD_ROLE_IDS = json.dumps([])


class ConfigOverridesService:
    """Apply entitlements/mod role overrides from a JSON file into DB settings.

    Default path: settings/entitlements.json
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

    def __init__(self, database: DatabaseService, *, config_path: str | Path | None = None) -> None:
        self._database = database
        raw_config_path = config_path or os.getenv("ENTITLEMENTS_CONFIG_PATH", str(ENTITLEMENTS_JSON))
        self._config_path = Path(raw_config_path)
        self._last_mtime: float | None = None
        self._missing_logged = False

    async def apply_overrides_once(self) -> None:
        seeded = await self._seed_defaults_if_missing()
        if seeded:
            logger.info("Seeded defaults for %s", ", ".join(seeded))

        if not self._config_path.exists():
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
