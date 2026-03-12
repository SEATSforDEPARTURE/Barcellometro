import asyncio
from pathlib import Path

import pytest


def test_no_recursive_call_in_channel_summary_window_helper() -> None:
    source = Path("app/plugins/commands_modular/resoconto.py").read_text()
    marker = "async def _run_channel_summary_window"
    start = source.find(marker)
    assert start >= 0
    end = source.find("@canale_group.command", start)
    helper_body = source[start:end]
    assert "await _run_channel_summary_window(" not in helper_body


def test_manual_window_helper_does_not_auto_enable_channel_summary() -> None:
    source = Path("app/plugins/commands_modular/resoconto.py").read_text()
    marker = "async def _run_channel_summary_window"
    start = source.find(marker)
    assert start >= 0
    end = source.find("@canale_group.command", start)
    helper_body = source[start:end]
    assert "set_channel_summary_auto_enabled" in helper_body
    assert "if publish_at_dt:" in helper_body
    schedule_pos = helper_body.find("if publish_at_dt:")
    auto_enable_pos = helper_body.find("set_channel_summary_auto_enabled")
    assert auto_enable_pos > schedule_pos


def test_resoconto_oggi_e_ieri_route_to_window_helper() -> None:
    source = Path("app/plugins/commands_modular/resoconto.py").read_text()
    assert "async def canale_oggi" in source
    assert 'schedule_type="oggi"' in source
    assert "async def canale_ieri" in source
    assert 'schedule_type="ieri"' in source


def test_edit_allows_clearing_recurrence_with_off_or_none() -> None:
    source = Path("app/plugins/commands_modular/resoconto.py").read_text()
    assert 'normalized_every in {"off", "none"}' in source


def test_schedule_scoped_queries_stay_guild_channel_bound() -> None:
    source = Path("app/services/database.py").read_text()
    assert "WHERE guild_id = ? AND channel_id = ?" in source


def test_renderer_has_window_level_barcello_todo_for_moments() -> None:
    source = Path("app/renderers/channel_summary_renderer.py").read_text()
    assert "TODO: use per-moment Barcello snapshots" in source


def test_update_schedule_can_clear_recurrence_and_keep_publish_at() -> None:
    pytest.importorskip("aiosqlite")
    from app.services.database import DatabaseService

    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        try:
            await db.initialize_schema()
            schedule_id = await db.create_channel_summary_schedule(
                guild_id="1",
                channel_id="2",
                schedule_type="oggi",
                start_ts="2026-01-01T00:00:00+00:00",
                end_ts="2026-01-01T23:59:59+00:00",
                publish_at="2026-01-02T10:00:00+00:00",
                repeat_every_value=24,
                repeat_every_unit="hours",
                created_by="99",
            )
            ok = await db.update_channel_summary_schedule(
                schedule_id=schedule_id,
                guild_id="1",
                channel_id="2",
                publish_at=None,
                repeat_every_value=None,
                repeat_every_unit=None,
                status="active",
            )
            assert ok is True
            row = await db.get_channel_summary_schedule(schedule_id=schedule_id, guild_id="1", channel_id="2")
            assert row is not None
            assert row["repeat_every_value"] is None
            assert row["repeat_every_unit"] is None
            assert row["publish_at"] == "2026-01-02T10:00:00+00:00"
        finally:
            await db.close()

    asyncio.run(_run())


def test_schedule_channel_scope_for_status_edit_delete_clear() -> None:
    pytest.importorskip("aiosqlite")
    from app.services.database import DatabaseService

    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        try:
            await db.initialize_schema()
            sid = await db.create_channel_summary_schedule(
                guild_id="1",
                channel_id="10",
                schedule_type="oggi",
                start_ts="2026-01-01T00:00:00+00:00",
                end_ts="2026-01-01T23:59:59+00:00",
                publish_at="2026-01-02T10:00:00+00:00",
                repeat_every_value=None,
                repeat_every_unit=None,
                created_by="99",
            )
            s_same = await db.list_channel_summary_schedules("1", "10")
            s_other = await db.list_channel_summary_schedules("1", "11")
            assert len(s_same) == 1
            assert len(s_other) == 0

            assert await db.get_channel_summary_schedule(schedule_id=sid, guild_id="1", channel_id="11") is None
            assert await db.delete_channel_summary_schedule(schedule_id=sid, guild_id="1", channel_id="11") is False
            assert await db.clear_channel_summary_schedules(guild_id="1", channel_id="11") == 0
            assert await db.delete_channel_summary_schedule(schedule_id=sid, guild_id="1", channel_id="10") is True
        finally:
            await db.close()

    asyncio.run(_run())
