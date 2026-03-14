from pathlib import Path


def test_root_namespaces_include_bm_attivita_qna_insights_campagne_and_not_inattivi() -> None:
    source = Path("app/plugins/commands.py").read_text()

    assert 'app_commands.Group(name="bm"' in source
    assert 'app_commands.Group(name="inattivi"' not in source
    assert 'app_commands.Group(name="qna"' in source
    assert 'app_commands.Group(name="insights"' in source
    assert 'app_commands.Group(name="campagne"' in source
    assert 'add_group_once(bm_group, qna_group, logger)' not in source
    assert 'add_group_once(bm_group, insights_group, logger)' not in source


def test_calibrate_is_under_bm_barcello_and_not_direct_on_bm() -> None:
    admin_source = Path("app/plugins/commands_modular/admin.py").read_text()
    triggers_source = Path("app/plugins/commands_modular/triggers.py").read_text()

    assert '@bm_group.command(name="calibrate"' not in admin_source
    assert '@barcello_group.command(name="calibrate"' in triggers_source


def test_status_subcommand_uses_bm_name_and_permission() -> None:
    source = Path("app/plugins/commands_modular/status.py").read_text()

    assert '@status_group.command(name="bm"' in source
    assert 'check_permission(interaction, "status.bm", ctx)' in source


def test_ask_alias_removed_and_domanda_guarded() -> None:
    source = Path("app/plugins/commands_modular/ask.py").read_text()

    assert 'name="ask"' not in source
    assert 'Alias di /ask' not in source
    assert '@tree.command(name="domanda"' in source
    assert 'check_permission(interaction, "qna.domanda", ctx)' in source


def test_triggers_commands_are_guarded_through_central_check() -> None:
    source = Path("app/plugins/commands_modular/triggers.py").read_text()

    assert 'def _command_permission_key' in source
    assert 'return await check_permission(interaction, _command_permission_key(interaction), ctx)' in source
    assert 'resolve_profile(' not in source


def test_inattivi_registered_as_attivita_subgroup() -> None:
    source = Path("app/plugins/commands_modular/attivita.py").read_text()

    assert "app_commands.Group(name=\"inattivi\"" in source
    assert "attivita_group.add_command(inattivi_group)" in source
    assert "register_inattivi(inattivi_group, ctx)" in source
