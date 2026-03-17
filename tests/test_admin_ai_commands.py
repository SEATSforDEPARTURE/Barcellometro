from pathlib import Path


def test_ai_model_choices_include_campaign_and_audio_tasks() -> None:
    source = Path("app/plugins/commands_modular/admin.py").read_text()
    assert 'app_commands.Choice(name="campaign_editorial", value="campaign_editorial")' in source
    assert 'app_commands.Choice(name="campaign_prompt", value="campaign_prompt")' in source
    assert 'app_commands.Choice(name="transcription", value="transcription")' in source
    assert 'app_commands.Choice(name="translation", value="translation")' in source


def test_ai_commands_are_registered_under_ai_group_namespace() -> None:
    source = Path("app/plugins/commands_modular/admin.py").read_text()
    assert 'ai_group = app_commands.Group(name="ai", description="Gestione servizio AI")' in source
    assert "bm_group.add_command(ai_group)" in source
    assert '@ai_group.command(name="on"' in source
    assert '@ai_group.command(name="off"' in source
    assert '@ai_group.command(name="model"' in source
    assert '@ai_group.command(name="fallback-model"' in source
    assert '@ai_group.command(name="status"' in source
    assert '@ai_group.command(name="test"' in source


def test_legacy_ai_sibling_commands_are_removed() -> None:
    source = Path("app/plugins/commands_modular/admin.py").read_text()
    assert '@bm_group.command(name="ai-model"' not in source
    assert '@bm_group.command(name="ai-fallback-model"' not in source
    assert '@bm_group.command(name="ai-status"' not in source
    assert '@bm_group.command(name="ai-test"' not in source


def test_ai_model_autocomplete_is_configured_on_model_commands() -> None:
    source = Path("app/plugins/commands_modular/admin.py").read_text()
    assert "async def _autocomplete_ai_model(" in source
    assert "build_model_autocomplete_choices(task_value, current)" in source
    assert source.count("@app_commands.autocomplete(model=_autocomplete_ai_model)") >= 2
