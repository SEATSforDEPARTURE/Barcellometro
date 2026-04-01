from pathlib import Path


def test_ai_model_choices_include_campaign_and_audio_tasks() -> None:
    source = Path("app/plugins/commands_modular/admin.py").read_text()
    assert 'app_commands.Choice(name="campaign_editorial", value="campaign_editorial")' in source
    assert 'app_commands.Choice(name="campaign_prompt", value="campaign_prompt")' in source
    assert 'app_commands.Choice(name="transcription", value="transcription")' in source
    assert 'app_commands.Choice(name="translation", value="translation")' in source
    assert 'app_commands.Choice(name="climate_analysis", value="climate_analysis")' in source


def test_ai_commands_are_registered_under_canonical_ai_namespace() -> None:
    source = Path("app/plugins/commands_modular/admin.py").read_text()
    assert 'def register_ai(ai_group: app_commands.Group, ctx: CommandContext) -> None:' in source
    assert '@ai_group.command(name="on"' in source
    assert '@ai_group.command(name="off"' in source
    assert '@ai_group.command(name="status"' in source
    assert '@ai_group.command(name="model_set"' in source
    assert '@ai_group.command(name="model_show"' in source
    assert '@ai_group.command(name="model_reset"' in source
    assert '@ai_group.command(name="fallback_set"' in source
    assert '@ai_group.command(name="fallback_show"' in source
    assert '@ai_group.command(name="fallback_reset"' in source
    assert '@ai_group.command(name="run"' in source
    assert 'check_permission(interaction, "ai.model_set", ctx)' in source
    assert 'check_permission(interaction, "admin.ai.model_set", ctx)' not in source


def test_legacy_ai_command_names_are_removed() -> None:
    source = Path("app/plugins/commands_modular/admin.py").read_text()
    assert '@ai_group.command(name="model"' not in source
    assert '@ai_group.command(name="fallback-model"' not in source
    assert '@ai_group.command(name="test"' not in source


def test_ai_model_autocomplete_is_configured_on_model_commands() -> None:
    source = Path("app/plugins/commands_modular/admin.py").read_text()
    assert 'async def _autocomplete_ai_model(' in source
    assert 'build_model_autocomplete_choices(task_value, current)' in source
    assert source.count('@app_commands.autocomplete(model=_autocomplete_ai_model)') >= 2
