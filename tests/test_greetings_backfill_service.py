from __future__ import annotations

import asyncio
import sqlite3
import sys
import types
from datetime import datetime, timedelta, timezone


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
from app.services.greetings_backfill_service import GreetingsBackfillService


def _iso(hour: int, minute: int = 0) -> str:
    return datetime(2026, 3, 20, hour, minute, tzinfo=timezone.utc).isoformat()


async def _insert_moderation_action(
    db: DatabaseService,
    *,
    action_id: str,
    guild_id: str,
    user_id: str,
    action_type: str,
    created_at: str,
    moderator_id: str | None = None,
    reason: str | None = None,
    duration_seconds: int | None = None,
    expires_at: str | None = None,
    metadata_json: str = "{}",
) -> None:
    await db.execute(
        """
        INSERT INTO moderation_actions (
            id, guild_id, user_id, moderator_id, action_type, reason, duration_seconds, duration_days, expires_at, created_at, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            action_id,
            guild_id,
            user_id,
            moderator_id,
            action_type,
            reason,
            duration_seconds,
            None,
            expires_at,
            created_at,
            metadata_json,
        ),
    )


async def _insert_event(db: DatabaseService, *, ts: str, event_type: str, guild_id: str, actor_id: str, target_id: str) -> None:
    await db.execute(
        """
        INSERT INTO events (ts, event_type, platform, guild_id, channel_id, actor_id, target_id, meta_json)
        VALUES (?, ?, 'discord', ?, NULL, ?, ?, ?)
        """,
        (ts, event_type, guild_id, actor_id, target_id, '{"target_id": "%s"}' % target_id),
    )


def test_greetings_backfill_service_status_and_run_are_idempotent(tmp_path) -> None:
    async def _run() -> None:
        db = DatabaseService(str(tmp_path / "test.sqlite"))
        await db.connect()
        await db.initialize_schema()
        service = GreetingsBackfillService(db)
        await service.load_settings()

        initial = await service.status("1")
        assert initial == {
            "enabled": False,
            "last_run_at": None,
            "last_run_imported_count": None,
            "last_run_skipped_count": None,
            "canonical_count": 0,
        }

        await _insert_moderation_action(
            db,
            action_id="join-1",
            guild_id="1",
            user_id="10",
            action_type="join",
            created_at=_iso(10, 0),
            reason="Ingresso nel server",
            metadata_json='{"source": "discord_adapter"}',
        )
        await _insert_moderation_action(
            db,
            action_id="kick-1",
            guild_id="1",
            user_id="11",
            action_type="kick",
            created_at=_iso(11, 0),
            moderator_id="99",
            reason="Kick storico",
            metadata_json='{"source": "member_flow_notifications"}',
        )
        await _insert_moderation_action(
            db,
            action_id="inactive-kick-1",
            guild_id="1",
            user_id="12",
            action_type="inactive_kick",
            created_at=_iso(12, 0),
            reason="Inattività",
            metadata_json='{"source": "inactive_members_moderation", "operation_id": "op-1"}',
        )
        await _insert_moderation_action(
            db,
            action_id="inactive-tempban-1",
            guild_id="1",
            user_id="12",
            action_type="inactive_tempban",
            created_at=_iso(12, 1),
            reason="Inattività",
            duration_seconds=7 * 86400,
            metadata_json='{"source": "inactive_members_moderation", "operation_id": "op-1"}',
        )
        await _insert_moderation_action(
            db,
            action_id="inactive-grace-1",
            guild_id="1",
            user_id="13",
            action_type="inactive_grace",
            created_at=_iso(13, 0),
            reason="Periodo di grazia",
            expires_at=_iso(14, 0),
            metadata_json='{"source": "inactive_members_moderation"}',
        )
        await db.execute(
            "INSERT INTO temp_bans (guild_id, user_id, unban_at, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            ("1", "12", _iso(19, 0), "Inattività", _iso(12, 1)),
        )
        await db.execute(
            "INSERT INTO inactivity_user_state (guild_id, user_id, last_reminder_at, reminder_count, last_kick_at) VALUES (?, ?, ?, ?, ?)",
            ("1", "12", _iso(9, 0), 2, _iso(12, 0)),
        )

        await _insert_event(db, ts=_iso(10, 5), event_type="member.leave", guild_id="1", actor_id="10", target_id="10")
        await _insert_event(db, ts=_iso(11, 1), event_type="member.leave", guild_id="1", actor_id="11", target_id="11")
        await _insert_event(db, ts=_iso(14, 0), event_type="member.join", guild_id="1", actor_id="14", target_id="14")

        await service.set_enabled(True)
        first = await service.run_once(guild_id="1")
        second = await service.run_once(guild_id="1")

        assert first.imported_count == 7
        assert first.skipped_count == 1
        assert first.canonical_count == 7
        assert second.imported_count == 0
        assert second.skipped_count == 8
        assert second.canonical_count == 7

        rows = await db.fetchall(
            "SELECT event_type_key, user_id, visible_in_greetings, source, source_ref, expires_at, metadata_json FROM member_flow_events WHERE guild_id = ? ORDER BY occurred_at ASC, id ASC",
            ("1",),
        )
        simplified = [
            (
                row["event_type_key"],
                row["user_id"],
                bool(row["visible_in_greetings"]),
                row["source_ref"],
                row["expires_at"],
                row["metadata_json"],
            )
            for row in rows
        ]

        assert [item[:3] for item in simplified] == [
            ("join", "10", True),
            ("leave", "10", True),
            ("kick", "11", True),
            ("inactive_kick", "12", False),
            ("inactive_tempban", "12", True),
            ("inactive_grace", "13", False),
            ("join", "14", True),
        ]
        assert all(source_ref != "events:2" for _, _, _, source_ref, _, _ in simplified)
        tempban_row = next(item for item in rows if item["event_type_key"] == "inactive_tempban")
        assert tempban_row["expires_at"] == _iso(19, 0)
        assert '"backfill_source": "moderation_actions"' in tempban_row["metadata_json"]
        assert '"reminder_count": 2' in tempban_row["metadata_json"]
        assert '"state_last_kick_at": "2026-03-20T12:00:00+00:00"' in tempban_row["metadata_json"]

        status = await service.status("1")
        assert status["enabled"] is True
        assert status["canonical_count"] == 7
        assert status["last_run_imported_count"] == 0
        assert status["last_run_skipped_count"] == 8
        assert status["last_run_at"] is not None

        await db.close()

    asyncio.run(_run())
