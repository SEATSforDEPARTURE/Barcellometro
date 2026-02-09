import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.database import DatabaseService
from app.services.message_scheduler import (
    calculate_initial_next_run,
    is_in_quiet_hours,
    select_round_robin_campaign,
    select_text_for_mood,
    should_skip_for_daily_cap,
    should_skip_for_idle,
)
from app.plugins.commands_modular.messaggi import validate_campaign_texts


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


def test_is_in_quiet_hours() -> None:
    assert is_in_quiet_hours(datetime(2024, 1, 1, 2, 0).time(), "01:00", "08:30")
    assert not is_in_quiet_hours(datetime(2024, 1, 1, 10, 0).time(), "01:00", "08:30")
    assert is_in_quiet_hours(datetime(2024, 1, 1, 23, 0).time(), "22:00", "07:00")
    assert is_in_quiet_hours(datetime(2024, 1, 1, 6, 30).time(), "22:00", "07:00")
    assert not is_in_quiet_hours(datetime(2024, 1, 1, 12, 0).time(), "22:00", "07:00")


def test_daily_cap_skip() -> None:
    assert should_skip_for_daily_cap(6, 6)
    assert not should_skip_for_daily_cap(5, 6)


def test_round_robin_selection() -> None:
    now = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    campaigns = [
        {"id": 1, "next_run_at": now.isoformat()},
        {"id": 2, "next_run_at": now.isoformat()},
        {"id": 3, "next_run_at": now.isoformat()},
    ]
    selected = select_round_robin_campaign(campaigns, 2, now)
    assert selected["id"] == 3
    selected_wrap = select_round_robin_campaign(campaigns, 3, now)
    assert selected_wrap["id"] == 1

    campaigns[2]["next_run_at"] = (now + timedelta(minutes=10)).isoformat()
    selected_fallback = select_round_robin_campaign(campaigns, 2, now)
    assert selected_fallback["id"] == 1


def test_barcello_text_selection() -> None:
    text, reason, _ = select_text_for_mood(
        mood_mode="AUTO",
        base_text="base",
        text_green=None,
        text_yellow=None,
        text_red="red",
        text_black="black",
        barcello_color="RED",
    )
    assert text == "red"
    assert reason == "barcello_red"

    text, reason, _ = select_text_for_mood(
        mood_mode="AUTO",
        base_text="base",
        text_green=None,
        text_yellow=None,
        text_red=None,
        text_black="black",
        barcello_color="RED",
    )
    assert text == "base"
    assert reason == "barcello_red"

    text, reason, _ = select_text_for_mood(
        mood_mode="RED_ONLY",
        base_text="base",
        text_green=None,
        text_yellow=None,
        text_red=None,
        text_black=None,
        barcello_color="GREEN",
    )
    assert text == "base"
    assert reason == "barcello_red"

    text, reason, _ = select_text_for_mood(
        mood_mode="AUTO",
        base_text=None,
        text_green=None,
        text_yellow=None,
        text_red=None,
        text_black="black",
        barcello_color="BLACK",
    )
    assert text == "black"
    assert reason == "barcello_black"


def test_validate_campaign_texts() -> None:
    error = validate_campaign_texts(
        testo=None,
        testo_verde=None,
        testo_giallo=None,
        testo_rosso=None,
        testo_nero=None,
        mood_mode="AUTO",
    )
    assert error is not None

    error = validate_campaign_texts(
        testo=None,
        testo_verde="ciao",
        testo_giallo=None,
        testo_rosso=None,
        testo_nero=None,
        mood_mode="AUTO",
    )
    assert error is None

    error = validate_campaign_texts(
        testo=None,
        testo_verde=None,
        testo_giallo=None,
        testo_rosso=None,
        testo_nero="ciao",
        mood_mode="IGNORE_BARCELLO",
    )
    assert error is not None


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
            text_green=None,
            text_yellow=None,
            text_red=None,
            text_black=None,
            enabled=True,
            start_time_local="10:00",
            interval_minutes=60,
            jitter_seconds=0,
            only_if_idle_minutes=0,
            mood_mode="AUTO",
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
