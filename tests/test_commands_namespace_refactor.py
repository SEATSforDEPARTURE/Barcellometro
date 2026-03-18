from pathlib import Path


def test_root_namespaces_include_mod_and_inactivity() -> None:
    source = Path("app/plugins/commands.py").read_text()

    assert 'app_commands.Group(name="bm"' in source
    assert 'app_commands.Group(name="mod"' in source
    assert 'app_commands.Group(name="inactivity"' in source
    assert 'app_commands.Group(name="moderazione"' not in source
    assert 'app_commands.Group(name="inattivi"' not in source


def test_mod_and_inactivity_register_independently() -> None:
    source = Path("app/plugins/commands.py").read_text()

    assert 'register_inattivi(inactivity_group, ctx)' in source
    assert 'register_moderazione_utenti(mod_group, ctx)' in source
