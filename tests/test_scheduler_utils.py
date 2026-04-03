from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.services.scheduler_utils import (
    calculate_initial_next_run,
    calculate_next_run_after_send,
    calculate_next_wall_clock_run,
)


def test_calculate_initial_next_run_regression() -> None:
    tz = ZoneInfo("Europe/Rome")
    now = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    next_run = calculate_initial_next_run(now, "10:00", 60, tz)
    assert next_run == datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)


def test_calculate_next_run_after_send_regression() -> None:
    now = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert calculate_next_run_after_send(now, 15, 0) == datetime(2024, 1, 1, 12, 15, tzinfo=timezone.utc)


def test_calculate_next_wall_clock_run_daily_keeps_local_time_across_dst_start() -> None:
    tz = ZoneInfo("Europe/Rome")
    due_slot = datetime(2026, 3, 28, 22, 55, tzinfo=timezone.utc).isoformat()  # 23:55 local (CET)
    now = datetime(2026, 3, 28, 22, 55, tzinfo=timezone.utc)
    next_run = calculate_next_wall_clock_run(
        now_utc=now,
        due_slot_iso=due_slot,
        interval_minutes=1440,
        jitter_seconds=0,
        tz=tz,
    )
    assert next_run == datetime(2026, 3, 29, 21, 55, tzinfo=timezone.utc)
    assert next_run.astimezone(tz).strftime("%H:%M") == "23:55"


def test_calculate_next_wall_clock_run_daily_keeps_local_time_across_dst_end() -> None:
    tz = ZoneInfo("Europe/Rome")
    due_slot = datetime(2026, 10, 24, 21, 55, tzinfo=timezone.utc).isoformat()  # 23:55 local (CEST)
    now = datetime(2026, 10, 24, 21, 55, tzinfo=timezone.utc)
    next_run = calculate_next_wall_clock_run(
        now_utc=now,
        due_slot_iso=due_slot,
        interval_minutes=1440,
        jitter_seconds=0,
        tz=tz,
    )
    assert next_run == datetime(2026, 10, 25, 22, 55, tzinfo=timezone.utc)
    assert next_run.astimezone(tz).strftime("%H:%M") == "23:55"
