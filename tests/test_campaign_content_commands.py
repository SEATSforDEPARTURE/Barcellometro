from pathlib import Path


def test_editorial_commands_are_under_servizi_subgroup() -> None:
    source = Path("app/plugins/commands_modular/messaggi.py").read_text()

    assert 'servizi_group = app_commands.Group(name="servizi", description="Servizi editoriali campagne")' in source
    assert 'add_group_once(campagne_group, servizi_group, logger)' in source

    for cmd in ["notizie", "meteo", "oroscopo", "lista", "test", "on", "off", "delete"]:
        assert f'@servizi_group.command(name="{cmd}"' in source


def test_editorial_commands_are_not_direct_children_of_campagne() -> None:
    source = Path("app/plugins/commands_modular/messaggi.py").read_text()

    forbidden = [
        '@campagne_group.command(name="notizie"',
        '@campagne_group.command(name="meteo"',
        '@campagne_group.command(name="oroscopo"',
        '@campagne_group.command(name="servizi_lista"',
        '@campagne_group.command(name="servizi_test"',
        '@campagne_group.command(name="servizi_on"',
        '@campagne_group.command(name="servizi_off"',
        '@campagne_group.command(name="servizi_delete"',
    ]
    for pattern in forbidden:
        assert pattern not in source


def test_existing_campagne_commands_and_prompt_group_are_kept() -> None:
    messaggi_source = Path("app/plugins/commands_modular/messaggi.py").read_text()
    triggers_source = Path("app/plugins/commands_modular/triggers.py").read_text()

    for cmd in ["aggiungi", "lista", "test", "pausa", "riprendi"]:
        assert f'@campagne_group.command(name="{cmd}"' in messaggi_source

    assert 'add_group_once(campagne_group, prompt_group, logger)' in triggers_source


def test_hardening_for_group_registration_is_present() -> None:
    source = Path("app/plugins/commands_modular/command_helpers.py").read_text()

    assert "def count_child_commands(parent: app_commands.Group) -> int:" in source
    assert "Attempting to register subgroup" in source
    assert "Failed to register subgroup" in source
    assert "Failed to register command" in source
