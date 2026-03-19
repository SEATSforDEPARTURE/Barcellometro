import asyncio
from datetime import datetime
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_resoconto_uses_schedule_standard_commands_only() -> None:
    source = Path("app/features/summary/commands/resoconto.py").read_text()

    for command_name in ["schedule_add", "schedule_edit", "schedule_remove", "schedule_show", "schedule_list"]:
        assert f'name="{command_name}"' in source

    assert 'name="edit"' not in source
    assert 'name="delete"' not in source
    assert 'name="clear"' not in source
    assert 'name="oggi"' not in source.split("canale_aura_group")[0]
    assert 'name="ieri"' not in source.split("canale_aura_group")[0]


def test_resoconto_schedule_commands_use_publish_at_every_and_enabled() -> None:
    source = Path("app/features/summary/commands/resoconto.py").read_text()

    assert "publish_at" in source
    assert "every" in source
    assert "enabled: bool | None = None" in source
    assert "schedule_kind" in source


def test_schedule_scoped_queries_stay_guild_channel_bound() -> None:
    source = Path("app/services/database.py").read_text()
    assert "WHERE guild_id = ? AND channel_id = ?" in source


def test_window_header_is_always_bold_across_period_types() -> None:
    source = Path("app/features/summary/renderers/channel_summary.py").read_text()
    assert "**🗓️ Oggi." in source
    assert "**🗓️ Ieri." in source
    assert "**🗓️ {title}" in source
    assert "**🗓️ {start_dt.strftime('%d/%m/%Y %H:%M')} → {end_dt.strftime('%d/%m/%Y %H:%M')}**" in source


def test_renderer_supports_per_moment_barcello_map() -> None:
    source = Path("app/features/summary/renderers/channel_summary.py").read_text()
    assert "moment_barcello: dict[int, BarcelloResult] | None = None" in source
    assert "(moment_barcello or {}).get(id(it), barcello_status)" in source


def test_channel_summary_trend_uses_previous_equivalent_window() -> None:
    source = Path("app/features/summary/services/channel_summary_service.py").read_text()
    assert "duration = max(timedelta(minutes=1), current_end_local - current_start_local)" in source
    assert "previous_start_local = current_start_local - duration" in source
    assert "previous_end_local = current_start_local" in source
    assert "confronto con finestra equivalente precedente" in source


def test_multi_day_moment_cleanup_removes_time_of_day_hooks() -> None:
    source = Path("app/features/summary/services/channel_summary_service.py").read_text()
    assert "if multi_day:" in source
    assert "di prima mattina" in source
    assert "verso mezzogiorno" in source
    assert "in serata" in source


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


def test_trend_wording_oggi_ieri_is_natural_without_explicit_range() -> None:
    pytest.importorskip("aiosqlite")
    from app.features.summary.services.channel_summary_service import ChannelSummaryService
    from app.features.barcello.services.barcello_service import BarcelloResult

    svc = ChannelSummaryService(database=None, bot=None, summary_service=None, barcello_service=None)
    current = BarcelloResult(score=72, color="verde", trend="up", reasons=[], metrics={"negativity_hits": 2, "positive_hits": 8})
    previous = BarcelloResult(score=68, color="giallo", trend="down", reasons=[], metrics={"negativity_hits": 4, "positive_hits": 5})

    today = svc._build_trend_vs_previous_equivalent(
        bar_current=current,
        bar_previous=previous,
        current_start_local=datetime(2026, 3, 11, 0, 0),
        current_end_local=datetime(2026, 3, 11, 12, 0),
        period_label="oggi",
    )
    yesterday = svc._build_trend_vs_previous_equivalent(
        bar_current=current,
        bar_previous=previous,
        current_start_local=datetime(2026, 3, 10, 0, 0),
        current_end_local=datetime(2026, 3, 10, 23, 59),
        period_label="ieri",
    )

    assert "→" not in today
    assert "→" not in yesterday
    assert "rispetto a ieri" in today
    assert "rispetto al giorno precedente" in yesterday


def test_trend_wording_ultimi_keeps_explicit_previous_window() -> None:
    pytest.importorskip("aiosqlite")
    from app.features.summary.services.channel_summary_service import ChannelSummaryService
    from app.features.barcello.services.barcello_service import BarcelloResult

    svc = ChannelSummaryService(database=None, bot=None, summary_service=None, barcello_service=None)
    current = BarcelloResult(score=45, color="giallo", trend="flat", reasons=[], metrics={"negativity_hits": 5, "positive_hits": 3})
    previous = BarcelloResult(score=50, color="verde", trend="up", reasons=[], metrics={"negativity_hits": 2, "positive_hits": 3})

    trend = svc._build_trend_vs_previous_equivalent(
        bar_current=current,
        bar_previous=previous,
        current_start_local=datetime(2026, 3, 11, 0, 0),
        current_end_local=datetime(2026, 3, 11, 6, 0),
        period_label="ultimi",
    )

    assert "→" in trend
    assert "rispetto a" in trend
