from pathlib import Path
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import app.plugins.commands_modular.moderazione_utenti as moderazione_utenti_module

import discord

from app.plugins.commands_modular.greetings import register_greetings
from app.plugins.commands_modular.moderazione_utenti import register_moderazione_utenti


def test_commands_register_mod_users_and_top_level_greetings_namespace() -> None:
    source = Path("app/plugins/commands.py").read_text()
    greetings = Path("app/plugins/commands_modular/greetings.py").read_text()
    modular = Path("app/plugins/commands_modular/moderazione_utenti.py").read_text()

    assert "register_moderazione_utenti" in source
    assert 'app_commands.Group(name="greetings"' in source
    assert "register_greetings(greetings_group, ctx)" in source
    assert 'name="users"' in modular
    assert 'description="Moderation actions for users"' in modular
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
    assert '@users_group.command(name="unban"' in modular
    assert '@users_group.command(name="tempban"' in modular
    assert '@users_group.command(name="tempban_list"' in modular
    assert 'name="grace"' in modular
    assert '@users_group.command(name="grace_list"' in modular
    assert 'description="Revoke an active ban for a user."' in modular
    assert 'description="Remove a user from the server."' in modular
    assert 'description="List recent user removals."' in modular


def test_legacy_mod_channel_namespace_is_removed() -> None:
    source = Path("app/plugins/commands_modular/moderazione_utenti.py").read_text()
    greetings = Path("app/plugins/commands_modular/greetings.py").read_text()
    commands_source = Path("app/plugins/commands.py").read_text()
    docs_source = Path("docs/command_tree_report.md").read_text()

    assert 'app_commands.Group(name="channel"' not in source
    assert "mod channel" not in source
    assert "moderazione channel" not in source
    assert "mod channel" not in greetings
    assert "moderazione channel" not in greetings
    assert 'app_commands.Group(name="channel"' not in commands_source
    assert "| `mod` | `channel` |" not in docs_source
    assert "| `greetings` | `—` | `template_set` |" not in docs_source
    assert "| `greetings` | `—` | `template_show` |" not in docs_source
    assert "| `greetings` | `—` | `template_reset` |" not in docs_source
    assert (
        "| `greetings` | `backfill` | `on` | Enable greetings timeline backfill. |"
        in docs_source
    )
    assert (
        "| `greetings` | `backfill` | `off` | Disable greetings timeline backfill. |"
        in docs_source
    )
    assert (
        "| `greetings` | `backfill` | `status` | Show greetings timeline backfill status. |"
        in docs_source
    )
    assert (
        "| `greetings` | `backfill` | `run` | Run greetings timeline backfill now. |"
        in docs_source
    )
    assert (
        "| `mod` | `users` | `unban` | Revoke an active ban for a user. |"
        in docs_source
    )


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


def _find_command(group: discord.app_commands.Group, *names: str):
    current = group
    for name in names[:-1]:
        current = next(
            cmd
            for cmd in current.commands
            if isinstance(cmd, discord.app_commands.Group) and cmd.name == name
        )
    return next(cmd for cmd in current.commands if cmd.name == names[-1])


def test_mod_users_unban_executes_discord_unban_and_clears_backend_state(
    monkeypatch,
) -> None:
    async def _run() -> None:
        send_standard_response = AsyncMock()
        monkeypatch.setattr(
            moderazione_utenti_module, "send_standard_response", send_standard_response
        )
        monkeypatch.setattr(
            moderazione_utenti_module, "check_permission", AsyncMock(return_value=True)
        )

        database = SimpleNamespace(clear_user_ban_state=AsyncMock())
        member_flow_notifications = SimpleNamespace(
            log_action=AsyncMock(
                return_value={"canonical_written": True, "canonical_visible": False}
            ),
            send_notification=AsyncMock(),
            forget_departure_action=Mock(),
        )
        ctx = SimpleNamespace(
            database=database,
            footer=None,
            member_flow_notifications=member_flow_notifications,
            barcello_service=None,
        )
        mod_group = discord.app_commands.Group(name="mod", description="mod")
        register_moderazione_utenti(mod_group, ctx)
        command = _find_command(mod_group, "users", "unban")

        guild = SimpleNamespace(id=1, unban=AsyncMock())
        target_user = SimpleNamespace(id=42, mention="<@42>", name="Dormiente")
        moderator = SimpleNamespace(id=9)
        interaction = SimpleNamespace(
            guild=guild,
            guild_id=1,
            user=moderator,
            command=SimpleNamespace(qualified_name="mod users unban"),
        )

        await command.callback(interaction, target_user)

        guild.unban.assert_awaited_once_with(target_user, reason="Revoca ban manuale")
        database.clear_user_ban_state.assert_awaited_once_with("1", "42")
        member_flow_notifications.forget_departure_action.assert_called_once_with(
            "1", "42"
        )
        member_flow_notifications.log_action.assert_awaited_once()
        notify_kwargs = member_flow_notifications.log_action.await_args.kwargs
        assert notify_kwargs["action_type"] == "unban"
        assert notify_kwargs["reason"] == "Revoca ban manuale"
        assert notify_kwargs["metadata"]["source"] == "moderazione_utenti"
        send_standard_response.assert_awaited_once()
        response_kwargs = send_standard_response.await_args.kwargs
        assert response_kwargs["subcommand_path"] == "moderazione users unban"
        assert response_kwargs["kind"] == "success"
        assert ("result", "ban revocato") in response_kwargs["lines"]

    asyncio.run(_run())


def test_mod_users_unban_handles_unknown_ban_without_crashing(
    monkeypatch, caplog
) -> None:
    async def _run() -> None:
        send_standard_response = AsyncMock()
        monkeypatch.setattr(
            moderazione_utenti_module, "send_standard_response", send_standard_response
        )
        monkeypatch.setattr(
            moderazione_utenti_module, "check_permission", AsyncMock(return_value=True)
        )

        database = SimpleNamespace(clear_user_ban_state=AsyncMock())
        member_flow_notifications = SimpleNamespace(
            log_action=AsyncMock(
                return_value={"canonical_written": True, "canonical_visible": False}
            ),
            send_notification=AsyncMock(),
            forget_departure_action=Mock(),
        )
        ctx = SimpleNamespace(
            database=database,
            footer=None,
            member_flow_notifications=member_flow_notifications,
            barcello_service=None,
        )
        mod_group = discord.app_commands.Group(name="mod", description="mod")
        register_moderazione_utenti(mod_group, ctx)
        command = _find_command(mod_group, "users", "unban")

        not_found = discord.NotFound(
            Mock(status=404, reason="Not Found"),
            {"code": 10026, "message": "Unknown Ban"},
        )
        guild = SimpleNamespace(id=1, unban=AsyncMock(side_effect=not_found))
        target_user = SimpleNamespace(id=42, mention="<@42>", name="Dormiente")
        moderator = SimpleNamespace(id=9)
        interaction = SimpleNamespace(
            guild=guild,
            guild_id=1,
            user=moderator,
            command=SimpleNamespace(qualified_name="mod users unban"),
        )

        with caplog.at_level("INFO"):
            await command.callback(interaction, target_user)

        guild.unban.assert_awaited_once_with(target_user, reason="Revoca ban manuale")
        database.clear_user_ban_state.assert_awaited_once_with("1", "42")
        member_flow_notifications.forget_departure_action.assert_called_once_with(
            "1", "42"
        )
        member_flow_notifications.log_action.assert_awaited_once()
        notify_kwargs = member_flow_notifications.log_action.await_args.kwargs
        assert notify_kwargs["action_type"] == "unban"
        assert notify_kwargs["metadata"]["source"] == "moderazione_utenti"
        assert notify_kwargs["metadata"]["discord_unban_result"] == "discord_ban_missing"
        send_standard_response.assert_awaited_once()
        response_kwargs = send_standard_response.await_args.kwargs
        assert response_kwargs["subcommand_path"] == "moderazione users unban"
        assert response_kwargs["kind"] == "success"
        assert ("result", "nessun ban attivo trovato su Discord") in response_kwargs["lines"]
        assert ("sync", "stati locali riallineati") in response_kwargs["lines"]
        assert "discord ban already missing guild=1 user=42" in caplog.text

    asyncio.run(_run())
