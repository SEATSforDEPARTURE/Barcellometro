import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.database import DatabaseService
from app.services.message_scheduler import (
    calculate_initial_next_run,
    should_skip_for_idle,
)


def test_next_run_calculation() -> None:
    tz = ZoneInfo("Europe/Rome")
    now = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    next_run = calculate_initial_next_run(now, "10:00", 60, tz)
    assert next_run == datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)

    now_late = datetime(2024, 1, 1, 10, 30, tzinfo=timezone.utc)
    next_run_late = calculate_initial_next_run(now_late, "10:00", 120, tz)
    assert next_run_late == datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc)


def test_idle_skip() -> None:
    now = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    last_activity_recent = now - timedelta(minutes=5)
    last_activity_old = now - timedelta(minutes=20)
    assert should_skip_for_idle(
        last_activity=last_activity_recent,
        only_if_idle_minutes=10,
        now_utc=now,
    )
    assert not should_skip_for_idle(
        last_activity=last_activity_old,
        only_if_idle_minutes=10,
        now_utc=now,
    )


def test_db_crud_campaigns() -> None:
    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()

        await db.set_message_channel_enabled("guild1", "channel1", True)
        assert await db.get_message_channel_status("guild1", "channel1") is True

        campaign_id = await db.create_message_campaign(
            guild_id="guild1",
            campaign_type="CUSTOM",
            name=None,
            text="Hello world",
            enabled=True,
            start_time_local="10:00",
            interval_minutes=60,
            jitter_seconds=0,
            only_if_idle_minutes=0,
            next_run_at=datetime.now(timezone.utc).isoformat(),
            created_by="user1",
        )
        campaigns = await db.list_message_campaigns("guild1", include_disabled=True)
        assert len(campaigns) == 1
        assert campaigns[0]["id"] == campaign_id

        await db.set_message_campaign_enabled("guild1", campaign_id, False)
        campaign = await db.get_message_campaign("guild1", campaign_id)
        assert campaign is not None
        assert campaign["enabled"] == 0

        await db.soft_delete_message_campaign("guild1", campaign_id)
        campaigns_after = await db.list_message_campaigns("guild1", include_disabled=True)
        assert campaigns_after == []

        await db.close()

    asyncio.run(_run())
