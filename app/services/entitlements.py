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
        profile, _ = await self.resolve_profile_with_role_id(member)
        return profile

    async def resolve_profile_with_role_id(self, member: Any) -> tuple[str, str | None]:
        if bool(getattr(getattr(member, "guild_permissions", None), "administrator", False)):
            logger.debug("resolve_profile_with_role_id: admin perms => mod")
            return "mod", None

        mod_role_ids = await self._get_json_setting("mod.role_ids", [])
        role_ids = [str(getattr(role, "id", "")) for role in getattr(member, "roles", [])]
        for role_id in role_ids:
            if role_id in {str(role_id) for role_id in mod_role_ids}:
                logger.debug("resolve_profile_with_role_id: mod role match => mod (%s)", role_id)
                return "mod", role_id

        profile_map = await self._get_json_setting("entitlements.profile_map", DEFAULT_PROFILE_MAP)
        profiles = profile_map.get("profiles", {}) if isinstance(profile_map, dict) else {}
        role_to_profile = profile_map.get("role_to_profile", {}) if isinstance(profile_map, dict) else {}

        best_profile = "base"
        best_priority = profiles.get("base", {}).get("priority", 0)
        winner_role_id: str | None = None
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
                winner_role_id = role_id
        logger.debug(
            "resolve_profile_with_role_id: selected profile=%s winner_role_id=%s",
            best_profile,
            winner_role_id,
        )
        return best_profile, winner_role_id

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
        allowed_profiles = feature_policy.get("allowed_profiles")
        if not isinstance(allowed_profiles, list):
            logger.debug("Feature %s not configured; default allow.", feature)
            return True
        return profile in allowed_profiles

    async def get_command_profile_config(self, member: Any, command: str) -> dict[str, Any]:
        profile = await self.resolve_profile(member)
        policies = await self._get_json_setting("entitlements.policies", DEFAULT_POLICIES)
        commands = policies.get("commands", {}) if isinstance(policies, dict) else {}
        command_policy = commands.get(command, {}) if isinstance(commands, dict) else {}
        profiles = command_policy.get("profiles", {}) if isinstance(command_policy, dict) else {}
        raw_profile = profiles.get(profile)
        if raw_profile is None:
            raw_profile = profiles.get("base")
        if not isinstance(raw_profile, dict):
            raw_profile = {}

        output_raw = raw_profile.get("output", {}) if isinstance(raw_profile.get("output"), dict) else {}
        messages_raw = raw_profile.get("messages", {}) if isinstance(raw_profile.get("messages"), dict) else {}
        capabilities_raw = raw_profile.get("capabilities", [])
        capabilities = capabilities_raw if isinstance(capabilities_raw, list) else []

        output_defaults = {
            "show_score": True,
            "show_motivation": False,
            "show_trend": False,
            "show_advice": False,
            "show_mod_metrics": False,
        }
        output = {key: bool(output_raw.get(key, default)) for key, default in output_defaults.items()}

        messages: dict[str, Any] = {}
        if "dm_text" in messages_raw:
            messages["dm_text"] = messages_raw.get("dm_text")
        if "footer_text" in messages_raw:
            messages["footer_text"] = messages_raw.get("footer_text")

        return {
            "allowed": bool(raw_profile.get("allowed", True)),
            "output": output,
            "capabilities": capabilities,
            "messages": messages,
        }

    async def get_command_limit_seconds(self, member: Any, command: str, limit_key: str) -> int | None:
        profile = await self.resolve_profile(member)
        policy = await self._get_command_policy(command)
        limits = policy.get("limits", {}) if isinstance(policy, dict) else {}
        mapping = limits.get(limit_key, {}) if isinstance(limits, dict) else {}

        if isinstance(mapping, dict):
            val = mapping.get(profile)
            if isinstance(val, int) and val > 0:
                return val
        return None

    async def get_feature_profile_config(self, member: Any, feature: str) -> dict[str, Any]:
        profile = await self.resolve_profile(member)
        policies = await self._get_json_setting("entitlements.policies", DEFAULT_POLICIES)
        commands = policies.get("commands", {}) if isinstance(policies, dict) else {}
        command_policy = commands.get("aura", {}) if isinstance(commands, dict) else {}
        profiles = command_policy.get("profiles", {}) if isinstance(command_policy, dict) else {}
        base = profiles.get("base", {}) if isinstance(profiles.get("base"), dict) else {}
        selected = profiles.get(profile, base)
        if not isinstance(selected, dict):
            selected = base
        features = selected.get("features", {}) if isinstance(selected.get("features"), dict) else {}
        feature_cfg = features.get(feature, {}) if isinstance(features, dict) else {}
        if not isinstance(feature_cfg, dict):
            return {}
        return feature_cfg

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
