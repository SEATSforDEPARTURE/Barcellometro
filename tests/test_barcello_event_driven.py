from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.AsyncOpenAI = object
    sys.modules["openai"] = openai_stub
if "httpx" not in sys.modules:
    httpx_stub = types.ModuleType("httpx")
    httpx_stub.AsyncClient = object
    httpx_stub.Client = object
    sys.modules["httpx"] = httpx_stub

from app.services.ingest import EventEnvelope
from app.services.footer import get_footer_meta
from app.services.triggers_service import TriggerEngineService


def _make_fake_messageable() -> AsyncMock:
    channel = AsyncMock(spec=discord.abc.Messageable)
    channel.sent = []

    async def _send(*, embed=None, **_kwargs):
        channel.sent.append(embed)

    channel.send.side_effect = _send
    return channel


class _FakeBot:
    def __init__(self, channel: _FakeMessageable) -> None:
        self._channel = channel

    def get_channel(self, _channel_id: int):
        return self._channel


def _base_service(prev_state: dict, status: dict, *, cfg: dict | None = None, ai_service: Mock | None = None):
    database = Mock()
    database.get_trigger_enabled = AsyncMock(return_value=True)
    database.fetchone = AsyncMock(side_effect=[{"count": 25}, {"count": 25}])
    database.get_barcello_trigger_state = AsyncMock(return_value=prev_state)
    database.update_barcello_candidate_state = AsyncMock()
    database.update_barcello_recovery_state = AsyncMock()
    database.get_barcello_last_seen_for_color = AsyncMock(return_value=(datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat())
    database.get_barcello_last_notified = AsyncMock(return_value=None)
    database.set_barcello_last_notified = AsyncMock()
    database.upsert_barcello_trigger_state = AsyncMock()
    database.set_barcello_last_seen_for_color = AsyncMock()
    database.set_trigger_state = AsyncMock()
    database.get_trigger_state = AsyncMock(return_value={})
    database.list_barcello_recovery_armed_channels = AsyncMock(return_value=[])
    database.get_trigger_barcello_publish_anchor = AsyncMock(return_value=None)
    database.upsert_trigger_barcello_publish_anchor = AsyncMock()
    database.mark_trigger_barcello_schedule_run = AsyncMock(return_value=True)
    database.list_due_trigger_barcello_schedules = AsyncMock(return_value=[])

    barcello = Mock()
    barcello.get_current_status = AsyncMock(return_value=status)
    barcello.get_color = AsyncMock(side_effect=lambda score: "VERDE" if int(score) >= 61 else ("GIALLO" if int(score) >= 41 else "ROSSO"))

    ai = ai_service or Mock()
    if not hasattr(ai, "is_enabled"):
        ai.is_enabled = Mock(return_value=False)
    service = TriggerEngineService(database, barcello, Mock(), ai, community_insights=Mock())
    service._load_barcello_trigger_cfg_cached = Mock(return_value=cfg or {
        "window_minutes": 60,
        "min_messages": 1,
        "event_driven": {
            "minor_state_confirm_seconds": 180,
            "fresh_activity_minutes": 5,
            "min_recent_messages": 4,
            "min_recent_authors": 2,
            "max_last_message_age_seconds": 120,
        },
        "cooldown_minutes": {"minor": 20, "major": 8, "recovery": 60},
        "recovery": {"enabled": True, "poll_seconds": 300, "min_quiet_minutes": 12},
        "mod_role_id": "999",
        "templates": {"VERDE->GIALLO": "x", "GIALLO->ROSSO": "Qui si arrossisce male", "GIALLO->VERDE": "x"},
    })
    channel = _make_fake_messageable()
    service._bot = _FakeBot(channel)
    return service, database, channel, ai


def test_giallo_to_verde_not_notified_without_recovery() -> None:
    prev = {
        "last_color": "GIALLO",
        "last_score": 45,
        "recovery_armed": 0,
        "candidate_color": "VERDE",
        "candidate_since_ts": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
    }
    service, _db, channel, _ai = _base_service(prev, {"color": "VERDE", "score": 70})
    asyncio.run(service._evaluate_barcello_channel("1", "2"))
    assert channel.sent == []


def test_verde_to_giallo_blocked_without_fresh_activity() -> None:
    prev = {
        "last_color": "VERDE",
        "last_score": 70,
        "recovery_armed": 0,
        "candidate_color": "GIALLO",
        "candidate_since_ts": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
    }
    service, _db, channel, _ai = _base_service(prev, {"color": "GIALLO", "score": 60})
    service._get_recent_barcello_activity = AsyncMock(return_value={"count": 1, "authors": 1, "last_message_ts": datetime.now(timezone.utc).isoformat()})
    asyncio.run(service._evaluate_barcello_channel("1", "2"))
    assert channel.sent == []


def test_recovery_armed_on_rosso_transition() -> None:
    prev = {"last_color": "GIALLO", "last_score": 55, "recovery_armed": 0}
    service, db, _channel, _ai = _base_service(prev, {"color": "ROSSO", "score": 25})
    asyncio.run(service._evaluate_barcello_channel("1", "2"))
    assert db.update_barcello_recovery_state.await_count >= 1


def test_recovery_verde_notified_only_if_armed() -> None:
    prev = {
        "last_color": "GIALLO",
        "last_score": 45,
        "recovery_armed": 1,
        "recovery_from": "ROSSO",
        "candidate_color": "VERDE",
        "candidate_since_ts": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
    }
    service, _db, channel, _ai = _base_service(prev, {"color": "VERDE", "score": 80})
    asyncio.run(service._evaluate_barcello_channel("1", "2", allow_recovery=True, reason="recovery_loop"))
    assert len(channel.sent) == 1


def test_cooldown_blocks_notification() -> None:
    prev = {"last_color": "GIALLO", "last_score": 50, "recovery_armed": 0}
    service, db, channel, _ai = _base_service(prev, {"color": "ROSSO", "score": 20})
    db.get_barcello_last_notified = AsyncMock(return_value=datetime.now(timezone.utc).isoformat())
    asyncio.run(service._evaluate_barcello_channel("1", "2"))
    assert channel.sent == []


def test_on_event_schedules_barcello_eval() -> None:
    service, _db, _channel, _ai = _base_service({"last_color": "VERDE", "last_score": 90}, {"color": "VERDE", "score": 90})
    service._handle_phrases = AsyncMock()
    service._schedule_barcello_eval = AsyncMock()
    env = EventEnvelope(
        event_id="e1",
        event_type="message.create",
        platform="discord",
        ts=datetime.now(timezone.utc).isoformat(),
        guild_id="1",
        channel_id="2",
        thread_id=None,
        author_id="u1",
        content="ciao",
        meta={},
        raw=None,
    )
    asyncio.run(service.on_event(env))
    service._schedule_barcello_eval.assert_awaited_once_with("1", "2")


def test_run_barcello_trigger_now_uses_evaluate_flow() -> None:
    service, _db, channel, _ai = _base_service({"last_color": "VERDE", "last_score": 70}, {"color": "ROSSO", "score": 20})
    out = asyncio.run(service.run_barcello_trigger_now("1", "2", window_minutes=15))
    assert out["evaluated"] is True
    assert out["reason"] == "ok"
    service._barcello.get_current_status.assert_awaited_once_with("1", channel_id="2", window_minutes=15)
    assert len(channel.sent) == 1


def test_run_barcello_trigger_now_force_publish_sends_even_without_transition() -> None:
    service, _db, channel, _ai = _base_service({"last_color": "VERDE", "last_score": 70}, {"color": "VERDE", "score": 71})
    out = asyncio.run(service.run_barcello_trigger_now("1", "2", force_publish=True))
    assert out["evaluated"] is True
    assert out["notified"] is True
    assert len(channel.sent) == 1
    embed = channel.sent[0]
    assert str(embed.title or "") == "🫛 __**CAMBIO STATO BARCELLO**__"
    assert "L'ALLERTA BARCELLO PASSA" not in str(embed.title or "")
    assert str(embed.description or "").startswith("*") and str(embed.description or "").endswith("*")
    field_names = [str(field.name or "") for field in embed.fields]
    assert not any("AGGIORNAMENTO" in name for name in field_names)
    assert any("PUNTI SALUTE" in name for name in field_names)
    salute_field = next(field for field in embed.fields if "PUNTI SALUTE" in str(field.name or ""))
    assert "⚪" in str(salute_field.value or "")
    assert "**(" in str(salute_field.value or "") and "/100)**" in str(salute_field.value or "")


def test_run_barcello_trigger_now_rosso_has_inline_mod_mention_and_no_moderation_field() -> None:
    prev = {"last_color": "GIALLO", "last_score": 55, "recovery_armed": 0}
    service, _db, channel, _ai = _base_service(prev, {"color": "ROSSO", "score": 25})
    out = asyncio.run(service.run_barcello_trigger_now("1", "2", force_publish=True))
    assert out["notified"] is True
    embed = channel.sent[0]
    assert str(embed.description or "").endswith("Qui si arrossisce male <@&999>*")
    field_names = [str(field.name or "") for field in embed.fields]
    assert not any("MODERAZIONE" in name.upper() for name in field_names)


def test_run_barcello_trigger_now_verde_does_not_add_mod_mention() -> None:
    service, _db, channel, _ai = _base_service({"last_color": "GIALLO", "last_score": 45}, {"color": "VERDE", "score": 75})
    out = asyncio.run(service.run_barcello_trigger_now("1", "2", force_publish=True))
    assert out["notified"] is True
    embed = channel.sent[0]
    assert "<@&999>" not in str(embed.description or "")


def test_run_barcello_trigger_now_rosso_without_mod_role_does_not_add_placeholder_text() -> None:
    cfg = {
        "window_minutes": 60,
        "min_messages": 1,
        "event_driven": {"minor_state_confirm_seconds": 180},
        "cooldown_minutes": {"minor": 20, "major": 8, "recovery": 60},
        "recovery": {"enabled": True, "poll_seconds": 300, "min_quiet_minutes": 12},
        "templates": {"GIALLO->ROSSO": "Qui si arrossisce male"},
    }
    prev = {"last_color": "GIALLO", "last_score": 55, "recovery_armed": 0}
    service, _db, channel, _ai = _base_service(prev, {"color": "ROSSO", "score": 25}, cfg=cfg)
    out = asyncio.run(service.run_barcello_trigger_now("1", "2", force_publish=True))
    assert out["notified"] is True
    embed = channel.sent[0]
    assert "Qui si arrossisce male" in str(embed.description or "")
    assert "<@&" not in str(embed.description or "")


def test_run_barcello_trigger_now_trend_field_is_always_present_with_two_bullets() -> None:
    service, _db, channel, _ai = _base_service({"last_color": "VERDE", "last_score": 70}, {"color": "VERDE", "score": 71})
    out = asyncio.run(service.run_barcello_trigger_now("1", "2", force_publish=True))
    assert out["notified"] is True
    embed = channel.sent[0]
    trend_fields = [field for field in embed.fields if "TREND" in str(field.name or "")]
    assert len(trend_fields) == 1
    trend_lines = [line for line in str(trend_fields[0].value or "").splitlines() if line.strip()]
    assert len(trend_lines) == 2
    assert trend_lines[0].startswith("• L'ultima volta in questo stato è stata **")
    assert trend_lines[1].startswith("• ")


def test_run_barcello_trigger_now_trend_field_contains_last_same_state_reference() -> None:
    now = datetime.now(timezone.utc)
    prev = {"last_color": "ROSSO", "last_score": 25, "recovery_armed": 0}
    service, db, channel, _ai = _base_service(prev, {"color": "ROSSO", "score": 25})
    db.get_trigger_state = AsyncMock(
        return_value={
            "date": now.date().isoformat(),
            "counts": {"ROSSO": 1},
            "last_entered_ts": {"ROSSO": (now - timedelta(minutes=7)).isoformat()},
        }
    )
    out = asyncio.run(service.run_barcello_trigger_now("1", "2", force_publish=True))
    assert out["notified"] is True
    assert len(channel.sent) == 1
    embed = channel.sent[0]
    trend_fields = [field for field in embed.fields if "TREND" in str(field.name or "")]
    assert len(trend_fields) == 1
    trend_value = str(trend_fields[0].value or "")
    assert "• L'ultima volta in questo stato è stata **7 minuti fa**." in trend_value


def test_render_barcello_trend_comment_worsening_improving_stable() -> None:
    service, _db, _channel, _ai = _base_service({"last_color": "GIALLO", "last_score": 50}, {"color": "GIALLO", "score": 50})
    worsening = service._render_barcello_trend_comment(
        state="ROSSO",
        delta_score=-12,
        recovery_type="active",
    )
    improving = service._render_barcello_trend_comment(
        state="VERDE",
        delta_score=14,
        recovery_type="active",
    )
    passive = service._render_barcello_trend_comment(
        state="GIALLO",
        delta_score=1,
        recovery_type="passive",
    )
    assert "peggiorando" in worsening
    assert "migliorando" in improving
    assert "mancanza di interazioni" in passive


def test_render_barcello_trend_comment_driver_specific_causes() -> None:
    service, _db, _channel, _ai = _base_service({"last_color": "GIALLO", "last_score": 50}, {"color": "GIALLO", "score": 50})
    direct = service._render_barcello_trend_comment(
        state="ROSSO",
        delta_score=-8,
        recovery_type="active",
        status={"reason": "directed_conflict", "metrics": {"msg_per_min": 7.1}},
    )
    active_recovery = service._render_barcello_trend_comment(
        state="VERDE",
        delta_score=9,
        recovery_type="active",
        status={"reason": "healthy_activity_bonus", "metrics": {"msg_per_min": 6.2}},
    )
    assert "attacchi diretti" in direct
    assert "Recupero **attivo**" in active_recovery


def test_render_barcello_trend_comment_yellow_low_vs_high_severity() -> None:
    service, _db, _channel, _ai = _base_service({"last_color": "VERDE", "last_score": 70}, {"color": "GIALLO", "score": 56})
    yellow_low = service._render_barcello_trend_comment(
        state="GIALLO",
        delta_score=-2,
        recovery_type="active",
        status={"score": 56, "reason": "venting", "metrics": {}},
    )
    yellow_high = service._render_barcello_trend_comment(
        state="GIALLO",
        delta_score=-10,
        recovery_type="active",
        status={"score": 42, "reason": "venting", "metrics": {}},
    )
    assert yellow_low != yellow_high
    assert "leggero **nervosismo**" in yellow_low
    assert "vicino al **peggioramento**" in yellow_high


def test_render_barcello_trend_comment_red_low_vs_high_severity() -> None:
    service, _db, _channel, _ai = _base_service({"last_color": "GIALLO", "last_score": 50}, {"color": "ROSSO", "score": 38})
    red_low = service._render_barcello_trend_comment(
        state="ROSSO",
        delta_score=-4,
        recovery_type="active",
        status={"score": 38, "reason": "directed_conflict", "metrics": {}},
    )
    red_high = service._render_barcello_trend_comment(
        state="ROSSO",
        delta_score=-12,
        recovery_type="active",
        status={"score": 23, "reason": "directed_conflict", "metrics": {}},
    )
    assert red_low != red_high
    assert "già critica" in red_low
    assert "molto **compromesso**" in red_high


def test_render_barcello_trend_comment_green_fragile_vs_stable() -> None:
    service, _db, _channel, _ai = _base_service({"last_color": "GIALLO", "last_score": 45}, {"color": "VERDE", "score": 89})
    green_stable = service._render_barcello_trend_comment(
        state="VERDE",
        delta_score=5,
        recovery_type="active",
        status={"score": 89, "reason": "healthy_activity_bonus", "metrics": {}},
    )
    green_fragile = service._render_barcello_trend_comment(
        state="VERDE",
        delta_score=2,
        recovery_type="active",
        status={"score": 62, "reason": "healthy_activity_bonus", "metrics": {}},
    )
    assert green_stable != green_fragile
    assert "**stabile**" in green_stable
    assert "resta **delicato**" in green_fragile


def test_render_barcello_trend_comment_black_extreme_vs_initial() -> None:
    service, _db, _channel, _ai = _base_service({"last_color": "ROSSO", "last_score": 36}, {"color": "NERO", "score": 16})
    black_initial = service._render_barcello_trend_comment(
        state="NERO",
        delta_score=-8,
        recovery_type="active",
        status={"score": 16, "reason": "directed_conflict", "metrics": {}},
    )
    black_extreme = service._render_barcello_trend_comment(
        state="NERO",
        delta_score=-20,
        recovery_type="active",
        status={"score": 5, "reason": "directed_conflict", "metrics": {}},
    )
    assert black_initial != black_extreme
    assert "molto **critico**" in black_initial
    assert "Situazione **estrema**" in black_extreme


def test_compute_barcello_severity_thresholds() -> None:
    assert TriggerEngineService._compute_barcello_severity(score=85, color="VERDE") == "low"
    assert TriggerEngineService._compute_barcello_severity(score=62, color="VERDE") == "high"
    assert TriggerEngineService._compute_barcello_severity(score=56, color="GIALLO") == "low"
    assert TriggerEngineService._compute_barcello_severity(score=42, color="GIALLO") == "high"
    assert TriggerEngineService._compute_barcello_severity(score=36, color="ROSSO") == "low"
    assert TriggerEngineService._compute_barcello_severity(score=22, color="ROSSO") == "high"
    assert TriggerEngineService._compute_barcello_severity(score=16, color="NERO") == "low"
    assert TriggerEngineService._compute_barcello_severity(score=3, color="NERO") == "high"


def test_recovery_type_active_trend_contains_migliorando_and_no_passive_phrase() -> None:
    service, db, channel, _ai = _base_service({"last_color": "GIALLO", "last_score": 45}, {"color": "VERDE", "score": 75})
    db.fetchone = AsyncMock(side_effect=[{"count": 18}, {"count": 20}])
    out = asyncio.run(service.run_barcello_trigger_now("1", "2", force_publish=True))
    assert out["notified"] is True
    trend_field = next(field for field in channel.sent[0].fields if "TREND" in str(field.name or ""))
    value = str(trend_field.value or "")
    assert "migliorando" in value
    assert "assenza di attività" not in value


def test_recovery_type_passive_trend_mentions_low_activity() -> None:
    service, db, channel, _ai = _base_service({"last_color": "GIALLO", "last_score": 45}, {"color": "VERDE", "score": 75})
    db.fetchone = AsyncMock(side_effect=[{"count": 1}, {"count": 30}])
    out = asyncio.run(service.run_barcello_trigger_now("1", "2", force_publish=True))
    assert out["notified"] is True
    trend_field = next(field for field in channel.sent[0].fields if "TREND" in str(field.name or ""))
    value = str(trend_field.value or "")
    assert "Recupero **passivo**" in value


def test_recovery_description_is_bold_and_contextual() -> None:
    service, db, channel, _ai = _base_service({"last_color": "GIALLO", "last_score": 45}, {"color": "VERDE", "score": 75})
    db.fetchone = AsyncMock(side_effect=[{"count": 2}, {"count": 25}])
    out = asyncio.run(service.run_barcello_trigger_now("1", "2", force_publish=True))
    assert out["notified"] is True
    description = str(channel.sent[0].description or "")
    assert "Rientro nel verde: **VERDE**. 🌿" in description
    assert "**stabilizzato**" in description


def test_run_barcello_trigger_now_pair_mode_uses_compute_pair() -> None:
    service, _db, _channel, _ai = _base_service({"last_color": "VERDE", "last_score": 70}, {"color": "VERDE", "score": 70})
    service._barcello.compute_pair = AsyncMock(return_value=SimpleNamespace(score=24, color="rosso"))
    service._barcello.get_current_status = AsyncMock(return_value={"color": "VERDE", "score": 80})
    asyncio.run(service.run_barcello_trigger_now("1", "2", force_publish=True, user1_id="11", user2_id="22"))
    service._barcello.compute_pair.assert_awaited_once_with("1", "2", "11", "22", 60)
    service._barcello.get_current_status.assert_not_awaited()


def test_run_barcello_trigger_now_returns_disabled_when_trigger_off() -> None:
    service, db, _channel, _ai = _base_service({"last_color": "VERDE", "last_score": 70}, {"color": "ROSSO", "score": 20})
    db.get_trigger_enabled = AsyncMock(return_value=False)
    service._evaluate_barcello_channel = AsyncMock()
    out = asyncio.run(service.run_barcello_trigger_now("1", "2"))
    assert out == {"evaluated": False, "notified": False, "reason": "disabled"}
    service._evaluate_barcello_channel.assert_not_awaited()


def test_insights_loop_kept_in_polling_mode() -> None:
    service, _db, _channel, _ai = _base_service({"last_color": "VERDE", "last_score": 90}, {"color": "VERDE", "score": 90})
    called = {"count": 0}

    async def _once():
        called["count"] += 1
        raise asyncio.CancelledError

    service._poll_insights = _once
    try:
        asyncio.run(service._insights_loop())
    except asyncio.CancelledError:
        pass
    assert called["count"] == 1


def test_barcello_climate_ai_uses_dedicated_task_and_sets_footer_contributors() -> None:
    ai = Mock()
    ai.is_enabled = Mock(return_value=True)
    ai.ask_for_task = AsyncMock(return_value='{"label":"directed_conflict","toxicity":0.7,"aggression":0.8,"directedness":0.9,"profanity":0.5,"venting":0.1,"calming":0.0,"conflict":0.88,"target_type":"user","confidence":0.92,"reason_code":"attack_with_target"}')
    ai.get_runtime_model_contributors = Mock(return_value=["llama3.2", "gpt-4o-mini"])
    cfg = {
        "window_minutes": 60,
        "min_messages": 1,
        "analysis": {"ai_fallback_enabled": True, "ai_ambiguity_min": 0.2, "ai_ambiguity_max": 0.6, "max_messages_per_window": 10},
        "event_driven": {"minor_state_confirm_seconds": 180},
        "cooldown_minutes": {"minor": 20, "major": 8, "recovery": 60},
        "recovery": {"enabled": True, "poll_seconds": 300, "min_quiet_minutes": 12},
        "templates": {"VERDE->GIALLO": "x"},
    }
    status = {"color": "GIALLO", "score": 58, "metrics": {"hostility_index": 0.4, "direct_conflict_index": 0.2, "venting_index": 0.3}}
    service, db, channel, _ai = _base_service({"last_color": "VERDE", "last_score": 70}, status, cfg=cfg, ai_service=ai)
    db.fetch_messages_in_range = AsyncMock(return_value=[{"author_id": "u1", "content": "msg1"}, {"author_id": "u2", "content": "msg2"}, {"author_id": "u3", "content": "msg3"}])
    service._get_recent_barcello_activity = AsyncMock(return_value={"count": 8, "authors": 4, "last_message_ts": datetime.now(timezone.utc).isoformat()})

    out = asyncio.run(service.run_barcello_trigger_now("1", "2", force_publish=True))

    assert out["notified"] is True
    ai.ask_for_task.assert_awaited()
    assert ai.ask_for_task.await_args.args[0] == "climate_analysis"
    meta = get_footer_meta(channel.sent[0])
    assert meta is not None
    assert meta.contributors == ["llama3.2", "gpt-4o-mini"]


def test_barcello_climate_ai_not_used_keeps_footer_without_contributors() -> None:
    ai = Mock()
    ai.is_enabled = Mock(return_value=True)
    ai.ask_for_task = AsyncMock(return_value='{"label":"neutral","toxicity":0.0,"aggression":0.0,"directedness":0.0,"profanity":0.0,"venting":0.0,"calming":0.0,"conflict":0.0,"target_type":"none","confidence":0.9,"reason_code":"neutral_no_target"}')
    ai.get_runtime_model_contributors = Mock(return_value=["llama3.2"])
    cfg = {
        "window_minutes": 60,
        "min_messages": 1,
        "analysis": {"ai_fallback_enabled": True, "ai_ambiguity_min": 0.7, "ai_ambiguity_max": 0.8, "max_messages_per_window": 10},
        "event_driven": {"minor_state_confirm_seconds": 180},
        "cooldown_minutes": {"minor": 20, "major": 8, "recovery": 60},
        "recovery": {"enabled": True, "poll_seconds": 300, "min_quiet_minutes": 12},
        "templates": {"VERDE->GIALLO": "x"},
    }
    status = {"color": "GIALLO", "score": 58, "metrics": {"hostility_index": 0.4}}
    service, _db, channel, _ai = _base_service({"last_color": "VERDE", "last_score": 70}, status, cfg=cfg, ai_service=ai)

    out = asyncio.run(service.run_barcello_trigger_now("1", "2", force_publish=True))

    assert out["notified"] is True
    ai.ask_for_task.assert_not_awaited()
    meta = get_footer_meta(channel.sent[0])
    assert meta is not None
    assert meta.contributors == []


def test_scheduled_publish_uses_fallback_title_and_updates_anchor() -> None:
    service, db, channel, _ai = _base_service({"last_color": "VERDE", "last_score": 70}, {"color": "VERDE", "score": 72})
    db.get_trigger_barcello_publish_anchor = AsyncMock(return_value=None)
    schedule = {"id": 1, "guild_id": "1", "channel_id": "2", "every_minutes": 30, "embed_title": None}

    sent = asyncio.run(service._publish_barcello_scheduled_update(schedule))

    assert sent is True
    embed = channel.sent[-1]
    assert str(embed.title or "") == "🫛 __**AGGIORNAMENTO ORARIO BARCELLO**__"
    db.upsert_trigger_barcello_publish_anchor.assert_awaited_once()


def test_scheduled_publish_uses_title_override() -> None:
    service, db, channel, _ai = _base_service({"last_color": "VERDE", "last_score": 70}, {"color": "GIALLO", "score": 52})
    db.get_trigger_barcello_publish_anchor = AsyncMock(return_value=None)
    schedule = {"id": 1, "guild_id": "1", "channel_id": "2", "every_minutes": 30, "embed_title": "Titolo custom"}

    sent = asyncio.run(service._publish_barcello_scheduled_update(schedule))

    assert sent is True
    embed = channel.sent[-1]
    assert str(embed.title or "") == "Titolo custom"


def test_scheduled_trend_uses_anchor_most_recent() -> None:
    service, db, channel, _ai = _base_service({"last_color": "VERDE", "last_score": 70}, {"color": "VERDE", "score": 80})
    db.get_trigger_barcello_publish_anchor = AsyncMock(
        return_value={"last_color": "GIALLO", "last_score": 50, "last_ts": "2026-04-02T10:00:00+00:00", "last_kind": "scheduled"}
    )
    schedule = {"id": 1, "guild_id": "1", "channel_id": "2", "every_minutes": 30}

    sent = asyncio.run(service._publish_barcello_scheduled_update(schedule))

    assert sent is True
    trend_field = next(field for field in channel.sent[-1].fields if "TREND" in str(field.name or ""))
    assert "ultimo publish (scheduled)" in str(trend_field.value or "")


def test_scheduled_after_state_change_uses_state_change_anchor() -> None:
    service, db, channel, _ai = _base_service({"last_color": "VERDE", "last_score": 70}, {"color": "ROSSO", "score": 25})
    db.get_trigger_barcello_publish_anchor = AsyncMock(return_value=None)

    out = asyncio.run(service.run_barcello_trigger_now("1", "2", force_publish=True))
    assert out["notified"] is True
    first_anchor_call = db.upsert_trigger_barcello_publish_anchor.await_args_list[0]
    assert first_anchor_call.kwargs["last_kind"] == "state_change"

    db.get_trigger_barcello_publish_anchor = AsyncMock(
        return_value={"last_color": "ROSSO", "last_score": 25, "last_ts": datetime.now(timezone.utc).isoformat(), "last_kind": "state_change"}
    )
    service._barcello.get_current_status = AsyncMock(return_value={"color": "GIALLO", "score": 40})
    schedule = {"id": 2, "guild_id": "1", "channel_id": "2", "every_minutes": 30}
    sent = asyncio.run(service._publish_barcello_scheduled_update(schedule))
    assert sent is True
    trend_field = next(field for field in channel.sent[-1].fields if "TREND" in str(field.name or ""))
    assert "ultimo publish (state_change)" in str(trend_field.value or "")


def test_trend_mode_state_change_vs_scheduled_are_kept_distinct() -> None:
    now = datetime.now(timezone.utc)
    service, db, channel, _ai = _base_service({"last_color": "ROSSO", "last_score": 22}, {"color": "ROSSO", "score": 25})
    db.get_trigger_state = AsyncMock(
        return_value={
            "date": now.date().isoformat(),
            "counts": {"ROSSO": 2},
            "last_entered_ts": {"ROSSO": (now - timedelta(minutes=9)).isoformat()},
        }
    )
    db.get_trigger_barcello_publish_anchor = AsyncMock(return_value=None)

    out = asyncio.run(service.run_barcello_trigger_now("1", "2", force_publish=True))
    assert out["notified"] is True
    state_change_trend = next(field for field in channel.sent[-1].fields if "TREND" in str(field.name or ""))
    assert "L'ultima volta in questo stato è stata **9 minuti fa**." in str(state_change_trend.value or "")

    db.get_trigger_barcello_publish_anchor = AsyncMock(return_value=None)
    service._barcello.get_current_status = AsyncMock(return_value={"color": "ROSSO", "score": 25})
    schedule = {"id": 77, "guild_id": "1", "channel_id": "2", "every_minutes": 30}
    sent = asyncio.run(service._publish_barcello_scheduled_update(schedule))
    assert sent is True
    scheduled_trend = next(field for field in channel.sent[-1].fields if "TREND" in str(field.name or ""))
    assert "Primo riferimento disponibile per il trend." in str(scheduled_trend.value or "")
