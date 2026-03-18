from pathlib import Path


def test_root_namespaces_include_moderazione_and_not_top_level_inattivi() -> None:
    source = Path("app/plugins/commands.py").read_text()

    assert 'app_commands.Group(name="bm"' in source
    assert 'app_commands.Group(name="moderazione"' in source
    assert 'app_commands.Group(name="inattivi"' in source


def test_moderazione_registers_inattivi_and_utenti_subgroups() -> None:
    source = Path("app/plugins/commands.py").read_text()

    assert 'app_commands.Group(name="inattivi"' in source
    assert 'register_inattivi(inattivi_group, ctx)' in source
    assert 'register_moderazione_utenti(moderazione_group, ctx)' in source
