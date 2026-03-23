from pathlib import Path


def test_editorial_commands_are_under_servizi_subgroup() -> None:
    source = Path("app/plugins/commands_modular/messaggi.py").read_text()

    assert 'news_group = app_commands.Group(name="news", description="News campaign controls")' in source
    assert 'weather_group = app_commands.Group(name="weather", description="Weather campaign controls")' in source
    assert 'horoscope_group = app_commands.Group(name="horoscope", description="Horoscope campaign controls")' in source
    assert "for group in (quiet_group, cap_group, custom_group, news_group, weather_group, horoscope_group):" in source
    assert "add_group_once(campaigns_group, group, logger)" in source


def test_editorial_commands_are_not_direct_children_of_campaigns() -> None:
    source = Path("app/plugins/commands_modular/messaggi.py").read_text()

    forbidden = [
        '@campaigns_group.command(name="news"',
        '@campaigns_group.command(name="weather"',
        '@campaigns_group.command(name="horoscope"',
        '@campaigns_group.command(name="schedule_add"',
        '@campaigns_group.command(name="run"',
    ]
    for pattern in forbidden:
        assert pattern not in source


def test_existing_campaigns_commands_and_prompt_and_insights_groups_are_kept() -> None:
    messaggi_source = Path("app/plugins/commands_modular/messaggi.py").read_text()
    triggers_source = Path("app/plugins/commands_modular/triggers.py").read_text()

    for cmd in ["on", "off", "status"]:
        assert f'@campaigns_group.command(name="{cmd}"' in messaggi_source
    for cmd in ["on", "off", "status", "schedule_add", "schedule_list", "schedule_show", "schedule_remove", "run", "schedule_edit"]:
        assert f'@custom_group.command(name="{cmd}"' in messaggi_source

    assert 'add_group_once(campaigns_group, prompt_group, logger)' in triggers_source
    assert 'add_group_once(campaigns_group, insights_group, logger)' in triggers_source

    for cmd in ["on", "off", "status", "template_set", "template_show", "template_reset"]:
        assert f'@insights_group.command(name="{cmd}"' in triggers_source

    for group_name in ["news", "weather", "horoscope"]:
        for cmd in ["on", "off", "status", "schedule_add", "schedule_edit", "schedule_remove", "schedule_show", "schedule_list", "run"]:
            assert f'@{group_name}_group.command(name="{cmd}"' in messaggi_source


def test_hardening_for_group_registration_is_present() -> None:
    source = Path("app/plugins/commands_modular/registration.py").read_text()

    assert "def count_child_commands(parent: app_commands.Group) -> int:" in source
    assert "Attempting to register subgroup" in source
    assert "Failed to register subgroup" in source
    assert "Failed to register command" in source


def test_scheduling_parameters_are_unified_to_publish_at_every() -> None:
    source = Path("app/plugins/commands_modular/messaggi.py").read_text()

    assert 'publish_at="First publication time (DD/MM/YYYY HH:MM)"' in source
    assert 'every="Repeat interval in minutes"' in source
    assert 'time_local="Ora invio (HH:MM)"' not in source
    assert 'interval_minutes="Intervallo in minuti"' not in source


def test_prompt_create_slash_exposes_publish_at_every() -> None:
    source = Path("app/plugins/commands_modular/triggers.py").read_text()

    assert 'publish_at="First publication time (DD/MM/YYYY HH:MM)"' in source
    assert 'every="Repeat interval in minutes"' in source
    assert 'prompt_text="Prompt text"' in source
    assert 'time_local: str | None = None' not in source
    assert 'interval_minutes: int | None = None' not in source
