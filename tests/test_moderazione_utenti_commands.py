from pathlib import Path


def test_commands_register_new_mod_namespace_and_channel_user_subgroups() -> None:
    source = Path("app/plugins/commands.py").read_text()
    modular = Path("app/plugins/commands_modular/moderazione_utenti.py").read_text()

    assert "register_moderazione_utenti" in source
    assert 'app_commands.Group(name="channel"' in modular
    assert 'app_commands.Group(name="users"' in modular
    assert '@channel_group.command(name="notify_set"' in modular
    assert '@channel_group.command(name="notify_show"' in modular
    assert '@channel_group.command(name="notify_reset"' in modular
    assert '@channel_group.command(name="template_set"' in modular
    assert '@channel_group.command(name="template_show"' in modular
    assert '@channel_group.command(name="template_reset"' in modular
    assert '@channel_group.command(name="user_card_set"' in modular
    assert '@channel_group.command(name="user_card_show"' in modular
    assert '@channel_group.command(name="user_card_reset"' in modular
    assert '@users_group.command(name="kick"' in modular
    assert '@users_group.command(name="kick_list"' in modular
    assert '@users_group.command(name="ban"' in modular
    assert '@users_group.command(name="ban_list"' in modular
    assert '@users_group.command(name="tempban"' in modular
    assert '@users_group.command(name="tempban_list"' in modular
    assert '@users_group.command(name="grace"' in modular
    assert '@users_group.command(name="grace_list"' in modular


def test_legacy_moderation_namespace_commands_are_removed() -> None:
    source = Path("app/plugins/commands_modular/moderazione_utenti.py").read_text()

    assert 'app_commands.Group(name="utenti"' not in source
    assert '@moderazione_group.command(name="tempban_users"' not in source
    assert '@moderazione_group.command(name="grace_users"' not in source
    assert '@moderazione_group.command(name="banned_users"' not in source
    assert '@moderazione_group.command(name="kicked_users"' not in source


def test_legacy_inactivity_commands_are_removed_from_namespace() -> None:
    source = Path("app/plugins/commands_modular/inattivi.py").read_text()

    assert 'name="auto_on"' not in source
    assert 'name="auto_off"' not in source
    assert 'name="set_grace"' not in source
    assert 'name="set_ban_days"' not in source
    assert 'name="exclude_role_add"' not in source
    assert 'name="exclude_role_remove"' not in source
    assert 'name="role_del"' not in source
