import asyncio
import sys
from types import ModuleType

import pytest

from tests._sqlite_stub import ensure_sqlite_stub

ensure_sqlite_stub()

openai_stub = ModuleType("openai")
openai_stub.AsyncOpenAI = object
sys.modules.setdefault("openai", openai_stub)

httpx_stub = ModuleType("httpx")
httpx_stub.AsyncClient = object
httpx_stub.Client = object
sys.modules.setdefault("httpx", httpx_stub)

pytest.importorskip("aiosqlite")

import sqlite3
from unittest.mock import AsyncMock, Mock

from app.services.qna_sessions_repo import QnaSessionsRepo
from app.services.triggers_service import TriggerEngineService


class RetryingDatabaseLayer:
    def __init__(self) -> None:
        self.execute = AsyncMock(return_value=None)


class AlwaysLockedDB:
    async def execute(self, query, params=()):
        raise sqlite3.OperationalError("database is locked")


async def _flush_tasks() -> None:
    await asyncio.sleep(0)
    await asyncio.sleep(0)


def test_delete_expired_sessions_uses_database_layer_and_does_not_propagate_transient_lock() -> None:
    async def _scenario() -> None:
        db = RetryingDatabaseLayer()
        repo = QnaSessionsRepo(db)

        await repo.delete_expired_sessions()

        assert db.execute.await_count == 1
        query = db.execute.await_args.args[0].lower()
        assert "delete from qna_followup_sessions" in query

    asyncio.run(_scenario())


def test_trigger_startup_cleanup_handles_locked_db_without_unhandled_task_exception(caplog) -> None:
    async def _scenario() -> None:
        db = AlwaysLockedDB()
        service = TriggerEngineService(db, Mock(), Mock(), Mock(), community_insights=Mock())
        service._insights_loop = AsyncMock(return_value=None)
        service._barcello_recovery_loop = AsyncMock(return_value=None)

        service.start(Mock())
        await _flush_tasks()

        assert "qna_followup_startup_cleanup_skipped reason=database_locked" in caplog.text

        service.stop()

    asyncio.run(_scenario())
