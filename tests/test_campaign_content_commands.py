from pathlib import Path


def test_editorial_commands_are_split_by_service_subgroups() -> None:
    source = Path("app/plugins/commands_modular/messaggi.py").read_text()

    for group_name, description in [
        ("news", "News campaign controls"),
        ("weather", "Weather campaign controls"),
        ("horoscope", "Horoscope campaign controls"),
    ]:
        assert f'app_commands.Group(name="{group_name}", description="{description}")' in source
        for cmd in ["on", "off", "status", "config_set", "config_show", "config_reset", "run"]:
            assert f'@{group_name}_group.command(name="{cmd}"' in source


def test_legacy_editorial_service_namespace_is_removed() -> None:
    source = Path("app/plugins/commands_modular/messaggi.py").read_text()

    forbidden = [
        'servizi_group = app_commands.Group(name="servizi"',
        '@servizi_group.command(name="notizie"',
        '@servizi_group.command(name="meteo"',
        '@servizi_group.command(name="oroscopo"',
        '@campagne_group.command(name="aggiungi"',
        '@campagne_group.command(name="lista"',
        '@campagne_group.command(name="test"',
        '@campagne_group.command(name="pausa"',
        '@campagne_group.command(name="riprendi"',
    ]
    for pattern in forbidden:
        assert pattern not in source


def test_custom_and_prompt_groups_are_registered_under_campagne() -> None:
    messaggi_source = Path("app/plugins/commands_modular/messaggi.py").read_text()
    triggers_source = Path("app/plugins/commands_modular/triggers.py").read_text()

    assert 'custom_group = app_commands.Group(name="custom", description="Custom campaign entries")' in messaggi_source
    assert 'for group in (quiet_group, cap_group, custom_group, news_group, weather_group, horoscope_group):' in messaggi_source
    for cmd in ["on", "off", "status", "entry_add", "entry_list", "entry_show", "entry_remove", "entry_run", "entry_edit"]:
        assert f'@custom_group.command(name="{cmd}"' in messaggi_source

    assert 'prompt_group = app_commands.Group(name="prompt", description="Prompt campaign controls")' in triggers_source
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
