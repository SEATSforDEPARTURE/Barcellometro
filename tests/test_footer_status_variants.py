from pathlib import Path

from app.plugins.commands_modular.admin import _service_section


def test_footer_status_groups_campaign_sections_separately() -> None:
    assert _service_section("campagne_notizie") == 1
    assert _service_section("campagne_meteo") == 1
    assert _service_section("campagne_oroscopo") == 1
    assert _service_section("campagne_prompt") == 2
    assert _service_section("campagne_timer") == 3
    assert _service_section("audio_notes") == 0


def test_footer_status_source_uses_variants_and_excludes_legacy_campagne() -> None:
    source = Path("app/plugins/commands_modular/admin.py").read_text()
    assert "get_all_service_footer_variants" in source
    assert "Campagne servizi editoriali" in source
    assert "Campagne prompt" in source
    assert "Campagne timer" in source
    assert 'service_name="campagne"' not in source


def test_message_scheduler_uses_prompt_vs_timer_footer_service() -> None:
    source = Path("app/services/message_scheduler.py").read_text()
    assert 'footer_service = "campagne_prompt" if campaign_type == "AI_PROMPT" else "campagne_timer"' in source
