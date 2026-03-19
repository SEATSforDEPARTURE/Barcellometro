import asyncio

from app.features.barcello.services.barcello_service import BarcelloService


class FakeDatabase:
    def __init__(self, settings: dict[str, str] | None = None) -> None:
        self._settings = settings or {}

    async def get_setting(self, key: str) -> str | None:
        return self._settings.get(key)

    async def get_barcello_snapshot_before(self, *args, **kwargs):
        return None


def run(coro):
    return asyncio.run(coro)


def test_get_color_default_and_custom() -> None:
    service = BarcelloService(FakeDatabase())
    assert run(service.get_color(10)) == "nero"
    assert run(service.get_color(55)) == "giallo"
    assert run(service.get_color(85)) == "verde"

    custom_settings = {
        "barcello.color_ranges": (
            "[{\"min\": 0, \"max\": 50, \"color\": \"#000\", \"label\": \"low\"},"
            " {\"min\": 51, \"max\": 100, \"color\": \"#0f0\", \"label\": \"high\"}]"
        )
    }
    custom_service = BarcelloService(FakeDatabase(custom_settings))
    assert run(custom_service.get_color(25)) == "low"
    assert run(custom_service.get_color(90)) == "high"


def test_clamp_score() -> None:
    assert BarcelloService._clamp_score(120) == 100
    assert BarcelloService._clamp_score(-10) == 0
    assert BarcelloService._clamp_score(42.2) == 42


def test_trend_computation() -> None:
    assert BarcelloService._build_trend(70, 60) == {"direction": "improving", "delta": 10}
    assert BarcelloService._build_trend(60, 62) == {"direction": "stable", "delta": -2}
    assert BarcelloService._build_trend(40, 55) == {"direction": "worsening", "delta": -15}
