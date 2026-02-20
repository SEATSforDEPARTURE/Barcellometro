import asyncio

import pytest

pytest.importorskip("aiosqlite")

from app.services.database import DatabaseService


def test_fetch_voice_participant_events_in_range_ordered() -> None:
    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()

        await db.insert_voice_participant_event(
            event_id="e2",
            guild_id="g1",
            voice_channel_id="c1",
            user_id="u2",
            username="Beta",
            event_type="leave",
            ts="2026-01-01T10:02:00+00:00",
        )
        await db.insert_voice_participant_event(
            event_id="e1",
            guild_id="g1",
            voice_channel_id="c1",
            user_id="u1",
            username="Alpha",
            event_type="join",
            ts="2026-01-01T10:01:00+00:00",
        )

        rows = await db.fetch_voice_participant_events_in_range(
            guild_id="g1",
            voice_channel_id="c1",
            start_ts="2026-01-01T10:00:00+00:00",
            end_ts="2026-01-01T10:03:00+00:00",
        )

        assert [row["event_id"] for row in rows] == ["e1", "e2"]
        assert [row["event_type"] for row in rows] == ["join", "leave"]

        await db.close()

    asyncio.run(_run())
