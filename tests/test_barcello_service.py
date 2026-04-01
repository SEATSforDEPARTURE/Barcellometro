import asyncio

from app.services.barcello_service import BarcelloService


class FakeDatabase:
    def __init__(self, settings: dict[str, str] | None = None) -> None:
        self._settings = settings or {}

    async def get_setting(self, key: str) -> str | None:
        return self._settings.get(key)

    async def get_barcello_snapshot_before(self, *args, **kwargs):
        return None

    async def put_barcello_window_analysis(self, *args, **kwargs):
        return None

    async def put_barcello_message_classifications(self, *args, **kwargs):
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
    assert BarcelloService._build_trend(70, 60) == {"direction": "improving", "delta": 10, "dominant_driver": ""}
    assert BarcelloService._build_trend(60, 62) == {"direction": "stable", "delta": -2, "dominant_driver": ""}
    assert BarcelloService._build_trend(40, 55) == {"direction": "worsening", "delta": -15, "dominant_driver": ""}


def test_activity_spike_non_hostile_does_not_drop_to_rosso() -> None:
    service = BarcelloService(FakeDatabase())
    messages = [{"author_id": f"u{i%4}", "content": "AHHAHA bellissimo!!!", "ts": "2026-04-01T10:00:00+00:00"} for i in range(90)]
    metrics = service._compute_metrics(messages, window_minutes=10)
    reasons, score = service._score_from_metrics(metrics, score_config={})
    assert score >= 61
    assert not any(r["key"] == "directed_conflict" for r in reasons)


def test_venting_with_profanity_has_limited_impact() -> None:
    service = BarcelloService(FakeDatabase())
    messages = [{"author_id": "u1", "content": "oggi sto incazzato, che giornata di merda", "ts": "2026-04-01T10:00:00+00:00"} for _ in range(8)]
    metrics = service._compute_metrics(messages, window_minutes=20)
    reasons, score = service._score_from_metrics(metrics, score_config={})
    assert metrics["venting_index"] > 0.4
    assert metrics["direct_conflict_index"] == 0
    assert score >= 55


def test_direct_attack_with_mentions_has_strong_impact() -> None:
    service = BarcelloService(FakeDatabase())
    messages = [
        {"author_id": "u1", "content": "sei ridicolo ma che cazzo dici <@2>", "mentions_json": "[\"2\"]", "ts": "2026-04-01T10:00:00+00:00"},
        {"author_id": "u2", "content": "parli tu, imbecille <@1>", "mentions_json": "[\"1\"]", "ts": "2026-04-01T10:00:10+00:00"},
    ] * 6
    metrics = service._compute_metrics(messages, window_minutes=8)
    reasons, score = service._score_from_metrics(metrics, score_config={})
    assert metrics["direct_conflict_index"] > 0.4
    assert any(r["key"] in {"directed_conflict_penalty", "escalation_penalty"} for r in reasons)
    assert score < 45


def test_calming_messages_add_recovery_bonus() -> None:
    service = BarcelloService(FakeDatabase())
    messages = [{"author_id": "u1", "content": "calma raga, non litigate, chiudiamola qui", "ts": "2026-04-01T10:00:00+00:00"} for _ in range(10)]
    metrics = service._compute_metrics(messages, window_minutes=10)
    reasons, score = service._score_from_metrics(metrics, score_config={})
    assert metrics["calming_index"] > 0.25
    assert any(r["key"] == "deescalation_bonus" for r in reasons)
    assert score >= 90
