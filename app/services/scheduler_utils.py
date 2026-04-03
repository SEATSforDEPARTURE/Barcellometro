from __future__ import annotations

import random
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ROME_TZ = ZoneInfo("Europe/Rome")


def _parse_local_time(value: str) -> time:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError("start_time_local must be HH:MM")
    hour = int(parts[0])
    minute = int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("start_time_local must be HH:MM")
    return time(hour=hour, minute=minute)


def calculate_initial_next_run(now_utc: datetime, start_time_local: str, interval_minutes: int, tz: ZoneInfo = ROME_TZ) -> datetime:
    if interval_minutes <= 0:
        raise ValueError("interval_minutes must be > 0")
    start_clock = _parse_local_time(start_time_local)
    now_local = now_utc.astimezone(tz)
    candidate_local = now_local.replace(
        hour=start_clock.hour,
        minute=start_clock.minute,
        second=0,
        microsecond=0,
    )
    if candidate_local <= now_local:
        delta_minutes = int((now_local - candidate_local).total_seconds() // 60)
        steps = delta_minutes // interval_minutes + 1
        candidate_local = candidate_local + timedelta(minutes=steps * interval_minutes)
    return candidate_local.astimezone(timezone.utc)


def calculate_next_run_after_send(now_utc: datetime, interval_minutes: int, jitter_seconds: int) -> datetime:
    jitter = random.randint(0, max(jitter_seconds, 0))
    return now_utc + timedelta(minutes=interval_minutes, seconds=jitter)


def calculate_next_summary_schedule_run_utc(
    *,
    base_iso: str | None,
    repeat_every_value: int | None,
    repeat_every_unit: str | None,
    tz: ZoneInfo = ROME_TZ,
) -> datetime | None:
    if repeat_every_value is None:
        return None
    value = int(repeat_every_value)
    if value <= 0:
        return None
    unit = str(repeat_every_unit or "").strip().lower()
    if unit not in {"min", "hours", "days"}:
        return None

    base_raw = str(base_iso or "")
    try:
        base_utc = datetime.fromisoformat(base_raw.replace("Z", "+00:00"))
        if base_utc.tzinfo is None:
            base_utc = base_utc.replace(tzinfo=timezone.utc)
        else:
            base_utc = base_utc.astimezone(timezone.utc)
    except Exception:
        return None

    if unit == "days":
        return (base_utc.astimezone(tz) + timedelta(days=value)).astimezone(timezone.utc)

    if unit == "hours" and value % 24 == 0:
        return (base_utc.astimezone(tz) + timedelta(days=value // 24)).astimezone(timezone.utc)

    if unit == "min" and value % 1440 == 0:
        return (base_utc.astimezone(tz) + timedelta(days=value // 1440)).astimezone(timezone.utc)

    if unit == "hours":
        return base_utc + timedelta(hours=value)
    return base_utc + timedelta(minutes=value)


def is_in_quiet_hours(now_local_time: time, start_str: str, end_str: str) -> bool:
    start = _parse_local_time(start_str)
    end = _parse_local_time(end_str)
    if start <= end:
        return start <= now_local_time < end
    return now_local_time >= start or now_local_time < end
