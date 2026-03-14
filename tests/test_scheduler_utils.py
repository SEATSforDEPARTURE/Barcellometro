from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.services.scheduler_utils import calculate_initial_next_run, calculate_next_run_after_send


def test_calculate_initial_next_run_regression() -> None:
    tz = ZoneInfo("Europe/Rome")
    now = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    next_run = calculate_initial_next_run(now, "10:00", 60, tz)
    assert next_run == datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)


def test_calculate_next_run_after_send_regression() -> None:
    now = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert calculate_next_run_after_send(now, 15, 0) == datetime(2024, 1, 1, 12, 15, tzinfo=timezone.utc)
