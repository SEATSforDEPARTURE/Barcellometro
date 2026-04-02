from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("aiosqlite")

from app.services.database import DatabaseService


def test_trigger_barcello_schedule_crud_and_due_list() -> None:
    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        try:
            await db.initialize_schema()
            now = datetime.now(timezone.utc)
            schedule_id = await db.create_trigger_barcello_schedule(
                guild_id="g1",
                channel_id="c1",
                publish_at="09:00",
                next_run_at=(now - timedelta(minutes=1)).isoformat(),
                every_minutes=30,
            )
            row = await db.get_trigger_barcello_schedule(schedule_id)
            assert row is not None
            assert row["guild_id"] == "g1"

            rows = await db.list_trigger_barcello_schedules("g1", "c1")
            assert len(rows) == 1

            due = await db.list_due_trigger_barcello_schedules(now.isoformat())
            assert [int(item["id"]) for item in due] == [schedule_id]

            updated = await db.update_trigger_barcello_schedule(
                schedule_id,
                enabled=False,
                embed_title="Custom",
                next_run_at=(now + timedelta(minutes=10)).isoformat(),
            )
            assert updated is True
            row_after = await db.get_trigger_barcello_schedule(schedule_id)
            assert row_after is not None
            assert int(row_after["enabled"]) == 0
            assert row_after["embed_title"] == "Custom"

            deleted = await db.delete_trigger_barcello_schedule(schedule_id)
            assert deleted is True
            assert await db.get_trigger_barcello_schedule(schedule_id) is None
        finally:
            await db.close()

    asyncio.run(_run())


def test_trigger_barcello_anchor_upsert_and_get() -> None:
    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        try:
            await db.initialize_schema()
            ts1 = datetime.now(timezone.utc).isoformat()
            await db.upsert_trigger_barcello_publish_anchor(
                guild_id="g1",
                channel_id="c1",
                last_color="GIALLO",
                last_score=50,
                last_ts=ts1,
                last_kind="scheduled",
            )
            anchor = await db.get_trigger_barcello_publish_anchor("g1", "c1")
            assert anchor is not None
            assert anchor["last_kind"] == "scheduled"

            ts2 = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
            await db.upsert_trigger_barcello_publish_anchor(
                guild_id="g1",
                channel_id="c1",
                last_color="ROSSO",
                last_score=30,
                last_ts=ts2,
                last_kind="state_change",
            )
            anchor_after = await db.get_trigger_barcello_publish_anchor("g1", "c1")
            assert anchor_after is not None
            assert anchor_after["last_color"] == "ROSSO"
            assert int(anchor_after["last_score"]) == 30
            assert anchor_after["last_kind"] == "state_change"
        finally:
            await db.close()

    asyncio.run(_run())


def test_trigger_barcello_quiet_hours_upsert_get_delete() -> None:
    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        try:
            await db.initialize_schema()
            assert await db.get_trigger_barcello_quiet_hours("g1", "c1") is None
            await db.upsert_trigger_barcello_quiet_hours(
                guild_id="g1",
                channel_id="c1",
                quiet_start="23:00",
                quiet_end="08:00",
            )
            quiet = await db.get_trigger_barcello_quiet_hours("g1", "c1")
            assert quiet is not None
            assert quiet["quiet_start"] == "23:00"
            assert quiet["quiet_end"] == "08:00"
            await db.upsert_trigger_barcello_quiet_hours(
                guild_id="g1",
                channel_id="c1",
                quiet_start="22:30",
                quiet_end="07:30",
            )
            quiet_after = await db.get_trigger_barcello_quiet_hours("g1", "c1")
            assert quiet_after is not None
            assert quiet_after["quiet_start"] == "22:30"
            assert quiet_after["quiet_end"] == "07:30"
            assert await db.delete_trigger_barcello_quiet_hours("g1", "c1") is True
            assert await db.get_trigger_barcello_quiet_hours("g1", "c1") is None
        finally:
            await db.close()

    asyncio.run(_run())
