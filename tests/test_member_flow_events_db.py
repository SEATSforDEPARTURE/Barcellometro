from __future__ import annotations

import asyncio
import sqlite3
import sys
import types


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
        return _ExecuteResult(_CursorWrapper(self._conn.execute(query, params), self.row_factory))

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


def test_member_flow_events_schema_is_created(tmp_path) -> None:
    async def _run() -> None:
        db = DatabaseService(str(tmp_path / "test.sqlite"))
        await db.connect()
        await db.initialize_schema()

        columns = await db.fetchall("PRAGMA table_info(member_flow_events)")
        column_names = [row["name"] for row in columns]
        indexes = await db.fetchall("PRAGMA index_list(member_flow_events)")
        index_names = {row["name"] for row in indexes}

        assert column_names == [
            "id",
            "guild_id",
            "user_id",
            "event_type_key",
            "occurred_at",
            "moderator_id",
            "reason",
            "duration_seconds",
            "expires_at",
            "source",
            "source_ref",
            "operation_id",
            "visible_in_greetings",
            "metadata_json",
        ]
        assert "uniq_member_flow_events_source_ref" in index_names
        assert "idx_member_flow_events_guild_user_type_occurred" in index_names
        assert "idx_member_flow_events_visible_departures" in index_names
        assert "idx_member_flow_events_operation" in index_names

        await db.close()

    asyncio.run(_run())


def test_member_flow_events_insert_count_visibility_and_idempotency(tmp_path) -> None:
    async def _run() -> None:
        db = DatabaseService(str(tmp_path / "test.sqlite"))
        await db.connect()
        await db.initialize_schema()

        first = await db.insert_member_flow_event(
            guild_id="1",
            user_id="42",
            event_type_key="kick",
            occurred_at="2026-03-20T10:00:00+00:00",
            moderator_id="99",
            reason="Kick test",
            source="moderation",
            source_ref="moderation_actions:abc",
            visible_in_greetings=True,
            metadata={"raw_action_id": "abc"},
        )
        duplicate = await db.insert_member_flow_event(
            guild_id="1",
            user_id="42",
            event_type_key="kick",
            occurred_at="2026-03-20T11:00:00+00:00",
            moderator_id="77",
            reason="Duplicate should not win",
            source="moderation",
            source_ref="moderation_actions:abc",
            visible_in_greetings=False,
            metadata={"raw_action_id": "abc", "duplicate": True},
        )
        hidden = await db.insert_member_flow_event(
            guild_id="1",
            user_id="42",
            event_type_key="kick",
            occurred_at="2026-03-20T12:00:00+00:00",
            source="backfill",
            source_ref="backfill:001",
            visible_in_greetings=False,
            metadata={"batch": 1},
        )

        stored = await db.find_member_flow_event_by_source_ref(source="moderation", source_ref="moderation_actions:abc")
        visible_count = await db.count_member_flow_events_for_user("1", "42", "kick")
        all_count = await db.count_member_flow_events_for_user("1", "42", "kick", visible_only=False)
        rows = await db.fetchall("SELECT COUNT(*) AS total FROM member_flow_events")

        assert first["id"] == duplicate["id"]
        assert stored is not None
        assert stored["reason"] == "Kick test"
        assert stored["visible_in_greetings"] is True
        assert stored["metadata"] == {"raw_action_id": "abc"}
        assert hidden["visible_in_greetings"] is False
        assert visible_count == 1
        assert all_count == 2
        assert rows[0]["total"] == 2

        await db.close()

    asyncio.run(_run())


def test_member_flow_events_recent_visible_departures_and_operation_id(tmp_path) -> None:
    async def _run() -> None:
        db = DatabaseService(str(tmp_path / "test.sqlite"))
        await db.connect()
        await db.initialize_schema()

        operation_id = "inactive-op-123"
        await db.insert_member_flow_event(
            guild_id="55",
            user_id="7",
            event_type_key="inactive_grace",
            occurred_at="2026-03-18T08:00:00+00:00",
            source="inactivity",
            source_ref="moderation_actions:grace-1",
            operation_id=operation_id,
            visible_in_greetings=False,
            metadata={"step": "grace"},
        )
        visible_departure = await db.insert_member_flow_event(
            guild_id="55",
            user_id="7",
            event_type_key="inactive_tempban",
            occurred_at="2026-03-19T08:00:00+00:00",
            source="inactivity",
            source_ref="moderation_actions:tempban-1",
            operation_id=operation_id,
            visible_in_greetings=True,
            metadata={"step": "tempban"},
        )
        await db.insert_member_flow_event(
            guild_id="55",
            user_id="7",
            event_type_key="join",
            occurred_at="2026-03-20T08:00:00+00:00",
            source="discord",
            source_ref="events:join-1",
            visible_in_greetings=True,
            metadata={"step": "join"},
        )

        recent_departures = await db.list_recent_visible_departures("55", "7", "2026-03-18T00:00:00+00:00")
        operation_rows = await db.list_member_flow_events_by_operation_id("55", operation_id)

        assert [row["event_type_key"] for row in recent_departures] == ["inactive_tempban"]
        assert recent_departures[0]["id"] == visible_departure["id"]
        assert [row["event_type_key"] for row in operation_rows] == ["inactive_grace", "inactive_tempban"]
        assert all(row["operation_id"] == operation_id for row in operation_rows)

        await db.close()

    asyncio.run(_run())
