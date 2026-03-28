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
    assert 'unban_group = app_commands.Group(name="unban"' in modular
    assert 'untempban_group = app_commands.Group(name="untempban"' in modular
    assert '@users_group.command(name="tempban"' in modular
    assert '@users_group.command(name="tempban_list"' in modular
    assert 'name="grace"' in modular
    assert 'ungrace_group = app_commands.Group(name="ungrace"' in modular
    assert '@users_group.command(name="grace_list"' in modular
    assert 'description="Revoke an active ban for one user."' in modular
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

        database = SimpleNamespace(
            clear_user_ban_state=AsyncMock(),
            fetch_user_display_name=AsyncMock(return_value="Dormiente"),
            list_active_tempbans=AsyncMock(return_value=[]),
            list_active_bans=AsyncMock(return_value=[]),
        )
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
        command = _find_command(users_group, "unban", "user")

        guild = SimpleNamespace(id=1, unban=AsyncMock())
        moderator = SimpleNamespace(id=9)
        interaction = SimpleNamespace(
            guild=guild,
            guild_id=1,
            user=moderator,
            command=SimpleNamespace(qualified_name="users unban user"),
        )

        await command.callback(interaction, "42")

        target_user = guild.unban.await_args.args[0]
        assert target_user.id == 42
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
        assert response_kwargs["subcommand_path"] == "users unban user"
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

        database = SimpleNamespace(
            clear_user_ban_state=AsyncMock(),
            fetch_user_display_name=AsyncMock(return_value="Dormiente"),
            list_active_tempbans=AsyncMock(return_value=[]),
            list_active_bans=AsyncMock(return_value=[]),
        )
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
        command = _find_command(users_group, "unban", "user")

        not_found = discord.NotFound(
            Mock(status=404, reason="Not Found"),
            {"code": 10026, "message": "Unknown Ban"},
        )
        guild = SimpleNamespace(id=1, unban=AsyncMock(side_effect=not_found))
        moderator = SimpleNamespace(id=9)
        interaction = SimpleNamespace(
            guild=guild,
            guild_id=1,
            user=moderator,
            command=SimpleNamespace(qualified_name="users unban user"),
        )

        with caplog.at_level("INFO"):
            await command.callback(interaction, "42")

        target_user = guild.unban.await_args.args[0]
        assert target_user.id == 42
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
        assert response_kwargs["subcommand_path"] == "users unban user"
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

        database = SimpleNamespace(
            clear_user_ban_state=AsyncMock(),
            fetch_user_display_name=AsyncMock(return_value="Dormiente"),
            list_active_tempbans=AsyncMock(return_value=[]),
        )
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
        command = _find_command(users_group, "untempban", "user")

        guild = SimpleNamespace(id=1, unban=AsyncMock())
        moderator = SimpleNamespace(id=9)
        interaction = SimpleNamespace(
            guild=guild,
            guild_id=1,
            user=moderator,
            command=SimpleNamespace(qualified_name="users untempban user"),
        )

        await command.callback(interaction, "42")

        target_user = guild.unban.await_args.args[0]
        assert target_user.id == 42
        guild.unban.assert_awaited_once_with(target_user, reason="Revoca ban manuale")
        database.clear_user_ban_state.assert_awaited_once_with("1", "42")
        response_kwargs = send_standard_response.await_args.kwargs
        assert response_kwargs["subcommand_path"] == "users untempban user"
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

        database = SimpleNamespace(
            revoke_user_grace_state=AsyncMock(),
            list_active_grace_users=AsyncMock(return_value=[{"user_id": "42"}]),
            fetch_user_display_name=AsyncMock(return_value="Dormiente"),
        )
        ctx = SimpleNamespace(
            database=database,
            footer=None,
            member_flow_notifications=None,
            barcello_service=None,
        )
        users_group = discord.app_commands.Group(name="users", description="users")
        register_moderazione_utenti(users_group, ctx)
        command = _find_command(users_group, "ungrace", "user")

        guild = SimpleNamespace(id=1)
        moderator = SimpleNamespace(id=9)
        interaction = SimpleNamespace(
            guild=guild,
            guild_id=1,
            user=moderator,
            command=SimpleNamespace(qualified_name="users ungrace user"),
        )

        await command.callback(interaction, "Dormiente")

        database.revoke_user_grace_state.assert_awaited_once()
        response_kwargs = send_standard_response.await_args.kwargs
        assert response_kwargs["subcommand_path"] == "users ungrace user"
        assert ("result", "grace revoked") in response_kwargs["lines"]

    asyncio.run(_run())


def test_mod_users_unban_resolves_known_nick(
    monkeypatch,
) -> None:
    async def _run() -> None:
        send_standard_response = AsyncMock()
        monkeypatch.setattr(moderazione_utenti_module, "send_standard_response", send_standard_response)
        monkeypatch.setattr(moderazione_utenti_module, "check_permission", AsyncMock(return_value=True))

        database = SimpleNamespace(
            clear_user_ban_state=AsyncMock(),
            list_active_tempbans=AsyncMock(return_value=[]),
            list_active_bans=AsyncMock(return_value=[{"user_id": "42"}]),
            fetch_user_display_name=AsyncMock(return_value="Dormiente"),
        )
        member_flow_notifications = SimpleNamespace(
            log_action=AsyncMock(return_value={"canonical_written": True, "canonical_visible": False}),
            send_notification=AsyncMock(),
            forget_departure_action=Mock(),
        )
        ctx = SimpleNamespace(database=database, footer=None, member_flow_notifications=member_flow_notifications, barcello_service=None)
        users_group = discord.app_commands.Group(name="users", description="users")
        register_moderazione_utenti(users_group, ctx)
        command = _find_command(users_group, "unban", "user")

        guild = SimpleNamespace(id=1, unban=AsyncMock())
        interaction = SimpleNamespace(guild=guild, guild_id=1, user=SimpleNamespace(id=9), command=SimpleNamespace(qualified_name="users unban user"))

        await command.callback(interaction, "Dormiente")

        target_user = guild.unban.await_args.args[0]
        assert target_user.id == 42
        database.clear_user_ban_state.assert_awaited_once_with("1", "42")

    asyncio.run(_run())


def test_mod_users_unban_reports_missing_target_for_unknown_nick(
    monkeypatch,
) -> None:
    async def _run() -> None:
        send_standard_response = AsyncMock()
        monkeypatch.setattr(moderazione_utenti_module, "send_standard_response", send_standard_response)
        monkeypatch.setattr(moderazione_utenti_module, "check_permission", AsyncMock(return_value=True))

        database = SimpleNamespace(
            clear_user_ban_state=AsyncMock(),
            list_active_tempbans=AsyncMock(return_value=[]),
            list_active_bans=AsyncMock(return_value=[{"user_id": "42"}]),
            fetch_user_display_name=AsyncMock(return_value="Dormiente"),
        )
        ctx = SimpleNamespace(database=database, footer=None, member_flow_notifications=None, barcello_service=None)
        users_group = discord.app_commands.Group(name="users", description="users")
        register_moderazione_utenti(users_group, ctx)
        command = _find_command(users_group, "unban", "user")

        guild = SimpleNamespace(id=1, unban=AsyncMock())
        interaction = SimpleNamespace(guild=guild, guild_id=1, user=SimpleNamespace(id=9), command=SimpleNamespace(qualified_name="users unban user"))

        await command.callback(interaction, "Sconosciuto")

        guild.unban.assert_not_awaited()
        response_kwargs = send_standard_response.await_args.kwargs
        assert response_kwargs["kind"] == "error"
        assert "Nessun utente trovato" in dict(response_kwargs["lines"])["error"]

    asyncio.run(_run())


def test_mod_users_unban_reports_ambiguous_known_nick(
    monkeypatch,
) -> None:
    async def _run() -> None:
        send_standard_response = AsyncMock()
        monkeypatch.setattr(moderazione_utenti_module, "send_standard_response", send_standard_response)
        monkeypatch.setattr(moderazione_utenti_module, "check_permission", AsyncMock(return_value=True))

        async def _display_name(*, guild_id: str, user_id: str) -> str:
            return "Dormiente" if user_id in {"42", "77"} else "Altro"

        database = SimpleNamespace(
            clear_user_ban_state=AsyncMock(),
            list_active_tempbans=AsyncMock(return_value=[]),
            list_active_bans=AsyncMock(return_value=[{"user_id": "42"}, {"user_id": "77"}]),
            fetch_user_display_name=AsyncMock(side_effect=_display_name),
        )
        ctx = SimpleNamespace(database=database, footer=None, member_flow_notifications=None, barcello_service=None)
        users_group = discord.app_commands.Group(name="users", description="users")
        register_moderazione_utenti(users_group, ctx)
        command = _find_command(users_group, "unban", "user")

        guild = SimpleNamespace(id=1, unban=AsyncMock())
        interaction = SimpleNamespace(guild=guild, guild_id=1, user=SimpleNamespace(id=9), command=SimpleNamespace(qualified_name="users unban user"))

        await command.callback(interaction, "Dormiente")

        guild.unban.assert_not_awaited()
        response_kwargs = send_standard_response.await_args.kwargs
        lines = dict(response_kwargs["lines"])
        assert response_kwargs["kind"] == "error"
        assert "Nickname ambiguo" in lines["error"]
        assert "Specifica l'ID utente." == lines["hint"]

    asyncio.run(_run())


def test_mod_users_batch_revocations_support_today_yesterday_last_range_for_all_modes(monkeypatch) -> None:
    async def _run() -> None:
        send_standard_response = AsyncMock()
        monkeypatch.setattr(moderazione_utenti_module, "send_standard_response", send_standard_response)
        monkeypatch.setattr(moderazione_utenti_module, "check_permission", AsyncMock(return_value=True))

        guild = SimpleNamespace(id=1, unban=AsyncMock())
        interaction = SimpleNamespace(guild=guild, guild_id=1, user=SimpleNamespace(id=9), command=SimpleNamespace(qualified_name="users test"))

        for mode in ("unban", "untempban", "ungrace"):
            database = SimpleNamespace(
                clear_user_ban_state=AsyncMock(),
                revoke_user_grace_state=AsyncMock(),
                fetch_user_display_name=AsyncMock(return_value="Dormiente"),
                list_active_bans=AsyncMock(return_value=[{"user_id": "42"}]),
                list_active_tempbans=AsyncMock(return_value=[{"user_id": "42"}]),
                list_active_grace_users=AsyncMock(return_value=[{"user_id": "42"}]),
            )
            ctx = SimpleNamespace(database=database, footer=None, member_flow_notifications=None, barcello_service=None, config=SimpleNamespace())
            users_group = discord.app_commands.Group(name="users", description="users")
            register_moderazione_utenti(users_group, ctx)
            mode_group = _find_command(users_group, mode)

            await _find_command(mode_group, "today").callback(interaction, "batch")
            await _find_command(mode_group, "yesterday").callback(interaction, "batch")

            unit = discord.app_commands.Choice(name="hours", value="ore")
            await _find_command(mode_group, "last").callback(interaction, 2, unit, "batch")
            await _find_command(mode_group, "range").callback(interaction, "20/03/2026 10:00", "21/03/2026 10:00", "batch")

            paths = [call.kwargs["subcommand_path"] for call in send_standard_response.await_args_list[-4:]]
            assert paths == [
                f"users {mode} today",
                f"users {mode} yesterday",
                f"users {mode} last",
                f"users {mode} range",
            ]
            if mode == "ungrace":
                assert database.revoke_user_grace_state.await_count == 4
                assert database.list_active_grace_users.await_count == 4
            elif mode == "untempban":
                assert database.clear_user_ban_state.await_count == 4
                assert database.list_active_tempbans.await_count == 4
            else:
                assert database.clear_user_ban_state.await_count == 4
                assert database.list_active_bans.await_count == 4

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


def test_users_unban_untempban_ungrace_user_expose_nick_or_id_parameter() -> None:
    users_group = discord.app_commands.Group(name="users", description="users")
    ctx = SimpleNamespace(
        database=Mock(),
        footer=None,
        member_flow_notifications=None,
        barcello_service=None,
    )
    register_moderazione_utenti(users_group, ctx)
    unban_command = _find_command(users_group, "unban", "user")
    untempban_command = _find_command(users_group, "untempban", "user")
    ungrace_command = _find_command(users_group, "ungrace", "user")

    assert [param.name for param in unban_command.parameters] == ["nick_or_id", "reason"]
    assert [param.name for param in untempban_command.parameters] == ["nick_or_id", "reason"]
    assert [param.name for param in ungrace_command.parameters] == ["nick_or_id", "reason"]


def test_users_unban_untempban_ungrace_groups_include_temporal_variants() -> None:
    users_group = discord.app_commands.Group(name="users", description="users")
    ctx = SimpleNamespace(database=Mock(), footer=None, member_flow_notifications=None, barcello_service=None, config=SimpleNamespace())
    register_moderazione_utenti(users_group, ctx)

    expected = {"user", "today", "yesterday", "last", "range", "oggi", "ieri", "ultimi", "intervallo"}
    assert {cmd.name for cmd in _find_command(users_group, "unban").commands} == expected
    assert {cmd.name for cmd in _find_command(users_group, "untempban").commands} == expected
    assert {cmd.name for cmd in _find_command(users_group, "ungrace").commands} == expected


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
