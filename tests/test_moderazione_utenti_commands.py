from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import discord

from app.plugins.commands_modular.greetings import register_greetings


def test_commands_register_mod_users_and_top_level_greetings_namespace() -> None:
    source = Path("app/plugins/commands.py").read_text()
    greetings = Path("app/plugins/commands_modular/greetings.py").read_text()
    modular = Path("app/plugins/commands_modular/moderazione_utenti.py").read_text()

    assert "register_moderazione_utenti" in source
    assert 'app_commands.Group(name="greetings"' in source
    assert 'register_greetings(greetings_group, ctx)' in source
    assert 'app_commands.Group(name="users"' in modular
    assert 'app_commands.Group(name="backfill"' in greetings
    assert '@backfill_group.command(name="on"' in greetings
    assert '@backfill_group.command(name="off"' in greetings
    assert '@backfill_group.command(name="status"' in greetings
    assert '@backfill_group.command(name="run"' in greetings
    assert '@greetings_group.command(name="on"' in greetings
    assert '@greetings_group.command(name="off"' in greetings
    assert '@greetings_group.command(name="status"' in greetings
    assert '@greetings_group.command(name="notify_set"' in greetings
    assert '@greetings_group.command(name="notify_show"' in greetings
    assert '@greetings_group.command(name="notify_reset"' in greetings
    assert '@greetings_group.command(name="template_set"' not in greetings
    assert '@greetings_group.command(name="template_show"' not in greetings
    assert '@greetings_group.command(name="template_reset"' not in greetings
    assert '@greetings_group.command(name="user_card_set"' in greetings
    assert '@greetings_group.command(name="user_card_show"' in greetings
    assert '@greetings_group.command(name="user_card_reset"' in greetings
    assert '@greetings_group.command(name="preview"' not in greetings
    assert '@users_group.command(name="kick"' in modular
    assert '@users_group.command(name="kick_list"' in modular
    assert '@users_group.command(name="ban"' in modular
    assert '@users_group.command(name="ban_list"' in modular
    assert '@users_group.command(name="tempban"' in modular
    assert '@users_group.command(name="tempban_list"' in modular
    assert '@users_group.command(name="grace"' in modular
    assert '@users_group.command(name="grace_list"' in modular
    assert 'description="Remove a user from the server."' in modular
    assert 'description="List recent user removals."' in modular


def test_legacy_mod_channel_namespace_is_removed() -> None:
    source = Path("app/plugins/commands_modular/moderazione_utenti.py").read_text()
    greetings = Path("app/plugins/commands_modular/greetings.py").read_text()
    commands_source = Path("app/plugins/commands.py").read_text()
    docs_source = Path("docs/command_tree_report.md").read_text()

    assert 'app_commands.Group(name="channel"' not in source
    assert 'mod channel' not in source
    assert 'moderazione channel' not in source
    assert 'mod channel' not in greetings
    assert 'moderazione channel' not in greetings
    assert 'app_commands.Group(name="channel"' not in commands_source
    assert '| `mod` | `channel` |' not in docs_source
    assert "| `greetings` | `—` | `template_set` |" not in docs_source
    assert "| `greetings` | `—` | `template_show` |" not in docs_source
    assert "| `greetings` | `—` | `template_reset` |" not in docs_source
    assert "| `greetings` | `backfill` | `on` | Enable greetings timeline backfill. |" in docs_source
    assert "| `greetings` | `backfill` | `off` | Disable greetings timeline backfill. |" in docs_source
    assert "| `greetings` | `backfill` | `status` | Show greetings timeline backfill status. |" in docs_source
    assert "| `greetings` | `backfill` | `run` | Run greetings timeline backfill now. |" in docs_source


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


def test_greetings_tree_has_no_preview_command() -> None:
    group = discord.app_commands.Group(name="greetings", description="x")
    ctx = SimpleNamespace(database=Mock(), footer=None)

    register_greetings(group, ctx)

    names = {command.name for command in group.commands}
    assert names == {
        "backfill",
        "on",
        "off",
        "status",
        "notify_set",
        "notify_show",
        "notify_reset",
        "user_card_set",
        "user_card_show",
        "user_card_reset",
    }
    assert "preview" not in names
