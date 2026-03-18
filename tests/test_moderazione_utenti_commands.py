from pathlib import Path


def test_commands_register_new_moderazione_utenti_namespace_and_top_level_lists() -> None:
    source = Path("app/plugins/commands.py").read_text()
    modular = Path("app/plugins/commands_modular/moderazione_utenti.py").read_text()

    assert "register_moderazione_utenti" in source
    assert 'app_commands.Group(name="utenti"' in modular
    assert '@utenti_group.command(name="channel_notify_set"' in modular
    assert '@utenti_group.command(name="tesserino"' in modular
    assert '@utenti_group.command(name="template_show"' in modular
    assert '@utenti_group.command(name="template_inactivity_reason"' in modular
    assert '@utenti_group.command(name="template_kick_reason"' in modular
    assert '@utenti_group.command(name="template_ban_reason"' in modular
    assert '@utenti_group.command(name="template_tempban_reason"' in modular
    assert '@utenti_group.command(name="template_grace_reason"' in modular
    assert '@utenti_group.command(name="kick"' in modular
    assert '@utenti_group.command(name="ban"' in modular
    assert '@utenti_group.command(name="tempban"' in modular
    assert '@utenti_group.command(name="grace"' in modular
    assert '@moderazione_group.command(name="tempban_users"' in modular
    assert '@moderazione_group.command(name="grace_users"' in modular
    assert '@moderazione_group.command(name="banned_users"' in modular
    assert '@moderazione_group.command(name="kicked_users"' in modular


def test_legacy_inattivi_commands_are_removed_from_namespace() -> None:
    source = Path("app/plugins/commands_modular/inattivi.py").read_text()

    assert 'name="set_atrio"' not in source
    assert 'name="template_atrio_set"' not in source
    assert 'name="template_show"' not in source
    assert 'name="grace_users"' not in source
    assert 'name="banned_users"' not in source
    assert 'name="template_kick_set"' not in source
