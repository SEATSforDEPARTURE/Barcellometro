import asyncio
import json
import sys
import types
from dataclasses import dataclass
from pathlib import Path

# app.services.database imports aiosqlite at module import time; stub is enough for these unit calls.
sys.modules.setdefault("aiosqlite", types.SimpleNamespace())

from app.services.entitlements import EntitlementsService


class FakeDatabase:
    def __init__(self, settings: dict[str, str]) -> None:
        self._settings = settings

    async def get_setting(self, key: str) -> str | None:
        return self._settings.get(key)


@dataclass
class FakeRole:
    id: int


@dataclass
class FakePermissions:
    administrator: bool = False


@dataclass
class FakeMember:
    roles: list[FakeRole]
    guild_permissions: FakePermissions


def run(coro):
    return asyncio.run(coro)


def test_entitlements_example_runtime_read_paths_are_valid() -> None:
    payload = json.loads(Path("app/settings/entitlements.example.json").read_text())

    assert payload["mod"]["role_ids"] == []
    assert payload["entitlements"]["profile_map"]["role_to_profile"] == {}

    settings = {
        "mod.role_ids": json.dumps(payload["mod"]["role_ids"]),
        "entitlements.profile_map": json.dumps(payload["entitlements"]["profile_map"]),
        "entitlements.policies": json.dumps(payload["entitlements"]["policies"]),
    }
    service = EntitlementsService(FakeDatabase(settings))

    base = FakeMember(roles=[], guild_permissions=FakePermissions())
    mod = FakeMember(roles=[], guild_permissions=FakePermissions(administrator=True))

    # profile resolution + feature gate
    assert run(service.resolve_profile(base)) == "base"
    assert run(service.resolve_profile(mod)) == "mod"
    assert isinstance(run(service.is_feature_allowed(base, "ai")), bool)

    # command profile config used by /barcello and /riassunto
    for command in ("barcello", "riassunto", "resoconto"):
        cfg = run(service.get_command_profile_config(base, command))
        assert isinstance(cfg["allowed"], bool)
        assert isinstance(cfg["messages"], dict)
        assert isinstance(cfg["capabilities"], list)
        assert isinstance(cfg["output"]["show_score"], bool)

    # root command policy maps used by future helpers
    for command in ("barcello", "riassunto", "resoconto"):
        assert isinstance(run(service.is_subcommand_allowed(base, command, "view")), bool)
        assert isinstance(run(service.get_detail_level(base, command)), str)
        assert isinstance(run(service.has_capability(mod, command, "analysis.ai_preferred")), bool)

    # /riassunto max window seconds
    assert isinstance(run(service.get_command_limit_seconds(base, "riassunto", "max_window_seconds")), int)

    # /aura feature profile config consumed by command + eligibility service
    aura_cfg = run(service.get_feature_profile_config(base, "aura"))
    for key in ("enabled", "limits", "render", "privacy", "missions", "eligibility"):
        assert key in aura_cfg
    assert isinstance(aura_cfg["limits"]["allow_target_user"], bool)


def test_entitlements_example_mod_has_aura_report_capability() -> None:
    payload = json.loads(Path("app/settings/entitlements.example.json").read_text())
    mod_caps = payload["entitlements"]["policies"]["commands"]["resoconto"]["profiles"]["mod"]["capabilities"]
    assert "aura_report.view" in mod_caps
