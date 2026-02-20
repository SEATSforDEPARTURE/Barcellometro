import asyncio
import json

import pytest

aiosqlite = pytest.importorskip("aiosqlite")

from app.services.database import DatabaseService


def test_close_open_voice_sessions_filters_by_source() -> None:
    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()

        await db.execute(
            """
            INSERT INTO voice_sessions (voice_session_id, guild_id, voice_channel_id, started_ts, ended_ts, meta_json)
            VALUES (?, ?, ?, ?, NULL, ?)
            """,
            (
                "session-a",
                "guild-1",
                "voice-1",
                "2026-01-01T10:00:00+00:00",
                json.dumps({"source": "voice_ingest"}),
            ),
        )
        await db.execute(
            """
            INSERT INTO voice_sessions (voice_session_id, guild_id, voice_channel_id, started_ts, ended_ts, meta_json)
            VALUES (?, ?, ?, ?, NULL, ?)
            """,
            (
                "session-b",
                "guild-1",
                "voice-1",
                "2026-01-01T11:00:00+00:00",
                json.dumps({"source": "other"}),
            ),
        )
        await db.execute(
            """
            INSERT INTO voice_sessions (voice_session_id, guild_id, voice_channel_id, started_ts, ended_ts, meta_json)
            VALUES (?, ?, ?, ?, NULL, NULL)
            """,
            (
                "session-c",
                "guild-1",
                "voice-1",
                "2026-01-01T11:30:00+00:00",
            ),
        )

        ended_ts = "2026-01-01T12:00:00+00:00"
        updated = await db.close_open_voice_sessions(ended_ts=ended_ts, source="voice_ingest")
        assert updated == 1

        row_a = await db.fetchone("SELECT ended_ts FROM voice_sessions WHERE voice_session_id = ?", ("session-a",))
        row_b = await db.fetchone("SELECT ended_ts FROM voice_sessions WHERE voice_session_id = ?", ("session-b",))
        row_c = await db.fetchone("SELECT ended_ts FROM voice_sessions WHERE voice_session_id = ?", ("session-c",))

        assert row_a is not None and row_a["ended_ts"] == ended_ts
        assert row_b is not None and row_b["ended_ts"] is None
        assert row_c is not None and row_c["ended_ts"] is None

        await db.close()

    asyncio.run(_run())


def test_close_open_voice_sessions_without_source_closes_all() -> None:
    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()

        await db.execute(
            """
            INSERT INTO voice_sessions (voice_session_id, guild_id, voice_channel_id, started_ts, ended_ts, meta_json)
            VALUES (?, ?, ?, ?, NULL, ?)
            """,
            ("session-a", "guild-1", "voice-1", "2026-01-01T10:00:00+00:00", json.dumps({"source": "voice_ingest"})),
        )
        await db.execute(
            """
            INSERT INTO voice_sessions (voice_session_id, guild_id, voice_channel_id, started_ts, ended_ts, meta_json)
            VALUES (?, ?, ?, ?, NULL, ?)
            """,
            ("session-b", "guild-1", "voice-1", "2026-01-01T11:00:00+00:00", "{}"),
        )
        await db.execute(
            """
            INSERT INTO voice_sessions (voice_session_id, guild_id, voice_channel_id, started_ts, ended_ts, meta_json)
            VALUES (?, ?, ?, ?, NULL, NULL)
            """,
            ("session-c", "guild-1", "voice-1", "2026-01-01T12:00:00+00:00"),
        )

        ended_ts = "2026-01-01T13:00:00+00:00"
        updated = await db.close_open_voice_sessions(ended_ts=ended_ts, source=None)
        assert updated == 3

        remaining = await db.fetchone("SELECT COUNT(*) AS c FROM voice_sessions WHERE ended_ts IS NULL")
        assert remaining is not None
        assert remaining["c"] == 0

        await db.close()

    asyncio.run(_run())


def test_unique_active_voice_session_per_channel() -> None:
    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()

        await db.start_voice_session(
            voice_session_id="session-a",
            guild_id="guild-1",
            voice_channel_id="voice-1",
            started_ts="2026-01-01T10:00:00+00:00",
            meta={"source": "voice_ingest"},
        )

        duplicate_failed = False
        try:
            await db.start_voice_session(
                voice_session_id="session-b",
                guild_id="guild-1",
                voice_channel_id="voice-1",
                started_ts="2026-01-01T10:05:00+00:00",
                meta={"source": "voice_ingest"},
            )
        except aiosqlite.IntegrityError:
            duplicate_failed = True

        assert duplicate_failed is True

        active_count = await db.fetchone(
            """
            SELECT COUNT(*) AS c
            FROM voice_sessions
            WHERE guild_id = ? AND voice_channel_id = ? AND ended_ts IS NULL
            """,
            ("guild-1", "voice-1"),
        )
        assert active_count is not None
        assert active_count["c"] == 1

        await db.close()

    asyncio.run(_run())
