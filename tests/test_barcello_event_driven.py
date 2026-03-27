from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime, timedelta, timezone
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


def _base_service(prev_state: dict, status: dict, *, cfg: dict | None = None):
    database = Mock()
    database.get_trigger_enabled = AsyncMock(return_value=True)
    database.fetchone = AsyncMock(return_value={"count": 25})
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

    barcello = Mock()
    barcello.get_current_status = AsyncMock(return_value=status)

    service = TriggerEngineService(database, barcello, Mock(), Mock(), community_insights=Mock())
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
        "templates": {"VERDE->GIALLO": "x", "GIALLO->ROSSO": "x", "GIALLO->VERDE": "x"},
    })
    channel = _make_fake_messageable()
    service._bot = _FakeBot(channel)
    return service, database, channel


def test_giallo_to_verde_not_notified_without_recovery() -> None:
    prev = {
        "last_color": "GIALLO",
        "last_score": 45,
        "recovery_armed": 0,
        "candidate_color": "VERDE",
        "candidate_since_ts": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
    }
    service, _db, channel = _base_service(prev, {"color": "VERDE", "score": 70})
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
    service, _db, channel = _base_service(prev, {"color": "GIALLO", "score": 60})
    service._get_recent_barcello_activity = AsyncMock(return_value={"count": 1, "authors": 1, "last_message_ts": datetime.now(timezone.utc).isoformat()})
    asyncio.run(service._evaluate_barcello_channel("1", "2"))
    assert channel.sent == []


def test_recovery_armed_on_rosso_transition() -> None:
    prev = {"last_color": "GIALLO", "last_score": 55, "recovery_armed": 0}
    service, db, _channel = _base_service(prev, {"color": "ROSSO", "score": 25})
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
    service, _db, channel = _base_service(prev, {"color": "VERDE", "score": 80})
    asyncio.run(service._evaluate_barcello_channel("1", "2", allow_recovery=True, reason="recovery_loop"))
    assert len(channel.sent) == 1


def test_cooldown_blocks_notification() -> None:
    prev = {"last_color": "GIALLO", "last_score": 50, "recovery_armed": 0}
    service, db, channel = _base_service(prev, {"color": "ROSSO", "score": 20})
    db.get_barcello_last_notified = AsyncMock(return_value=datetime.now(timezone.utc).isoformat())
    asyncio.run(service._evaluate_barcello_channel("1", "2"))
    assert channel.sent == []


def test_on_event_schedules_barcello_eval() -> None:
    service, _db, _channel = _base_service({"last_color": "VERDE", "last_score": 90}, {"color": "VERDE", "score": 90})
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
    service, _db, channel = _base_service({"last_color": "VERDE", "last_score": 70}, {"color": "ROSSO", "score": 20})
    out = asyncio.run(service.run_barcello_trigger_now("1", "2", window_minutes=15))
    assert out["evaluated"] is True
    assert out["reason"] == "ok"
    service._barcello.get_current_status.assert_awaited_once_with("1", channel_id="2", window_minutes=15)
    assert len(channel.sent) == 1


def test_run_barcello_trigger_now_returns_disabled_when_trigger_off() -> None:
    service, db, _channel = _base_service({"last_color": "VERDE", "last_score": 70}, {"color": "ROSSO", "score": 20})
    db.get_trigger_enabled = AsyncMock(return_value=False)
    service._evaluate_barcello_channel = AsyncMock()
    out = asyncio.run(service.run_barcello_trigger_now("1", "2"))
    assert out == {"evaluated": False, "notified": False, "reason": "disabled"}
    service._evaluate_barcello_channel.assert_not_awaited()


def test_insights_loop_kept_in_polling_mode() -> None:
    service, _db, _channel = _base_service({"last_color": "VERDE", "last_score": 90}, {"color": "VERDE", "score": 90})
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
