from __future__ import annotations

import asyncio
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
