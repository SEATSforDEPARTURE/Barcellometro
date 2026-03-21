import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

import app.plugins.commands_modular.greetings as greetings_module
from app.plugins.commands_modular.greetings import register_greetings
from app.services.database import DatabaseService


def test_commands_register_mod_users_and_top_level_greetings_namespace() -> None:
    source = Path("app/plugins/commands.py").read_text()
    greetings = Path("app/plugins/commands_modular/greetings.py").read_text()
    modular = Path("app/plugins/commands_modular/moderazione_utenti.py").read_text()

    assert "register_moderazione_utenti" in source
    assert 'app_commands.Group(name="greetings"' in source
    assert 'register_greetings(greetings_group, ctx)' in source
    assert 'app_commands.Group(name="users"' in modular
    assert '@greetings_group.command(name="on"' in greetings
    assert '@greetings_group.command(name="off"' in greetings
    assert '@greetings_group.command(name="status"' in greetings
    assert '@greetings_group.command(name="notify_set"' in greetings
    assert '@greetings_group.command(name="notify_show"' in greetings
    assert '@greetings_group.command(name="notify_reset"' in greetings
    assert '@greetings_group.command(name="template_set"' in greetings
    assert '@greetings_group.command(name="template_show"' in greetings
    assert '@greetings_group.command(name="template_reset"' in greetings
    assert '@greetings_group.command(name="user_card_set"' in greetings
    assert '@greetings_group.command(name="user_card_show"' in greetings
    assert '@greetings_group.command(name="user_card_reset"' in greetings
    assert '@greetings_group.command(name="preview"' in greetings
    assert '@users_group.command(name="kick"' in modular
    assert '@users_group.command(name="kick_list"' in modular
    assert '@users_group.command(name="ban"' in modular
    assert '@users_group.command(name="ban_list"' in modular
    assert '@users_group.command(name="tempban"' in modular
    assert '@users_group.command(name="tempban_list"' in modular
    assert '@users_group.command(name="grace"' in modular
    assert '@users_group.command(name="grace_list"' in modular


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


def test_greetings_preview_command_renders_for_selected_type() -> None:
    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()
        await db.upsert_inactivity_config("1", template_kick_reason="Kick notice for {display_name} by {moderator}.")

        group = discord.app_commands.Group(name="greetings", description="x")
        ctx = SimpleNamespace(
            database=db,
            footer=None,
            entitlements=SimpleNamespace(resolve_profile=AsyncMock(return_value="mod")),
        )
        old_permission = greetings_module.check_permission
        greetings_module.check_permission = AsyncMock(return_value=True)
        try:
            register_greetings(group, ctx)
            preview_cmd = next(command for command in group.commands if command.name == "preview")

            response = Mock()
            response.send_message = AsyncMock()
            response.is_done = Mock(return_value=False)
            interaction = SimpleNamespace(
                guild_id=1,
                guild=SimpleNamespace(id=1, name="Barcellometro"),
                channel=SimpleNamespace(id=99),
                response=response,
                followup=SimpleNamespace(send=AsyncMock()),
                user=SimpleNamespace(
                    id=7,
                    name="Mod",
                    display_name="Moderator",
                    mention="<@7>",
                    guild_permissions=SimpleNamespace(administrator=True),
                ),
            )

            await preview_cmd.callback(interaction, type="kick")

            assert response.send_message.await_count == 1
            embed = response.send_message.await_args.kwargs["embed"]
            description = embed.description or ""
            assert "Kick" in description
            assert "Kick notice for New User by Moderator." in description
        finally:
            greetings_module.check_permission = old_permission
            await db.close()

    asyncio.run(_run())
