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
