from pathlib import Path
import asyncio

from tests._sqlite_stub import ensure_sqlite_stub

ensure_sqlite_stub()

from app.services.database import DatabaseService


def test_scheduler_processes_campaign_content_services() -> None:
    source = Path("app/services/message_scheduler.py").read_text()
    assert "process_due_services" in source


def test_db_has_campaign_content_tables_and_index() -> None:
    source = Path("app/services/database.py").read_text()
    assert "CREATE TABLE IF NOT EXISTS campaign_content_configs" in source
    assert "extras_json TEXT NULL" in source
    assert "idx_campaign_content_configs_due" in source
    assert "CREATE TABLE IF NOT EXISTS campaign_content_messages" in source
    assert "update_campaign_content_current_index" in source



def test_persistent_views_registration_uses_dynamic_campaign_views() -> None:
    source = Path("app/services/campaign_content_service.py").read_text()
    assert "Dynamic persistent views are re-created per message from DB metadata" in source
    assert "PersistentCampaignLauncherView" in source


def test_db_lists_next_recurring_campaign_content_runs() -> None:
    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()
        await db.create_campaign_content_config(
            guild_id="1",
            channel_id="10",
            service_type="NEWS",
            enabled=True,
            time_local="08:00",
            interval_minutes=60,
            embed_title=None,
            embed_color=None,
            sources_json="[]",
            categories_json="",
            extras_json="[]",
            next_run_at="2026-04-09T20:00:00+00:00",
        )
        await db.create_campaign_content_config(
            guild_id="1",
            channel_id="10",
            service_type="NEWS",
            enabled=True,
            time_local="08:00",
            interval_minutes=30,
            embed_title=None,
            embed_color=None,
            sources_json="[]",
            categories_json="",
            extras_json="[]",
            next_run_at="2026-04-09T18:00:00+00:00",
        )
        rows = await db.list_campaign_content_recurring_schedule_runs(
            guild_id="1",
            channel_id="10",
            service_type="NEWS",
            after_iso="2026-04-09T19:10:00+00:00",
        )
        assert rows
        assert rows[0]["next_effective_run_at"].startswith("2026-04-09T19:30:00")
        await db.close()

    asyncio.run(_run())
