import asyncio
import json

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

        ended_ts = "2026-01-01T12:00:00+00:00"
        updated = await db.close_open_voice_sessions(ended_ts=ended_ts, source="voice_ingest")
        assert updated == 1

        row_a = await db.fetchone(
            "SELECT ended_ts FROM voice_sessions WHERE voice_session_id = ?",
            ("session-a",),
        )
        row_b = await db.fetchone(
            "SELECT ended_ts FROM voice_sessions WHERE voice_session_id = ?",
            ("session-b",),
        )

        assert row_a is not None
        assert row_b is not None
        assert row_a["ended_ts"] == ended_ts
        assert row_b["ended_ts"] is None

        await db.close()

    asyncio.run(_run())
