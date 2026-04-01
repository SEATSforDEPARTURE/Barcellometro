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
    assert BarcelloService._build_trend(70, 60)["direction"] == "improving"
    assert BarcelloService._build_trend(70, 60)["delta"] == 10
    assert BarcelloService._build_trend(60, 62)["direction"] == "stable"
    assert BarcelloService._build_trend(60, 62)["delta"] == -2
    assert BarcelloService._build_trend(40, 55)["direction"] == "worsening"
    assert BarcelloService._build_trend(40, 55)["delta"] == -15


def test_activity_spike_non_hostile_does_not_drop_to_rosso() -> None:
    service = BarcelloService(FakeDatabase())
    messages = [{"author_id": f"u{i%4}", "content": "AHHAHA bellissimo!!!", "ts": "2026-04-01T10:00:00+00:00"} for i in range(90)]
    metrics = service._compute_metrics(messages, window_minutes=10)
    reasons, score = service._score_from_metrics(metrics, score_config={})
    assert score >= 61
    assert not any(r["key"] == "directed_conflict" for r in reasons)


def test_dense_two_user_back_and_forth_without_hostility_stays_safe() -> None:
    service = BarcelloService(FakeDatabase())
    messages = []
    for i in range(80):
        author = "u1" if i % 2 == 0 else "u2"
        text = "ti passo il setup ora 😂" if i % 4 else "ok bro, provo subito lol"
        messages.append({"author_id": author, "content": text, "reply_to_author_id": "u2" if author == "u1" else "u1", "ts": "2026-04-01T10:00:00+00:00"})
    metrics = service._compute_metrics(messages, window_minutes=10)
    reasons, score = service._score_from_metrics(metrics, score_config={})
    assert metrics["direct_conflict_index"] == 0
    assert not any(r["key"] == "escalation_penalty" and r["weight"] > 10 for r in reasons)
    assert score >= 61


def test_venting_with_profanity_has_limited_impact() -> None:
    service = BarcelloService(FakeDatabase())
    messages = [{"author_id": "u1", "content": "oggi sto incazzato, che giornata di merda", "ts": "2026-04-01T10:00:00+00:00"} for _ in range(8)]
    metrics = service._compute_metrics(messages, window_minutes=20)
    reasons, score = service._score_from_metrics(metrics, score_config={})
    assert metrics["venting_index"] > 0.4
    assert metrics["direct_conflict_index"] == 0
    assert score >= 55


def test_isolated_blasphemy_without_target_maps_to_venting_not_internal_conflict() -> None:
    service = BarcelloService(FakeDatabase())
    messages = [{"author_id": "u1", "content": "porco dio che giornata", "ts": "2026-04-01T10:00:00+00:00"} for _ in range(6)]
    metrics = service._compute_metrics(messages, window_minutes=15)
    reasons, score = service._score_from_metrics(metrics, score_config={})
    assert metrics["venting_index"] > 0.4
    assert metrics["direct_conflict_index"] == 0
    assert score >= 55


def test_civil_challenge_patterns_alone_do_not_create_direct_conflict() -> None:
    service = BarcelloService(FakeDatabase())
    messages = [{"author_id": f"u{i%3}", "content": "ma che dici?? perche?? spiegami meglio", "ts": "2026-04-01T10:00:00+00:00"} for i in range(15)]
    metrics = service._compute_metrics(messages, window_minutes=20)
    reasons, score = service._score_from_metrics(metrics, score_config={})
    assert metrics["challenge_signals"] > 0
    assert metrics["direct_conflict_index"] == 0
    assert score >= 55


def test_collective_venting_on_external_topic_stays_not_directed_conflict() -> None:
    service = BarcelloService(FakeDatabase())
    messages = [
        {"author_id": f"u{i%5}", "content": "io sono incazzato col meteo di merda oggi", "ts": "2026-04-01T10:00:00+00:00"}
        for i in range(25)
    ]
    metrics = service._compute_metrics(messages, window_minutes=30)
    assert metrics["venting_index"] > metrics["direct_conflict_index"]


def test_live_reaction_with_playful_markers_triggers_mitigation() -> None:
    service = BarcelloService(FakeDatabase())
    messages = [{"author_id": f"u{i%6}", "content": "NOOOO 😂😂 ahah che meme", "ts": "2026-04-01T10:00:00+00:00"} for i in range(120)]
    metrics = service._compute_metrics(messages, window_minutes=8)
    reasons, score = service._score_from_metrics(metrics, score_config={})
    assert any(r["key"] == "playful_mitigation" for r in reasons)
    assert score >= 61


def test_playful_banter_with_light_insult_is_not_rosso() -> None:
    service = BarcelloService(FakeDatabase())
    messages = [{"author_id": f"u{i%2}", "content": "sei scemo 😂 tvb", "ts": "2026-04-01T10:00:00+00:00"} for i in range(20)]
    metrics = service._compute_metrics(messages, window_minutes=10)
    _, score = service._score_from_metrics(metrics, score_config={})
    assert score >= 41


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


def test_true_reciprocal_escalation_still_drops_to_nero_or_rosso() -> None:
    service = BarcelloService(FakeDatabase())
    messages = [
        {"author_id": "u1", "content": "sei un idiota zitto vaffanculo!!", "reply_to_author_id": "u2", "ts": "2026-04-01T10:00:00+00:00"},
        {"author_id": "u2", "content": "parli tu pagliaccio sparisci merda!!", "reply_to_author_id": "u1", "ts": "2026-04-01T10:00:05+00:00"},
    ] * 10
    metrics = service._compute_metrics(messages, window_minutes=6)
    reasons, score = service._score_from_metrics(metrics, score_config={})
    assert metrics["direct_conflict_index"] > 0.5
    assert metrics["reciprocal_conflict_pairs"] > 0
    assert any(r["key"] == "escalation_penalty" and r["weight"] > 0 for r in reasons)
    assert score <= 40


def test_calming_messages_add_recovery_bonus() -> None:
    service = BarcelloService(FakeDatabase())
    messages = [{"author_id": "u1", "content": "calma raga, non litigate, chiudiamola qui", "ts": "2026-04-01T10:00:00+00:00"} for _ in range(10)]
    metrics = service._compute_metrics(messages, window_minutes=10)
    reasons, score = service._score_from_metrics(metrics, score_config={})
    assert metrics["calming_index"] > 0.25
    assert any(r["key"] == "deescalation_bonus" for r in reasons)
    assert score >= 90
