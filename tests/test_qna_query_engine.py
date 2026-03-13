from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.services.qna_query_engine import NO_DATA_REPLY, QnaQueryEngine


def test_qna_query_engine_returns_no_data_fallback_when_empty_payload() -> None:
    async def _run() -> None:
        db = Mock()
        ai = Mock()
        ai.is_enabled.return_value = False
        ai.client.return_value = None
        barcello = Mock()
        engine = QnaQueryEngine(database=db, ai_service=ai, barcello=barcello)
        engine._fetch_intent_data = AsyncMock(return_value={"has_data": False})

        out = await engine.answer(guild_id="1", channel_id="2", question="di che si è parlato ieri?")
        assert out == NO_DATA_REPLY

    asyncio.run(_run())


def test_qna_query_engine_uses_barcello_data_without_ai_generation() -> None:
    async def _run() -> None:
        db = Mock()
        ai = Mock()
        ai.is_enabled.return_value = False
        ai.client.return_value = None
        barcello = Mock()
        barcello.get_current_status = AsyncMock(return_value={"score": 65, "color": "VERDE", "reason": None})
        engine = QnaQueryEngine(database=db, ai_service=ai, barcello=barcello)
        engine._parse_intent = AsyncMock(return_value=engine._heuristic_intent("com'è il barcello ora?"))

        out = await engine.answer(guild_id="1", channel_id="2", question="com'è il barcello ora?")
        assert "Barcello ora" in out
        assert "VERDE" in out

    asyncio.run(_run())


def test_parse_intent_uses_response_output_when_output_text_empty() -> None:
    async def _run() -> None:
        db = Mock()
        ai = Mock()
        ai.is_enabled.return_value = True
        client = Mock()
        ai.client.return_value = client
        ai.get_model.return_value = "gpt-4o-mini"
        payload = '{"intent":"user_activity_summary","target_user":"<@123>","time_range":"ieri","limit":7}'
        response = SimpleNamespace(output_text="", output=[SimpleNamespace(content=[SimpleNamespace(type="output_text", text=payload)])])
        client.responses.create = AsyncMock(return_value=response)
        engine = QnaQueryEngine(database=db, ai_service=ai, barcello=Mock())

        out = await engine._parse_intent("di che ha parlato <@123> ieri?")
        assert out.intent == "user_activity_summary"
        assert out.target_user == "<@123>"
        assert out.time_range == "ieri"

    asyncio.run(_run())


def test_heuristic_intent_extracts_user_topic_time_and_channel_hints() -> None:
    engine = QnaQueryEngine(database=Mock(), ai_service=Mock(), barcello=Mock())

    mention_case = engine._heuristic_intent("di che ha parlato <@123> ieri?")
    assert mention_case.intent == "user_activity_summary"
    assert mention_case.target_user == "123"
    assert mention_case.time_range == "ieri"

    topic_case = engine._heuristic_intent("cosa pensa Luca di Sanremo?")
    assert topic_case.intent == "user_opinion_on_topic"
    assert topic_case.target_user == "Luca"
    assert topic_case.topic == "Sanremo"

    voice_case = engine._heuristic_intent("quanto tempo sono stati in auditorium?")
    assert voice_case.intent == "voice_activity"
    assert voice_case.channel == "auditorium"


def test_fetch_intent_data_voice_uses_resolved_channel_id() -> None:
    async def _run() -> None:
        db = Mock()
        db.fetch_voice_sessions_in_range = AsyncMock(return_value=[])
        engine = QnaQueryEngine(database=db, ai_service=Mock(), barcello=Mock())

        await engine._fetch_intent_data(
            intent="voice_activity",
            guild_id="1",
            channel_id="text-1",
            resolved_channel_id="voice-9",
            start_ts="2026-01-01T00:00:00+00:00",
            end_ts="2026-01-01T01:00:00+00:00",
        )
        kwargs = db.fetch_voice_sessions_in_range.await_args.kwargs
        assert kwargs["voice_channel_id"] == "voice-9"

    asyncio.run(_run())


def test_compose_answer_falls_back_locally_when_ai_returns_empty_text() -> None:
    async def _run() -> None:
        ai = Mock()
        ai.is_enabled.return_value = True
        ai.get_model.return_value = "gpt-4o-mini"
        client = Mock()
        client.responses.create = AsyncMock(return_value=SimpleNamespace(output_text="", output=[]))
        ai.client.return_value = client
        engine = QnaQueryEngine(database=Mock(), ai_service=ai, barcello=Mock())

        out = await engine._compose_answer(
            question="di che ha parlato Britney ieri?",
            intent="user_activity_summary",
            target_user_name="Britney",
            range_label="ieri",
            payload={"has_data": True, "messages": [{"author_name": "Britney", "content": "Ho parlato di musica."}]},
        )
        assert out.startswith("Messaggi trovati:")

    asyncio.run(_run())
