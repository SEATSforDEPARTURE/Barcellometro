from pathlib import Path


def test_root_namespace_is_bm_and_inattivi_top_level() -> None:
    source = Path("app/plugins/commands.py").read_text()

    assert 'app_commands.Group(name="bm"' in source
    assert 'add_group_once(bm_group, inattivi_group, logger)' not in source
    assert 'root_commands: list[app_commands.Command | app_commands.Group] = [' in source
    assert '        bm_group,' in source
    assert '        inattivi_group,' in source


def test_status_subcommand_uses_bm_name_and_permission() -> None:
    source = Path("app/plugins/commands_modular/status.py").read_text()

    assert '@status_group.command(name="bm"' in source
    assert 'check_permission(interaction, "status.bm", ctx)' in source
