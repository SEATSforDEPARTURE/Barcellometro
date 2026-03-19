from pathlib import Path


def test_editorial_commands_are_under_servizi_subgroup() -> None:
    source = Path("app/plugins/commands_modular/messaggi.py").read_text()

    assert 'news_group = app_commands.Group(name="news", description="News campaign controls")' in source
    assert 'weather_group = app_commands.Group(name="weather", description="Weather campaign controls")' in source
    assert 'horoscope_group = app_commands.Group(name="horoscope", description="Horoscope campaign controls")' in source
    assert "for group in (quiet_group, cap_group, custom_group, news_group, weather_group, horoscope_group):" in source
    assert "add_group_once(campagne_group, group, logger)" in source


def test_editorial_commands_are_not_direct_children_of_campagne() -> None:
    source = Path("app/plugins/commands_modular/messaggi.py").read_text()

    forbidden = [
        '@campagne_group.command(name="news"',
        '@campagne_group.command(name="weather"',
        '@campagne_group.command(name="horoscope"',
        '@campagne_group.command(name="config_set"',
        '@campagne_group.command(name="run"',
    ]
    for pattern in forbidden:
        assert pattern not in source


def test_existing_campagne_commands_and_prompt_group_are_kept() -> None:
    messaggi_source = Path("app/plugins/commands_modular/messaggi.py").read_text()
    triggers_source = Path("app/plugins/commands_modular/triggers.py").read_text()

    for cmd in ["on", "off", "status"]:
        assert f'@campagne_group.command(name="{cmd}"' in messaggi_source
    for cmd in ["on", "off", "status", "entry_add", "entry_list", "entry_show", "entry_remove", "entry_run", "entry_edit"]:
        assert f'@custom_group.command(name="{cmd}"' in messaggi_source

    assert 'add_group_once(campagne_group, prompt_group, logger)' in triggers_source


def test_hardening_for_group_registration_is_present() -> None:
    source = Path("app/plugins/commands_modular/command_helpers.py").read_text()

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
    assert 'time_local: str | None = None' not in source
    assert 'interval_minutes: int | None = None' not in source
