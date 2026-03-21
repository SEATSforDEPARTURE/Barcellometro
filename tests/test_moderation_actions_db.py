from __future__ import annotations

import sqlite3
import sys
import types
from datetime import datetime, timedelta, timezone

import asyncio


class _CursorWrapper:
    def __init__(self, cursor: sqlite3.Cursor, row_factory):
        self._cursor = cursor
        self._row_factory = row_factory

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._cursor.close()

    async def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return self._row_factory(self._cursor, row) if self._row_factory else row

    async def fetchall(self):
        rows = self._cursor.fetchall()
        if self._row_factory:
            return [self._row_factory(self._cursor, row) for row in rows]
        return rows


class _ExecuteResult:
    def __init__(self, cursor_wrapper: _CursorWrapper):
        self._cursor_wrapper = cursor_wrapper

    def __await__(self):
        async def _coro():
            return self._cursor_wrapper

        return _coro().__await__()

    async def __aenter__(self):
        return await self._cursor_wrapper.__aenter__()

    async def __aexit__(self, exc_type, exc, tb):
        return await self._cursor_wrapper.__aexit__(exc_type, exc, tb)


class _ConnectionWrapper:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path)
        self.row_factory = None

    def execute(self, query, params=()):
        return _ExecuteResult(
            _CursorWrapper(self._conn.execute(query, params), self.row_factory)
        )

    async def executescript(self, script):
        self._conn.executescript(script)

    async def commit(self):
        self._conn.commit()

    async def close(self):
        self._conn.close()


async def _connect(path: str):
    return _ConnectionWrapper(path)


if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(connect=_connect, Row=sqlite3.Row)

from app.services.database import DatabaseService


def test_inactivity_config_backward_compatibility_notify_channel_only(tmp_path) -> None:
    async def _run() -> None:
        db = DatabaseService(str(tmp_path / "test.sqlite"))
        await db.connect()
        await db.initialize_schema()
        await db.upsert_inactivity_config(
            "1", atrio_channel_id="555", atrio_template="legacy {display_name}"
        )

        cfg = await db.get_inactivity_config("1")

        assert cfg is not None
        assert cfg["notify_channel_id"] == "555"
        assert cfg["atrio_template"] == "legacy {display_name}"
        assert cfg["template_inactivity_reason"] is None

        await db.close()

    asyncio.run(_run())


def test_moderation_actions_lists_cover_tempban_grace_ban_and_kick(tmp_path) -> None:
    async def _run() -> None:
        db = DatabaseService(str(tmp_path / "test.sqlite"))
        await db.connect()
        await db.initialize_schema()

        now = datetime.now(timezone.utc)
        later = now + timedelta(days=3)
        await db.add_temp_ban("1", "10", later.isoformat(), "tempban manuale")
        await db.log_moderation_action(
            guild_id="1",
            user_id="10",
            moderator_id="99",
            action_type="tempban",
            reason="tempban manuale",
            duration_seconds=3 * 86400,
            expires_at=later.isoformat(),
            metadata={},
        )
        await db.log_moderation_action(
            guild_id="1",
            user_id="11",
            moderator_id="99",
            action_type="grace",
            reason="grace manuale",
            duration_seconds=86400,
            expires_at=(now + timedelta(days=1)).isoformat(),
            metadata={},
        )
        await db.log_moderation_action(
            guild_id="1",
            user_id="12",
            moderator_id="99",
            action_type="ban",
            reason="ban manuale",
            metadata={},
        )
        await db.log_moderation_action(
            guild_id="1",
            user_id="13",
            moderator_id="99",
            action_type="kick",
            reason="kick manuale",
            metadata={},
        )

        tempbans = await db.list_active_tempbans("1", now_iso=now.isoformat())
        grace = await db.list_active_grace_users("1", now_iso=now.isoformat())
        bans = await db.list_active_bans("1")
        kicks = await db.list_recent_kicked_users("1")

        assert [row["user_id"] for row in tempbans] == ["10"]
        assert [row["user_id"] for row in grace] == ["11"]
        assert [row["user_id"] for row in bans] == ["12"]
        assert [row["user_id"] for row in kicks] == ["13"]

        await db.close()

    asyncio.run(_run())


def test_clear_user_ban_state_removes_tempban_and_inactivity_kick_marker(
    tmp_path,
) -> None:
    async def _run() -> None:
        db = DatabaseService(str(tmp_path / "clear_ban_state.sqlite"))
        await db.connect()
        await db.initialize_schema()

        future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        await db.add_temp_ban("1", "77", future, "tempban attivo")
        await db.mark_user_kicked("1", "77", datetime.now(timezone.utc).isoformat())

        await db.clear_user_ban_state("1", "77")

        temp_bans = await db.list_active_tempbans("1")
        states = await db.list_inactivity_banned_states("1")

        assert temp_bans == []
        assert [row["user_id"] for row in states] == []

        await db.close()

    asyncio.run(_run())
