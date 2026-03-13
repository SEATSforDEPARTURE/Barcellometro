import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from app.services.qna_sessions_repo import QnaSessionsRepo
from app.services.triggers import TriggerEngineService


def run(coro):
    return asyncio.run(coro)


class FakeCursor:
    def __init__(self, row=None) -> None:
        self._row = row

    async def fetchone(self):
        return self._row


class FakeConn:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, str | None]] = {}

    async def execute(self, query: str, params: tuple[object, ...]):
        q = " ".join(query.lower().split())
        if "delete from qna_followup_sessions" in q:
            now_iso = str(params[0])
            expired = [k for k, v in self.rows.items() if str(v["expires_at"]) <= now_iso]
            for key in expired:
                self.rows.pop(key, None)
            return FakeCursor()
        if "insert into qna_followup_sessions" in q:
            self.rows[str(params[0])] = {
                "anchor_message_id": str(params[0]),
                "guild_id": str(params[1]),
                "channel_id": str(params[2]),
                "user_id": str(params[3]) if params[3] is not None else None,
                "scope": str(params[4]),
                "history_json": str(params[5]),
                "model_name": str(params[6]) if params[6] else None,
                "created_at": str(params[7]),
                "updated_at": str(params[8]),
                "expires_at": str(params[9]),
            }
            return FakeCursor()
        if "select anchor_message_id, guild_id, channel_id" in q:
            row = self.rows.get(str(params[0]))
            if row is None or str(row["expires_at"]) <= str(params[1]):
                return FakeCursor(None)
            return FakeCursor((
                row["anchor_message_id"],
                row["guild_id"],
                row["channel_id"],
                row["user_id"],
                row["scope"],
                row["history_json"],
                row["model_name"],
                row["created_at"],
                row["updated_at"],
            ))
        raise AssertionError(f"Unsupported query: {query}")

    async def commit(self):
        return None


def test_qna_followup_repo_ttl_is_7_days_and_refreshes() -> None:
    async def _scenario() -> None:
        db = SimpleNamespace(_conn=FakeConn())
        repo = QnaSessionsRepo(db)

        await repo.save_session(
            anchor_message_id=100,
            guild_id=10,
            channel_id=20,
            user_id=30,
            scope="general_llm",
            history=[{"role": "user", "content": "ciao"}],
            model_name="gpt",
            created_at=datetime.now(timezone.utc),
        )
        row1 = db._conn.rows["100"]
        updated1 = datetime.fromisoformat(str(row1["updated_at"]))
        expires1 = datetime.fromisoformat(str(row1["expires_at"]))
        assert timedelta(days=6, hours=23) < (expires1 - updated1) <= timedelta(days=7, minutes=1)

        await repo.save_session(
            anchor_message_id=100,
            guild_id=10,
            channel_id=20,
            user_id=30,
            scope="general_llm",
            history=[{"role": "user", "content": "ciao"}, {"role": "assistant", "content": "ok"}],
            model_name="gpt",
            created_at=datetime.now(timezone.utc),
        )
        row2 = db._conn.rows["100"]
        updated2 = datetime.fromisoformat(str(row2["updated_at"]))
        expires2 = datetime.fromisoformat(str(row2["expires_at"]))
        assert updated2 >= updated1
        assert expires2 >= expires1

    run(_scenario())


def test_qna_followup_repo_ignores_expired_sessions() -> None:
    async def _scenario() -> None:
        db = SimpleNamespace(_conn=FakeConn())
        now = datetime.now(timezone.utc)
        db._conn.rows["200"] = {
            "anchor_message_id": "200",
            "guild_id": "10",
            "channel_id": "20",
            "user_id": "30",
            "scope": "general_llm",
            "history_json": '[{"role":"user","content":"x"}]',
            "model_name": "gpt",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "expires_at": (now - timedelta(minutes=1)).isoformat(),
        }
        repo = QnaSessionsRepo(db)
        assert await repo.get_session(200) is None
        assert "200" not in db._conn.rows

    run(_scenario())


def test_handle_message_qna_recovers_session_from_db() -> None:
    async def _scenario() -> None:
        db = SimpleNamespace(_conn=FakeConn(), get_trigger_enabled=AsyncMock(return_value=True), get_usage=AsyncMock(return_value=0), increment_usage=AsyncMock())
        service = TriggerEngineService(db, Mock(), Mock(), Mock(), community_insights=Mock())
        service._ask_general_answer = AsyncMock(return_value="Risposta da DB")
        await service._qna_sessions_repo.save_session(
            anchor_message_id=500,
            guild_id=10,
            channel_id=20,
            user_id=111,
            scope="general_llm",
            history=[{"role": "user", "content": "prima domanda"}],
            model_name="gpt",
            created_at=datetime.now(timezone.utc),
        )

        captured: dict[str, object] = {}

        async def _reply(*args, **kwargs):
            captured["kwargs"] = kwargs
            return SimpleNamespace(id=700)

        message = SimpleNamespace(
            guild=SimpleNamespace(id=10),
            channel=SimpleNamespace(id=20, fetch_message=AsyncMock(return_value=None)),
            author=SimpleNamespace(id=111, display_name="u", name="u"),
            content="e poi?",
            reference=SimpleNamespace(message_id=500, resolved=None),
            reply=_reply,
        )

        await service.handle_message_qna(message)

        service._ask_general_answer.assert_awaited_once()
        assert "embed" in captured.get("kwargs", {})
        assert service._qna_sessions.get((10, 20, 700)) is not None

    run(_scenario())


def test_handle_message_qna_expired_session_fallback_dm_only() -> None:
    async def _scenario() -> None:
        db = SimpleNamespace(_conn=FakeConn(), get_trigger_enabled=AsyncMock(return_value=True), get_usage=AsyncMock(return_value=0), increment_usage=AsyncMock())
        service = TriggerEngineService(db, Mock(), Mock(), Mock(), community_insights=Mock())
        service._bot = SimpleNamespace(user=SimpleNamespace(id=9999))
        service._ask_general_answer = AsyncMock()

        dm_send = AsyncMock()
        author = SimpleNamespace(id=111, send=dm_send)
        referenced = SimpleNamespace(author=SimpleNamespace(id=9999), embeds=[discord.Embed(title="❓BOTTA & RISPOSTA")])
        public_reply = AsyncMock()

        message = SimpleNamespace(
            guild=SimpleNamespace(id=10),
            channel=SimpleNamespace(id=20, fetch_message=AsyncMock(return_value=referenced)),
            author=author,
            content="vecchio followup?",
            reference=SimpleNamespace(message_id=500, resolved=referenced),
            reply=public_reply,
        )

        await service.handle_message_qna(message)

        dm_send.assert_awaited_once()
        public_reply.assert_not_called()
        service._ask_general_answer.assert_not_called()

    run(_scenario())
