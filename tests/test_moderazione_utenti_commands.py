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
    assert 'register_greetings(greetings_group, ctx, top_level="greetings", visual_top_level="greetings")' in source
    assert 'register_moderazione_utenti(' in modular
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
    assert 'app_commands.Group(name="user_card"' in greetings
    assert '@user_card_group.command(name="on"' in greetings
    assert '@user_card_group.command(name="off"' in greetings
    assert '@user_card_group.command(name="status"' in greetings
    assert '@greetings_group.command(name="preview"' not in greetings
    assert '@users_group.command(name="kick"' in modular
    assert '@users_group.command(name="kick_list"' in modular
    assert '@users_group.command(name="ban"' in modular
    assert '@users_group.command(name="ban_list"' in modular
    assert '@users_group.command(name="unban"' in modular
    assert '@users_group.command(name="untempban"' in modular
    assert '@users_group.command(name="tempban"' in modular
    assert '@users_group.command(name="tempban_list"' in modular
    assert 'name="grace"' in modular
    assert '@users_group.command(name="ungrace"' in modular
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


def test_users_alias_commands_are_registered_as_top_level_aliases() -> None:
    source = Path("app/plugins/commands.py").read_text()
    group = discord.app_commands.Group(name="users", description="x")
    ctx = SimpleNamespace(database=Mock(), footer=None, member_flow_notifications=None, barcello_service=None)
    aliases: list[discord.app_commands.Command] = []

    register_moderazione_utenti(group, ctx, alias_commands=aliases)

    assert 'user_alias_commands: list[app_commands.Command] = []' in source
    assert '*user_alias_commands,' in source
    assert [command.name for command in aliases] == ["kick", "ban", "unban", "tempban", "untempban", "grace", "ungrace"]


def test_greetings_tree_has_no_preview_command() -> None:
    group = discord.app_commands.Group(name="greetings", description="x")
    ctx = SimpleNamespace(database=Mock(), footer=None)

    register_greetings(group, ctx)

    names = {command.name for command in group.commands}
    assert names == {
        "backfill",
        "user_card",
        "on",
        "off",
        "status",
        "notify_set",
        "notify_show",
        "notify_reset",
    }
    assert "preview" not in names
    user_card = next(command for command in group.commands if isinstance(command, discord.app_commands.Group) and command.name == "user_card")
    assert {command.name for command in user_card.commands} == {"on", "off", "status"}


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
        users_group = discord.app_commands.Group(name="users", description="users")
        register_moderazione_utenti(users_group, ctx)
        command = _find_command(users_group, "unban")

        guild = SimpleNamespace(id=1, unban=AsyncMock())
        target_user = SimpleNamespace(id=42, mention="<@42>", name="Dormiente")
        moderator = SimpleNamespace(id=9)
        interaction = SimpleNamespace(
            guild=guild,
            guild_id=1,
            user=moderator,
            command=SimpleNamespace(qualified_name="users unban"),
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
        assert response_kwargs["top_level"] == "users"
        assert response_kwargs["visual_top_level"] == "users"
        assert response_kwargs["subcommand_path"] == "users unban"
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
        users_group = discord.app_commands.Group(name="users", description="users")
        register_moderazione_utenti(users_group, ctx)
        command = _find_command(users_group, "unban")

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
            command=SimpleNamespace(qualified_name="users unban"),
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
        assert response_kwargs["top_level"] == "users"
        assert response_kwargs["visual_top_level"] == "users"
        assert response_kwargs["subcommand_path"] == "users unban"
        assert response_kwargs["kind"] == "success"
        assert ("result", "nessun ban attivo trovato su Discord") in response_kwargs["lines"]
        assert ("sync", "stati locali riallineati") in response_kwargs["lines"]
        assert "discord ban already missing guild=1 user=42" in caplog.text

    asyncio.run(_run())


def test_mod_users_untempban_uses_canonical_unban_flow_with_tempban_message(
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
        users_group = discord.app_commands.Group(name="users", description="users")
        register_moderazione_utenti(users_group, ctx)
        command = _find_command(users_group, "untempban")

        guild = SimpleNamespace(id=1, unban=AsyncMock())
        target_user = SimpleNamespace(id=42, mention="<@42>", name="Dormiente")
        moderator = SimpleNamespace(id=9)
        interaction = SimpleNamespace(
            guild=guild,
            guild_id=1,
            user=moderator,
            command=SimpleNamespace(qualified_name="users untempban"),
        )

        await command.callback(interaction, target_user)

        guild.unban.assert_awaited_once_with(target_user, reason="Revoca ban manuale")
        database.clear_user_ban_state.assert_awaited_once_with("1", "42")
        response_kwargs = send_standard_response.await_args.kwargs
        assert response_kwargs["subcommand_path"] == "users untempban"
        assert ("result", "temporary ban revoked") in response_kwargs["lines"]

    asyncio.run(_run())


def test_mod_users_ungrace_revokes_grace_state(
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

        database = SimpleNamespace(revoke_user_grace_state=AsyncMock())
        ctx = SimpleNamespace(
            database=database,
            footer=None,
            member_flow_notifications=None,
            barcello_service=None,
        )
        users_group = discord.app_commands.Group(name="users", description="users")
        register_moderazione_utenti(users_group, ctx)
        command = _find_command(users_group, "ungrace")

        guild = SimpleNamespace(id=1)
        target_user = SimpleNamespace(id=42, mention="<@42>", name="Dormiente")
        moderator = SimpleNamespace(id=9)
        interaction = SimpleNamespace(
            guild=guild,
            guild_id=1,
            user=moderator,
            command=SimpleNamespace(qualified_name="users ungrace"),
        )

        await command.callback(interaction, target_user)

        database.revoke_user_grace_state.assert_awaited_once()
        response_kwargs = send_standard_response.await_args.kwargs
        assert response_kwargs["subcommand_path"] == "users ungrace"
        assert ("result", "grace revoked") in response_kwargs["lines"]

    asyncio.run(_run())


def test_users_tempban_and_grace_expose_quantity_unit_not_duration() -> None:
    users_group = discord.app_commands.Group(name="users", description="users")
    ctx = SimpleNamespace(
        database=Mock(),
        footer=None,
        member_flow_notifications=None,
        barcello_service=None,
    )
    register_moderazione_utenti(users_group, ctx)

    tempban_command = _find_command(users_group, "tempban")
    grace_command = _find_command(users_group, "grace")

    tempban_params = [param.name for param in tempban_command.parameters]
    grace_params = [param.name for param in grace_command.parameters]

    assert tempban_params == ["user", "quantity", "unit", "reason"]
    assert grace_params == ["user", "quantity", "unit", "reason"]
    assert "duration" not in tempban_params
    assert "duration" not in grace_params


def test_mod_users_tempban_converts_quantity_unit_to_duration_seconds(
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

        database = SimpleNamespace(add_temp_ban=AsyncMock())
        member_flow_notifications = SimpleNamespace(
            log_action=AsyncMock(return_value={"canonical_written": False, "canonical_visible": False}),
            send_notification=AsyncMock(),
            remember_departure_action=Mock(),
        )
        ctx = SimpleNamespace(
            database=database,
            footer=None,
            member_flow_notifications=member_flow_notifications,
            barcello_service=None,
        )
        users_group = discord.app_commands.Group(name="users", description="users")
        register_moderazione_utenti(users_group, ctx)
        command = _find_command(users_group, "tempban")

        guild = SimpleNamespace(id=1, ban=AsyncMock())
        target_user = SimpleNamespace(id=42, mention="<@42>", name="Dormiente")
        moderator = SimpleNamespace(id=9)
        interaction = SimpleNamespace(
            guild=guild,
            guild_id=1,
            user=moderator,
            command=SimpleNamespace(qualified_name="users tempban"),
        )
        unit = discord.app_commands.Choice(name="ore", value="ore")

        await command.callback(interaction, target_user, 3, unit, "Motivo test")

        guild.ban.assert_awaited_once_with(
            target_user, reason="Motivo test", delete_message_seconds=0
        )
        database.add_temp_ban.assert_awaited_once()
        notify_kwargs = member_flow_notifications.log_action.await_args.kwargs
        assert notify_kwargs["action_type"] == "tempban"
        assert notify_kwargs["duration_seconds"] == 3 * 60 * 60
        response_kwargs = send_standard_response.await_args.kwargs
        assert response_kwargs["subcommand_path"] == "users tempban"
        assert ("duration", "3h") in response_kwargs["lines"]

    asyncio.run(_run())


def test_mod_users_grace_converts_quantity_unit_to_duration_seconds(
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

        database = SimpleNamespace(extend_user_grace=AsyncMock())
        member_flow_notifications = SimpleNamespace(
            log_action=AsyncMock(return_value={"canonical_written": False, "canonical_visible": False}),
            send_notification=AsyncMock(),
        )
        ctx = SimpleNamespace(
            database=database,
            footer=None,
            member_flow_notifications=member_flow_notifications,
            barcello_service=None,
        )
        users_group = discord.app_commands.Group(name="users", description="users")
        register_moderazione_utenti(users_group, ctx)
        command = _find_command(users_group, "grace")

        guild = SimpleNamespace(id=1)
        target_user = SimpleNamespace(id=42, mention="<@42>", name="Dormiente")
        moderator = SimpleNamespace(id=9)
        interaction = SimpleNamespace(
            guild=guild,
            guild_id=1,
            user=moderator,
            command=SimpleNamespace(qualified_name="users grace"),
        )
        unit = discord.app_commands.Choice(name="settimane", value="settimane")

        await command.callback(interaction, target_user, 2, unit, "Protezione test")

        database.extend_user_grace.assert_awaited_once()
        notify_kwargs = member_flow_notifications.log_action.await_args.kwargs
        assert notify_kwargs["action_type"] == "grace"
        assert notify_kwargs["duration_seconds"] == 2 * 7 * 24 * 60 * 60
        response_kwargs = send_standard_response.await_args.kwargs
        assert response_kwargs["subcommand_path"] == "users grace"
        assert ("duration", "14g") in response_kwargs["lines"]

    asyncio.run(_run())
