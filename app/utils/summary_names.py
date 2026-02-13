from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.services.database import DatabaseService


def is_valid_snowflake(value: str) -> bool:
    return bool(re.fullmatch(r"\d{17,20}", str(value or "")))


def parse_iso_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


async def resolve_primary_message_id(
    *,
    database: DatabaseService,
    channel_id: str,
    start_ts: str,
    end_ts: str,
    ts: str | None,
    message_ids: list[str],
) -> str | None:
    for mid in message_ids:
        mid_str = str(mid)
        if not is_valid_snowflake(mid_str):
            continue
        if await database.message_exists_in_channel(channel_id=channel_id, message_id=mid_str):
            return mid_str

    parsed = parse_iso_ts(ts)
    if parsed is not None:
        return await database.fetch_nearest_message_id_in_range(
            channel_id=channel_id,
            start_ts=start_ts,
            end_ts=end_ts,
            ts=parsed.isoformat(),
        )

    start_dt = parse_iso_ts(start_ts)
    end_dt = parse_iso_ts(end_ts)
    if start_dt and end_dt:
        midpoint = start_dt + (end_dt - start_dt) / 2
        return await database.fetch_nearest_message_id_in_range(
            channel_id=channel_id,
            start_ts=start_ts,
            end_ts=end_ts,
            ts=midpoint.isoformat(),
        )
    return None


async def resolve_display_name_from_message_id(
    *,
    database: DatabaseService,
    guild_id: str,
    channel_id: str,
    message_id: str | None,
    message_cache: dict[str, dict[str, Any]],
) -> str | None:
    if not message_id:
        return None
    if message_id in message_cache:
        record = message_cache[message_id]
    else:
        row = await database.fetch_message_by_id(channel_id=channel_id, message_id=message_id)
        if not row:
            return None
        record = {
            "author_id": str(row["author_id"] or "") or None,
            "content": str(row["content"] or ""),
        }
        message_cache[message_id] = record

    author_id = str(record.get("author_id") or "").strip()
    if not author_id:
        return None
    return safe_display_name(await database.fetch_user_display_name(guild_id=guild_id, user_id=author_id))



def safe_display_name(name: str | None) -> str | None:
    if name is None:
        return None
    trimmed = str(name).strip()
    return trimmed or None
