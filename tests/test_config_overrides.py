import asyncio

from app.services.config_overrides import ConfigOverridesService


class FakeDatabase:
    def __init__(self) -> None:
        self.settings: dict[str, str] = {}

    async def get_setting(self, key: str) -> str | None:
        return self.settings.get(key)

    async def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value


def run(coro):
    return asyncio.run(coro)


def test_apply_overrides_seeds_defaults(tmp_path) -> None:
    database = FakeDatabase()
    config_path = tmp_path / "entitlements.json"
    service = ConfigOverridesService(database, config_path=str(config_path))
    run(service.apply_overrides_once())
    assert database.settings.get("entitlements.profile_map") is not None
    assert database.settings.get("entitlements.policies") is not None
    assert database.settings.get("mod.role_ids") is not None
