import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.services.aura import AuraEligibilityService, render_karma_bar
from app.services.entitlements import EntitlementsService


class FakeDatabase:
    def __init__(self, *, settings=None, message_count: int = 0):
        self._settings = settings or {}
        self._message_count = message_count

    async def get_setting(self, key: str):
        return self._settings.get(key)

    async def count_user_messages_in_range(self, guild_id: str, user_id: str, start_ts: str, end_ts: str):
        return self._message_count


@dataclass
class FakeRole:
    id: int
    name: str = "member"


@dataclass
class FakePermissions:
    administrator: bool = False


@dataclass
class FakeMember:
    id: int
    roles: list[FakeRole]
    guild_permissions: FakePermissions
    bot: bool = False
    created_at: datetime = datetime.now(timezone.utc) - timedelta(days=90)


def run(coro):
    return asyncio.run(coro)


def test_aura_entitlements_eligibility_gate_and_target_disabled_for_base() -> None:
    policies = {
        "commands": {
            "aura": {
                "profiles": {
                    "base": {
                        "features": {
                            "aura": {
                                "enabled": True,
                                "limits": {"allow_target_user": False},
                                "eligibility": {"min_messages_in_range": 20, "exclude_bots": True},
                            }
                        }
                    }
                }
            }
        }
    }
    settings = {
        "entitlements.policies": json.dumps(policies),
        "entitlements.profile_map": json.dumps({"profiles": {"base": {"priority": 0}}, "role_to_profile": {}}),
        "mod.role_ids": "[]",
    }
    entitlements = EntitlementsService(FakeDatabase(settings=settings))
    member = FakeMember(id=1, roles=[], guild_permissions=FakePermissions())
    aura_cfg = run(entitlements.get_feature_profile_config(member, "aura"))
    assert aura_cfg["eligibility"]["min_messages_in_range"] == 20
    assert aura_cfg["limits"]["allow_target_user"] is False


def test_render_karma_bar_cursor_edges() -> None:
    assert "🟣" in render_karma_bar(0)
    assert render_karma_bar(0).endswith("0%")
    assert render_karma_bar(50).endswith("50%")
    assert render_karma_bar(100).endswith("100%")


def test_eligibility_bots_and_min_messages() -> None:
    policies = {
        "commands": {
            "aura": {
                "profiles": {
                    "base": {
                        "features": {
                            "aura": {
                                "enabled": True,
                                "eligibility": {
                                    "min_account_age_days": 7,
                                    "min_messages_in_range": 20,
                                    "exclude_bots": True,
                                    "exclude_roles": [],
                                    "exclude_if_flagged_fake": True,
                                },
                            }
                        }
                    }
                }
            }
        }
    }
    settings = {
        "entitlements.policies": json.dumps(policies),
        "entitlements.profile_map": json.dumps({"profiles": {"base": {"priority": 0}}, "role_to_profile": {}}),
        "mod.role_ids": "[]",
    }

    db_low = FakeDatabase(settings=settings, message_count=5)
    ent = EntitlementsService(db_low)
    service = AuraEligibilityService(db_low, ent)
    member = FakeMember(id=1, roles=[], guild_permissions=FakePermissions(), bot=False)
    result = run(service.evaluate_member(member, "10", datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()))
    assert result.eligible is False
    assert "almeno 20 messaggi" in result.reason

    db_ok = FakeDatabase(settings=settings, message_count=100)
    ent_ok = EntitlementsService(db_ok)
    service_ok = AuraEligibilityService(db_ok, ent_ok)
    bot_member = FakeMember(id=2, roles=[], guild_permissions=FakePermissions(), bot=True)
    bot_result = run(service_ok.evaluate_member(bot_member, "10", datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()))
    assert bot_result.eligible is False
    assert "bot" in bot_result.reason.lower()
