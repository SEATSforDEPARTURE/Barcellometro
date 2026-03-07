import asyncio
from dataclasses import dataclass

from app.services.entitlements import EntitlementsService


class FakeDatabase:
    def __init__(self, settings: dict[str, str] | None = None) -> None:
        self._settings = settings or {}

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


def test_resolve_profile_priority_and_mod_override() -> None:
    settings = {
        "mod.role_ids": "[123]",
        "entitlements.profile_map": (
            '{\"profiles\": {\"base\": {\"priority\": 0}, \"r1\": {\"priority\": 10}, \"r2\": {\"priority\": 20}},'
            ' \"role_to_profile\": {\"111\": \"r1\", \"222\": \"r2\"}}'
        ),
    }
    service = EntitlementsService(FakeDatabase(settings))
    member = FakeMember(roles=[FakeRole(111), FakeRole(222)], guild_permissions=FakePermissions())
    assert run(service.resolve_profile(member)) == "r2"

    mod_member = FakeMember(roles=[FakeRole(123)], guild_permissions=FakePermissions())
    assert run(service.resolve_profile(mod_member)) == "mod"

    admin_member = FakeMember(roles=[FakeRole(111)], guild_permissions=FakePermissions(administrator=True))
    assert run(service.resolve_profile(admin_member)) == "mod"


def test_subcommand_allowed_by_profile() -> None:
    policies = (
        '{\"commands\": {\"barcello\": {\"subcommands\": {\"base\": [\"view\"], \"r1\": [\"view\", \"reason\"]}}}}'
    )
    settings = {"entitlements.profile_map": '{\"profiles\": {\"base\": {\"priority\": 0}, \"r1\": {\"priority\": 10}}, \"role_to_profile\": {\"111\": \"r1\"}}', "entitlements.policies": policies}
    service = EntitlementsService(FakeDatabase(settings))
    base_member = FakeMember(roles=[], guild_permissions=FakePermissions())
    r1_member = FakeMember(roles=[FakeRole(111)], guild_permissions=FakePermissions())

    assert run(service.is_subcommand_allowed(base_member, "barcello", "view")) is True
    assert run(service.is_subcommand_allowed(base_member, "barcello", "reason")) is False
    assert run(service.is_subcommand_allowed(r1_member, "barcello", "reason")) is True


def test_has_capability_and_defaults() -> None:
    service = EntitlementsService(FakeDatabase())
    mod_member = FakeMember(roles=[], guild_permissions=FakePermissions(administrator=True))
    base_member = FakeMember(roles=[], guild_permissions=FakePermissions())

    assert run(service.has_capability(mod_member, "riassunto", "summary.include_names_when_tense")) is True
    assert run(service.has_capability(base_member, "riassunto", "summary.include_names_when_tense")) is False
    assert run(service.is_subcommand_allowed(base_member, "aura", "view")) is True
    assert run(service.is_subcommand_allowed(base_member, "aura", "debug")) is False
    assert run(service.is_feature_allowed(base_member, "ai")) is False


def test_command_profile_config_defaults_and_overrides() -> None:
    policies = (
        "{"
        '\"commands\": {'
        '  \"barcello\": {'
        '    \"profiles\": {'
        '      \"base\": {\"allowed\": false, \"messages\": {\"dm_text\": \"Serve PLUS.\"}},'
        '      \"role1\": {'
        '        \"allowed\": true,'
        '        \"output\": {\"show_score\": true, \"show_motivation\": true},'
        '        \"messages\": {\"footer_text\": \"Passa a PRO per il trend.\"},'
        '        \"capabilities\": [\"analysis.local\"]'
        "      },"
        '      \"role2\": {'
        '        \"allowed\": true,'
        '        \"output\": {\"show_score\": true, \"show_motivation\": true, \"show_trend\": true},'
        '        \"messages\": {\"footer_text\": \"Passa a PRO MAX per i consigli.\"},'
        '        \"capabilities\": [\"analysis.ai_preferred\"]'
        "      },"
        '      \"role3\": {'
        '        \"allowed\": true,'
        '        \"output\": {\"show_score\": true, \"show_motivation\": true, \"show_trend\": true, \"show_advice\": true},'
        '        \"capabilities\": [\"analysis.ai_preferred\"]'
        "      },"
        '      \"mod\": {'
        '        \"allowed\": true,'
        '        \"output\": {'
        '          \"show_score\": true,'
        '          \"show_motivation\": true,'
        '          \"show_trend\": true,'
        '          \"show_advice\": true,'
        '          \"show_mod_metrics\": true'
        "        },"
        '        \"capabilities\": [\"analysis.ai_preferred\"]'
        "      }"
        "    }"
        "  }"
        "}"
        "}"
    )
    profile_map = (
        "{"
        '\"profiles\": {\"base\": {\"priority\": 0}, \"role1\": {\"priority\": 1}, \"role2\": {\"priority\": 2}, \"role3\": {\"priority\": 3}},'
        '\"role_to_profile\": {\"111\": \"role1\", \"222\": \"role2\", \"333\": \"role3\"}'
        "}"
    )
    settings = {"entitlements.profile_map": profile_map, "entitlements.policies": policies}
    service = EntitlementsService(FakeDatabase(settings))

    base_member = FakeMember(roles=[], guild_permissions=FakePermissions())
    role1_member = FakeMember(roles=[FakeRole(111)], guild_permissions=FakePermissions())
    role2_member = FakeMember(roles=[FakeRole(222)], guild_permissions=FakePermissions())
    role3_member = FakeMember(roles=[FakeRole(333)], guild_permissions=FakePermissions())
    mod_member = FakeMember(roles=[], guild_permissions=FakePermissions(administrator=True))

    base_config = run(service.get_command_profile_config(base_member, "barcello"))
    assert base_config["allowed"] is False
    assert base_config["messages"]["dm_text"] == "Serve PLUS."

    role1_config = run(service.get_command_profile_config(role1_member, "barcello"))
    assert role1_config["output"]["show_trend"] is False
    assert role1_config["messages"]["footer_text"] == "Passa a PRO per il trend."

    role2_config = run(service.get_command_profile_config(role2_member, "barcello"))
    assert role2_config["output"]["show_trend"] is True
    assert role2_config["messages"]["footer_text"] == "Passa a PRO MAX per i consigli."

    role3_config = run(service.get_command_profile_config(role3_member, "barcello"))
    assert role3_config["output"]["show_advice"] is True

    mod_config = run(service.get_command_profile_config(mod_member, "barcello"))
    assert mod_config["output"]["show_mod_metrics"] is True


def test_aura_feature_sections_by_tier() -> None:
    policies = {
        "commands": {
            "aura": {
                "profiles": {
                    "base": {"features": {"aura": {"enabled": True, "render": {"sections": []}, "limits": {"allow_target_user": False}}}},
                    "role1": {"features": {"aura": {"enabled": True, "render": {"sections": ["details.missions", "details.note.role1"]}, "limits": {"allow_target_user": False}}}},
                    "role2": {"features": {"aura": {"enabled": True, "render": {"sections": ["details.missions", "details.profile", "details.note.role2"]}, "limits": {"allow_target_user": False}}}},
                    "role3": {"features": {"aura": {"enabled": True, "render": {"sections": ["details.missions", "details.profile", "details.advice"]}, "limits": {"allow_target_user": False}}}},
                    "mod": {"features": {"aura": {"enabled": True, "render": {"sections": ["details.missions", "details.profile", "details.advice", "details.metrics_aggregated"]}, "limits": {"allow_target_user": True}}}},
                }
            }
        }
    }
    profile_map = {
        "profiles": {"base": {"priority": 0}, "role1": {"priority": 1}, "role2": {"priority": 2}, "role3": {"priority": 3}},
        "role_to_profile": {"11": "role1", "22": "role2", "33": "role3"},
    }
    settings = {"entitlements.profile_map": __import__('json').dumps(profile_map), "entitlements.policies": __import__('json').dumps(policies), "mod.role_ids": "[]"}
    service = EntitlementsService(FakeDatabase(settings))

    base = FakeMember(roles=[], guild_permissions=FakePermissions())
    role1 = FakeMember(roles=[FakeRole(11)], guild_permissions=FakePermissions())
    role2 = FakeMember(roles=[FakeRole(22)], guild_permissions=FakePermissions())
    role3 = FakeMember(roles=[FakeRole(33)], guild_permissions=FakePermissions())
    mod = FakeMember(roles=[], guild_permissions=FakePermissions(administrator=True))

    assert run(service.get_feature_profile_config(base, "aura"))["render"]["sections"] == []
    assert "details.note.role1" in run(service.get_feature_profile_config(role1, "aura"))["render"]["sections"]
    assert "details.profile" in run(service.get_feature_profile_config(role2, "aura"))["render"]["sections"]
    assert "details.advice" in run(service.get_feature_profile_config(role3, "aura"))["render"]["sections"]
    mod_cfg = run(service.get_feature_profile_config(mod, "aura"))
    assert "details.metrics_aggregated" in mod_cfg["render"]["sections"]
    assert mod_cfg["limits"]["allow_target_user"] is True
