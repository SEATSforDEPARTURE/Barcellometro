from pathlib import Path


def test_ai_model_choices_include_campaign_tasks() -> None:
    source = Path("app/plugins/commands_modular/admin.py").read_text()
    assert 'app_commands.Choice(name="campaign_editorial", value="campaign_editorial")' in source
    assert 'app_commands.Choice(name="campaign_prompt", value="campaign_prompt")' in source


def test_ai_fallback_model_command_is_registered_and_updates_fallback() -> None:
    source = Path("app/plugins/commands_modular/admin.py").read_text()
    assert '@bm_group.command(name="ai-fallback-model"' in source
    assert 'await ctx.ai.set_fallback_model(task.value, model)' in source


def test_ai_status_and_ai_test_commands_are_registered() -> None:
    source = Path("app/plugins/commands_modular/admin.py").read_text()
    assert '@bm_group.command(name="ai-status"' in source
    assert 'status = ctx.ai.status()' in source
    assert '@bm_group.command(name="ai-test"' in source
    assert 'result = await ctx.ai.run_test(task.value, prompt, use_web=web_value)' in source
