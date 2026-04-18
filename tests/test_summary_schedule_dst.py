import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.services.database import DatabaseService

ROME_TZ = ZoneInfo("Europe/Rome")


def _utc_iso_from_rome(year: int, month: int, day: int, hour: int, minute: int) -> str:
    return datetime(year, month, day, hour, minute, tzinfo=ROME_TZ).astimezone(timezone.utc).isoformat()


def _rome_hhmm(iso_utc: str) -> str:
    return datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(ROME_TZ).strftime("%H:%M")


def test_channel_summary_daily_1440min_remains_same_local_time_across_dst() -> None:
    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()

        sid = await db.create_channel_summary_schedule(
            guild_id="g",
            channel_id="c",
            schedule_type="daily",
            embed_section=None,
            start_ts=None,
            end_ts=None,
            publish_at=_utc_iso_from_rome(2026, 3, 12, 23, 55),
            repeat_every_value=1440,
            repeat_every_unit="min",
            created_by="u",
        )

        for _ in range(25):
            await db.mark_channel_summary_schedule_sent(sid)
            row = await db.get_channel_summary_schedule(schedule_id=sid, guild_id="g", channel_id="c")
            assert row is not None
            assert _rome_hhmm(str(row["next_run_at"])) == "23:55"

        await db.close()

    asyncio.run(_run())


def test_server_summary_daily_1440min_remains_same_local_time_across_dst() -> None:
    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()

        sid = await db.create_server_summary_schedule(
            guild_id="g",
            schedule_type="daily",
            start_ts=None,
            end_ts=None,
            publish_at=_utc_iso_from_rome(2026, 3, 12, 23, 55),
            repeat_every_value=1440,
            repeat_every_unit="min",
            created_by="u",
            enabled=True,
        )

        for _ in range(25):
            await db.mark_server_summary_schedule_sent(sid)
            row = await db.get_server_summary_schedule(schedule_id=sid, guild_id="g")
            assert row is not None
            assert _rome_hhmm(str(row["next_run_at"])) == "23:55"

        await db.close()

    asyncio.run(_run())


def test_channel_summary_daily_1day_remains_same_local_time_across_dst() -> None:
    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()

        sid = await db.create_channel_summary_schedule(
            guild_id="g",
            channel_id="c",
            schedule_type="daily",
            embed_section=None,
            start_ts=None,
            end_ts=None,
            publish_at=_utc_iso_from_rome(2026, 3, 12, 23, 55),
            repeat_every_value=1,
            repeat_every_unit="days",
            created_by="u",
        )

        for _ in range(25):
            await db.mark_channel_summary_schedule_sent(sid)
            row = await db.get_channel_summary_schedule(schedule_id=sid, guild_id="g", channel_id="c")
            assert row is not None
            assert _rome_hhmm(str(row["next_run_at"])) == "23:55"

        await db.close()

    asyncio.run(_run())


def test_channel_summary_daily_24hours_remains_same_local_time_across_dst() -> None:
    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()

        sid = await db.create_channel_summary_schedule(
            guild_id="g",
            channel_id="c",
            schedule_type="daily",
            embed_section=None,
            start_ts=None,
            end_ts=None,
            publish_at=_utc_iso_from_rome(2026, 3, 12, 23, 55),
            repeat_every_value=24,
            repeat_every_unit="hours",
            created_by="u",
        )

        for _ in range(25):
            await db.mark_channel_summary_schedule_sent(sid)
            row = await db.get_channel_summary_schedule(schedule_id=sid, guild_id="g", channel_id="c")
            assert row is not None
            assert _rome_hhmm(str(row["next_run_at"])) == "23:55"

        await db.close()

    asyncio.run(_run())


def test_channel_summary_pre_dst_non_regression() -> None:
    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()

        sid = await db.create_channel_summary_schedule(
            guild_id="g",
            channel_id="c",
            schedule_type="daily",
            embed_section=None,
            start_ts=None,
            end_ts=None,
            publish_at=_utc_iso_from_rome(2026, 3, 12, 23, 55),
            repeat_every_value=1,
            repeat_every_unit="days",
            created_by="u",
        )

        await db.mark_channel_summary_schedule_sent(sid)
        row = await db.get_channel_summary_schedule(schedule_id=sid, guild_id="g", channel_id="c")
        assert row is not None
        next_run_utc = datetime.fromisoformat(str(row["next_run_at"]).replace("Z", "+00:00"))
        assert next_run_utc == datetime(2026, 3, 13, 22, 55, tzinfo=timezone.utc)

        await db.close()

    asyncio.run(_run())


def test_summary_schedule_one_shot_marks_completed() -> None:
    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()

        channel_sid = await db.create_channel_summary_schedule(
            guild_id="g",
            channel_id="c",
            schedule_type="one_shot",
            embed_section=None,
            start_ts=None,
            end_ts=None,
            publish_at=_utc_iso_from_rome(2026, 3, 12, 23, 55),
            repeat_every_value=None,
            repeat_every_unit=None,
            created_by="u",
        )
        await db.mark_channel_summary_schedule_sent(channel_sid)
        channel_row = await db.get_channel_summary_schedule(schedule_id=channel_sid, guild_id="g", channel_id="c")
        assert channel_row is not None
        assert channel_row["status"] == "completed"
        assert channel_row["next_run_at"] is None

        server_sid = await db.create_server_summary_schedule(
            guild_id="g",
            schedule_type="one_shot",
            start_ts=None,
            end_ts=None,
            publish_at=_utc_iso_from_rome(2026, 3, 12, 23, 55),
            repeat_every_value=None,
            repeat_every_unit=None,
            created_by="u",
            enabled=True,
        )
        await db.mark_server_summary_schedule_sent(server_sid)
        server_row = await db.get_server_summary_schedule(schedule_id=server_sid, guild_id="g")
        assert server_row is not None
        assert server_row["status"] == "completed"
        assert server_row["next_run_at"] is None

        await db.close()

    asyncio.run(_run())
