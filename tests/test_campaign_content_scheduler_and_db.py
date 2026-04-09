from pathlib import Path


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
