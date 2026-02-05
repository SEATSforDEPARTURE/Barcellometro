from __future__ import annotations

import json
import logging
from typing import Any

from app.services.database import DatabaseService

logger = logging.getLogger(__name__)

DEFAULT_PROFILE_MAP = {
    "profiles": {
        "base": {"priority": 0},
        "mod": {"priority": 100},
    },
    "role_to_profile": {},
}

DEFAULT_COMMAND_POLICY = {
    "subcommands": {
        "base": ["view"],
        "mod": ["view", "target_user"],
    },
    "detail_level": {
        "base": "score",
        "mod": "mod_extras",
    },
    "capabilities": {
        "mod": ["summary.include_names_when_tense"],
    },
}

DEFAULT_POLICIES = {
    "commands": {},
    "features": {
        "ai": {"allowed_profiles": []},
    },
}


class EntitlementsService:
    def __init__(self, database: DatabaseService) -> None:
        self._database = database

    async def resolve_profile(self, member: Any) -> str:
        if bool(getattr(getattr(member, "guild_permissions", None), "administrator", False)):
            return "mod"

        mod_role_ids = await self._get_json_setting("mod.role_ids", [])
        role_ids = [str(getattr(role, "id", "")) for role in getattr(member, "roles", [])]
        if any(role_id in {str(role_id) for role_id in mod_role_ids} for role_id in role_ids):
            return "mod"

        profile_map = await self._get_json_setting("entitlements.profile_map", DEFAULT_PROFILE_MAP)
        profiles = profile_map.get("profiles", {}) if isinstance(profile_map, dict) else {}
        role_to_profile = profile_map.get("role_to_profile", {}) if isinstance(profile_map, dict) else {}

        best_profile = "base"
        best_priority = profiles.get("base", {}).get("priority", 0)
        for role_id in role_ids:
            profile = role_to_profile.get(role_id)
            if profile is None:
                continue
            priority = 0
            if isinstance(profiles.get(profile), dict):
                priority = profiles.get(profile, {}).get("priority", 0)
            if priority > best_priority:
                best_profile = profile
                best_priority = priority
        return best_profile

    async def get_detail_level(self, member: Any, command: str) -> str:
        profile = await self.resolve_profile(member)
        policy = await self._get_command_policy(command)
        detail_level = policy.get("detail_level", {}) if isinstance(policy, dict) else {}
        if profile in detail_level:
            return detail_level[profile]
        if "base" in detail_level:
            return detail_level["base"]
        return "score"

    async def is_subcommand_allowed(self, member: Any, command: str, subcommand: str) -> bool:
        profile = await self.resolve_profile(member)
        policy = await self._get_command_policy(command)
        subcommands = policy.get("subcommands", {}) if isinstance(policy, dict) else {}
        allowed = subcommands.get(profile)
        if allowed is None:
            allowed = subcommands.get("base", [])
        return subcommand in (allowed or [])

    async def has_capability(self, member: Any, command: str, capability: str) -> bool:
        profile = await self.resolve_profile(member)
        policy = await self._get_command_policy(command)
        capabilities = policy.get("capabilities", {}) if isinstance(policy, dict) else {}
        allowed = capabilities.get(profile)
        if allowed is None:
            allowed = capabilities.get("base", [])
        return capability in (allowed or [])

    async def is_feature_allowed(self, member: Any, feature: str) -> bool:
        profile = await self.resolve_profile(member)
        policies = await self._get_json_setting("entitlements.policies", DEFAULT_POLICIES)
        features = policies.get("features", {}) if isinstance(policies, dict) else {}
        feature_policy = features.get(feature, {}) if isinstance(features, dict) else {}
        allowed_profiles = feature_policy.get("allowed_profiles", [])
        return profile in allowed_profiles

    async def _get_command_policy(self, command: str) -> dict[str, Any]:
        policies = await self._get_json_setting("entitlements.policies", DEFAULT_POLICIES)
        commands = policies.get("commands", {}) if isinstance(policies, dict) else {}
        if isinstance(commands, dict) and command in commands:
            policy = commands.get(command, {})
            if isinstance(policy, dict):
                return self._merge_command_policy(DEFAULT_COMMAND_POLICY, policy)
        return DEFAULT_COMMAND_POLICY

    async def _get_json_setting(self, key: str, default: Any) -> Any:
        raw = await self._database.get_setting(key)
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in setting %s", key)
            return default

    def _merge_command_policy(self, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged.get(key, {}), **value}
            else:
                merged[key] = value
        return merged
