from pathlib import Path


def test_root_namespaces_include_mod_and_inactivity() -> None:
    source = Path("app/plugins/commands.py").read_text()

    assert 'app_commands.Group(name="admin"' in source
    assert 'app_commands.Group(name="mod"' in source
    assert 'app_commands.Group(name="inactivity"' in source
    assert 'app_commands.Group(name="moderazione"' not in source
    assert 'app_commands.Group(name="inattivi"' not in source


def test_mod_and_inactivity_register_independently() -> None:
    source = Path("app/plugins/commands.py").read_text()

    assert 'register_inattivi(inactivity_group, ctx)' in source
    assert 'register_moderazione_utenti(mod_group, ctx)' in source


def test_admin_group_is_the_registered_root_namespace() -> None:
    source = Path("app/plugins/commands.py").read_text()

    assert 'admin_group = app_commands.Group(name="admin", description="Barcellometro control commands")' in source
    assert 'root_commands: list[app_commands.Command | app_commands.Group] = [' in source
    assert '        admin_group,' in source


def test_campaign_and_trigger_outputs_use_admin_namespace() -> None:
    triggers_source = Path("app/plugins/commands_modular/triggers.py").read_text()
    messaggi_source = Path("app/plugins/commands_modular/messaggi.py").read_text()

    assert 'top_level="admin"' in triggers_source
    assert 'top_level="admin"' in messaggi_source
    assert 'top_level="bm"' not in triggers_source
    assert 'top_level="bm"' not in messaggi_source
