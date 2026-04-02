import asyncio

from app.services.barcello_service import BarcelloService


class FakeDatabase:
    def __init__(self, settings: dict[str, str] | None = None) -> None:
        self._settings = settings or {}
        self._messages: list[dict[str, object]] = []
        self._snapshot = None
        self._remote_author_by_message_id: dict[str, str] = {}

    async def get_setting(self, key: str) -> str | None:
        return self._settings.get(key)

    async def get_barcello_snapshot_before(self, *args, **kwargs):
        return self._snapshot

    async def put_barcello_window_analysis(self, *args, **kwargs):
        return None

    async def put_barcello_message_classifications(self, *args, **kwargs):
        return None

    async def get_barcello_snapshot(self, *args, **kwargs):
        return None

    async def fetch_messages_in_range(self, *args, **kwargs):
        return self._messages

    async def put_barcello_snapshot(self, *args, **kwargs):
        self._snapshot = {
            "guild_id": kwargs.get("guild_id", "g1"),
            "channel_id": kwargs.get("channel_id", "c1"),
            "window_minutes": kwargs.get("window_minutes", 10),
            "window_end_ts": kwargs.get("window_end_ts", ""),
            "score": kwargs.get("score", 100),
            "reasons_json": kwargs.get("reasons_json", "[]"),
            "metrics_json": kwargs.get("metrics_json", "{}"),
        }
        return None

    async def fetch_message_authors_by_ids(self, message_ids: list[str]) -> dict[str, str]:
        return {message_id: self._remote_author_by_message_id[message_id] for message_id in message_ids if message_id in self._remote_author_by_message_id}


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


def test_reciprocal_reply_conflict_with_real_reply_to_message_id_is_detected() -> None:
    db = FakeDatabase()
    db._messages = [
        {"message_id": "m1", "author_id": "u1", "content": "sei ridicolo", "ts": "2026-04-01T10:00:00+00:00"},
        {"message_id": "m2", "author_id": "u2", "content": "tu sei un pezzo di merda", "reply_to_message_id": "m1", "ts": "2026-04-01T10:00:08+00:00"},
        {"message_id": "m3", "author_id": "u1", "content": "tu sei una brutta puttana", "reply_to_message_id": "m2", "ts": "2026-04-01T10:00:15+00:00"},
        {"message_id": "m4", "author_id": "u2", "content": "non osare bastarda, stai zitta", "reply_to_message_id": "m3", "ts": "2026-04-01T10:00:22+00:00"},
    ] * 3
    service = BarcelloService(db)
    result = run(service.compute_channel("g1", "c1", window_minutes=10, now_ts="2026-04-01T10:10:00+00:00"))
    assert result.metrics["reciprocal_conflict_pairs"] >= 1
    assert result.metrics["aggressive_directed_count"] >= 2
    assert result.score < 70


def test_reply_target_resolution_uses_batch_lookup_when_referenced_message_is_outside_window() -> None:
    db = FakeDatabase()
    db._remote_author_by_message_id = {"old-1": "u2", "old-2": "u1"}
    db._messages = [
        {"message_id": "m1", "author_id": "u1", "content": "sei ridicolo", "reply_to_message_id": "old-1", "ts": "2026-04-01T10:00:00+00:00"},
        {"message_id": "m2", "author_id": "u2", "content": "parla piano bastardo", "reply_to_message_id": "old-2", "ts": "2026-04-01T10:00:08+00:00"},
    ] * 4
    service = BarcelloService(db)
    result = run(service.compute_channel("g1", "c1", window_minutes=10, now_ts="2026-04-01T10:10:00+00:00"))
    assert result.metrics["direct_conflict_index"] > 0.3
    assert result.metrics["reply_density"] > 0
    assert result.score < 75


def test_short_intense_burst_penalizes_even_if_rest_of_window_is_quiet() -> None:
    service = BarcelloService(FakeDatabase())
    quiet = [
        {"author_id": f"u{i%4}", "content": "ok ricevuto", "ts": f"2026-04-01T10:{i:02d}:00+00:00"}
        for i in range(15)
    ]
    burst = [
        {"author_id": "u1", "content": "sei ridicolo", "reply_to_author_id": "u2", "ts": "2026-04-01T10:20:00+00:00"},
        {"author_id": "u2", "content": "tu sei un pezzo di merda", "reply_to_author_id": "u1", "ts": "2026-04-01T10:20:10+00:00"},
        {"author_id": "u1", "content": "tu sei una brutta puttana", "reply_to_author_id": "u2", "ts": "2026-04-01T10:21:00+00:00"},
        {"author_id": "u2", "content": "non osare bastarda, stai zitta", "reply_to_author_id": "u1", "ts": "2026-04-01T10:21:10+00:00"},
    ]
    metrics = service._compute_metrics(quiet + burst, window_minutes=30)
    service._apply_temporal_context(metrics, previous_metrics={}, previous_score=None)
    reasons, score = service._score_from_metrics(metrics, score_config={})
    assert metrics["direct_conflict_burst_peak"] >= 3
    assert metrics["local_worst_segment_score"] > 0.55
    assert any(r["key"] in {"local_burst_penalty", "mutual_direct_conflict_burst_penalty"} for r in reasons)
    assert score < 55


def test_calming_messages_add_recovery_bonus() -> None:
    service = BarcelloService(FakeDatabase())
    messages = [{"author_id": "u1", "content": "calma raga, non litigate, chiudiamola qui", "ts": "2026-04-01T10:00:00+00:00"} for _ in range(10)]
    metrics = service._compute_metrics(messages, window_minutes=10)
    service._apply_temporal_context(metrics, previous_metrics={}, previous_score=None)
    reasons, score = service._score_from_metrics(metrics, score_config={})
    assert metrics["calming_index"] > 0.25
    assert any(r["key"] == "recovery_adjustment" for r in reasons)
    assert score >= 90


def test_burst_followed_by_short_silence_keeps_latch_and_blocks_instant_green_rebound() -> None:
    db = FakeDatabase()
    db._messages = [
        {"author_id": "u1", "content": "sei un idiota", "reply_to_author_id": "u2", "ts": "2026-04-01T10:10:00+00:00"},
        {"author_id": "u2", "content": "taci pagliaccio", "reply_to_author_id": "u1", "ts": "2026-04-01T10:10:08+00:00"},
        {"author_id": "u1", "content": "vaffanculo", "reply_to_author_id": "u2", "ts": "2026-04-01T10:10:16+00:00"},
        {"author_id": "u2", "content": "sei ridicolo", "reply_to_author_id": "u1", "ts": "2026-04-01T10:10:24+00:00"},
    ]
    service = BarcelloService(db)
    first = run(service.compute_channel("g1", "c1", window_minutes=15, now_ts="2026-04-01T10:11:00+00:00"))
    assert first.metrics["conflict_latch_level"] >= 0.4
    assert first.score <= 55
    db._messages = []
    second = run(service.compute_channel("g1", "c1", window_minutes=15, now_ts="2026-04-01T10:12:00+00:00"))
    assert second.metrics["conflict_latch_level"] >= 0.28
    assert second.score < 90


def test_hysteresis_penalty_applies_when_previous_window_was_unhealthy() -> None:
    service = BarcelloService(FakeDatabase())
    quiet_metrics = service._compute_metrics([], window_minutes=10)
    service._apply_temporal_context(
        quiet_metrics,
        previous_metrics={"conflict_latch_level": 0.8, "direct_conflict_index": 0.4},
        previous_score=45,
    )
    reasons, score = service._score_from_metrics(quiet_metrics, score_config={})
    assert any(item["key"] == "hysteresis_penalty" for item in reasons)
    assert score < 98


def test_non_hostile_chaos_does_not_trigger_conflict_burst() -> None:
    service = BarcelloService(FakeDatabase())
    messages = [
        {"author_id": f"u{i%6}", "content": "HAHAH che caos lol 😂", "ts": f"2026-04-01T10:{(i%50):02d}:00+00:00"}
        for i in range(40)
    ]
    metrics = service._compute_metrics(messages, window_minutes=12)
    assert metrics["conflict_burst_count"] == 0
    assert metrics["local_worst_segment_score"] < 0.35
