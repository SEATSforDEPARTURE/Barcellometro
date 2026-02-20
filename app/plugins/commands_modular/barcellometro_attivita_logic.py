from __future__ import annotations

import re
from typing import Any


def validate_hhmm(value: str) -> str | None:
    if not re.fullmatch(r"\d{2}:\d{2}", value or ""):
        return "invalid"
    hh, mm = value.split(":", 1)
    hour = int(hh)
    minute = int(mm)
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return "invalid"
    return None


async def set_activity_send_time(database: Any, *, guild_id: str, hhmm: str) -> str | None:
    cfg = await database.get_activity_monitoring_config(guild_id)
    enabled = bool(cfg["enabled"]) if cfg else True
    mod_channel_id = str(cfg["mod_channel_id"]) if cfg and cfg["mod_channel_id"] else None
    await database.upsert_activity_monitoring_config(
        guild_id,
        enabled=enabled,
        mod_channel_id=mod_channel_id,
        send_time_local=hhmm,
    )
    return mod_channel_id


async def send_activity_now(database: Any, daily_activity_report: Any, *, guild_id: str) -> str | None:
    cfg = await database.get_activity_monitoring_config(guild_id)
    mod_channel_id = str(cfg["mod_channel_id"]) if cfg and cfg["mod_channel_id"] else None
    if not mod_channel_id:
        return None
    await daily_activity_report.send_now(guild_id=guild_id, mod_channel_id=mod_channel_id)
    return mod_channel_id
