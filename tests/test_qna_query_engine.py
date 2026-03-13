from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.services.qna_query_engine import NO_DATA_REPLY, QnaAnswerResult, QnaQueryEngine


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
        assert isinstance(out, QnaAnswerResult)
        assert out.answer_text == NO_DATA_REPLY
        assert out.proofs == []

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
        assert isinstance(out, QnaAnswerResult)
        assert "Barcello ora" in out.answer_text
        assert "VERDE" in out.answer_text
        assert out.proofs == []

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


def test_parse_intent_accepts_fenced_json() -> None:
    async def _run() -> None:
        db = Mock()
        ai = Mock()
        ai.is_enabled.return_value = True
        client = Mock()
        ai.client.return_value = client
        ai.get_model.return_value = "gpt-4o-mini"
        payload = """```json
{"intent":"user_activity_summary","target_user":"Lela","topic":null,"time_range":"ieri","channel":null,"metric":null,"limit":8}
```"""
        response = SimpleNamespace(output_text=payload, output=[])
        client.responses.create = AsyncMock(return_value=response)
        engine = QnaQueryEngine(database=db, ai_service=ai, barcello=Mock())

        out = await engine._parse_intent("di che ha parlato lela ieri?")
        assert out.intent == "user_activity_summary"
        assert out.target_user == "Lela"
        assert out.time_range == "ieri"

    asyncio.run(_run())


def test_answer_requires_user_tag_when_target_not_resolved() -> None:
    async def _run() -> None:
        engine = QnaQueryEngine(database=Mock(), ai_service=Mock(), barcello=Mock())
        engine._parse_intent = AsyncMock(
            return_value=SimpleNamespace(
                intent="user_activity_summary",
                target_user="lela",
                topic=None,
                time_range="ieri",
                channel=None,
                metric=None,
                limit=8,
            )
        )
        engine._resolve_target_user = AsyncMock(return_value=(None, "lela"))

        out = await engine.answer(guild_id="1", channel_id="2", question="di che ha parlato lela ieri?")
        assert isinstance(out, QnaAnswerResult)
        assert "taggala direttamente" in out.answer_text.lower()
        assert out.answer_text != NO_DATA_REPLY

    asyncio.run(_run())


def test_extract_topic_hint_ignores_mentions_and_numeric_ids() -> None:
    engine = QnaQueryEngine(database=Mock(), ai_service=Mock(), barcello=Mock())
    assert engine._extract_topic_hint("cosa ha detto lela su <@123456789012345678> ieri?") is None
    assert engine._extract_topic_hint("cosa pensa lela di 1408152223665360977?") is None


def test_resolve_target_user_prefers_exact_match_over_substring() -> None:
    async def _run() -> None:
        member_exact = SimpleNamespace(id=42, display_name="Lela", name="lela", global_name=None, nick=None)
        member_sub = SimpleNamespace(id=77, display_name="lelandro", name="lelandro", global_name=None, nick=None)
        guild = SimpleNamespace(members=[member_sub, member_exact], get_member=lambda _: None)
        source = SimpleNamespace(guild=guild)
        db = Mock()
        db.fetchall = AsyncMock(return_value=[])
        engine = QnaQueryEngine(database=db, ai_service=Mock(), barcello=Mock())

        user_id, user_name = await engine._resolve_target_user("lela", "di che ha parlato lela ieri?", "1", source)
        assert user_id == "42"
        assert user_name == "Lela"

    asyncio.run(_run())


def test_fetch_intent_data_user_activity_uses_larger_candidate_pool() -> None:
    async def _run() -> None:
        db = Mock()
        db.fetch_qna_messages = AsyncMock(return_value=[])
        engine = QnaQueryEngine(database=db, ai_service=Mock(), barcello=Mock())

        await engine._fetch_intent_data(
            intent="user_activity_summary",
            guild_id="1",
            channel_id="2",
            target_user_id="10",
            topic=None,
            limit=8,
            start_ts="2026-01-01T00:00:00+00:00",
            end_ts="2026-01-01T23:59:59+00:00",
            question="di che ha parlato lela ieri?",
        )
        kwargs = db.fetch_qna_messages.await_args.kwargs
        assert kwargs["candidate_pool_limit"] >= 50

    asyncio.run(_run())


def test_extract_proofs_deduplicates_and_limits_message_links() -> None:
    engine = QnaQueryEngine(database=Mock(), ai_service=Mock(), barcello=Mock())
    payload = {
        "messages": [
            {
                "jump_url": "https://discord.com/channels/1/2/10",
                "ts": "2026-03-13T14:38:12+00:00",
                "author_name": "Meg",
                "content": "Pollock e altri dettagli" * 20,
            },
            {
                "jump_url": "https://discord.com/channels/1/2/9",
                "ts": "2026-03-13T14:31:00+00:00",
                "author_name": "Luca",
                "content": "Secondo messaggio",
            },
            {
                "jump_url": "https://discord.com/channels/1/2/10",
                "ts": "2026-03-13T14:38:12+00:00",
                "author_name": "Meg",
                "content": "Duplicato",
            },
        ]
    }

    proofs = engine._extract_proofs(intent="user_activity_summary", payload=payload, limit=2)
    assert len(proofs) == 2
    assert proofs[0]["jump_url"] == "https://discord.com/channels/1/2/10"
    assert proofs[0]["created_at_iso"] == "2026-03-13T14:38:12+00:00"
    assert len(proofs[0]["snippet"]) <= 220


def test_answer_returns_structured_result_with_proofs_for_message_intent() -> None:
    async def _run() -> None:
        engine = QnaQueryEngine(database=Mock(), ai_service=Mock(), barcello=Mock())
        engine._parse_intent = AsyncMock(
            return_value=SimpleNamespace(
                intent="user_activity_summary",
                target_user=None,
                topic=None,
                time_range="ieri",
                channel=None,
                metric=None,
                limit=8,
            )
        )
        engine._resolve_target_user = AsyncMock(return_value=(None, None))
        engine._fetch_intent_data = AsyncMock(
            return_value={
                "has_data": True,
                "messages": [
                    {
                        "jump_url": "https://discord.com/channels/1/2/3",
                        "ts": "2026-03-13T14:38:12+00:00",
                        "author_name": "Meg",
                        "content": "Test",
                    }
                ],
            }
        )
        engine._compose_answer = AsyncMock(return_value="Risposta semantica")

        out = await engine.answer(guild_id="1", channel_id="2", question="di che ha parlato ieri?")
        assert isinstance(out, QnaAnswerResult)
        assert out.answer_text == "Risposta semantica"
        assert len(out.proofs) == 1
        assert out.proofs[0]["jump_url"] == "https://discord.com/channels/1/2/3"

    asyncio.run(_run())
