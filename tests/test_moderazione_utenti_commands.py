from pathlib import Path
import asyncio
import inspect
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
    assert 'dms_group = app_commands.Group(name="dms"' in modular
    assert 'grace_group = app_commands.Group(name="grace"' in modular
    assert '@grace_group.command(name="manual"' in modular
    assert '@grace_group.command(name="tempban_set"' in modular
    assert '@grace_group.command(name="tempban_show"' in modular
    assert '@grace_group.command(name="tempban_reset"' in modular
    assert 'ungrace_group = app_commands.Group(name="ungrace"' in modular
    assert '@users_group.command(name="grace_list"' in modular
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


def test_inactivity_dms_on_off_status_commands_are_registered() -> None:
    source = Path("app/plugins/commands_modular/inattivi.py").read_text()

    assert '@dms_group.command(name="on"' in source
    assert '@dms_group.command(name="off"' in source
    assert '@dms_group.command(name="status"' in source


def test_users_alias_commands_are_registered_as_top_level_aliases() -> None:
    source = Path("app/plugins/commands.py").read_text()
    group = discord.app_commands.Group(name="users", description="x")
    ctx = SimpleNamespace(database=Mock(), footer=None, member_flow_notifications=None, barcello_service=None)
    aliases: list[discord.app_commands.Command] = []

    register_moderazione_utenti(group, ctx, alias_commands=aliases)

    assert 'user_alias_commands: list[app_commands.Command] = []' in source
    assert '*user_alias_commands,' in source
    assert [command.name for command in aliases] == ["kick", "ban", "unban", "tempban", "untempban", "grace", "ungrace"]

def test_users_alias_revocation_commands_use_motivo_parameter() -> None:
    group = discord.app_commands.Group(name="users", description="x")
    ctx = SimpleNamespace(database=Mock(), footer=None, member_flow_notifications=None, barcello_service=None)
    aliases: list[discord.app_commands.Command] = []

    register_moderazione_utenti(group, ctx, alias_commands=aliases)

    by_name = {command.name: command for command in aliases}
    assert [param.name for param in _find_command(by_name["unban"], "oggi").parameters] == ["motivo"]
    assert [param.name for param in _find_command(by_name["untempban"], "oggi").parameters] == ["motivo"]
    assert [param.name for param in _find_command(by_name["ungrace"], "oggi").parameters] == ["motivo"]


def test_users_canonical_inventory_matches_contract() -> None:
    users_group = discord.app_commands.Group(name="users", description="users")
    ctx = SimpleNamespace(database=Mock(), footer=None, member_flow_notifications=None, barcello_service=None, config=SimpleNamespace())
    register_moderazione_utenti(users_group, ctx)

    assert {cmd.name for cmd in users_group.commands} == {
        "kick",
        "kick_list",
        "ban",
        "ban_list",
        "tempban",
        "tempban_list",
        "dms",
        "grace",
        "grace_list",
        "unban",
        "untempban",
        "ungrace",
    }
    assert {cmd.name for cmd in _find_command(users_group, "dms").commands} == {
        "on",
        "off",
        "status",
        "template_grace_set",
        "template_grace_show",
        "template_grace_reset",
        "template_tempban_set",
        "template_tempban_show",
        "template_tempban_reset",
        "template_kick_set",
        "template_kick_show",
        "template_kick_reset",
        "template_ban_set",
        "template_ban_show",
        "template_ban_reset",
        "cooldown_set",
        "cooldown_show",
        "cooldown_reset",
        "invite_set",
        "invite_show",
        "invite_reset",
    }
    assert {cmd.name for cmd in _find_command(users_group, "grace").commands} == {
        "manual",
        "tempban_set",
        "tempban_show",
        "tempban_reset",
    }
    assert "assign" not in {cmd.name for cmd in _find_command(users_group, "grace").commands}


def test_users_alias_inventory_matches_contract() -> None:
    users_group = discord.app_commands.Group(name="users", description="users")
    ctx = SimpleNamespace(database=Mock(), footer=None, member_flow_notifications=None, barcello_service=None, config=SimpleNamespace())
    aliases: list[discord.app_commands.Command | discord.app_commands.Group] = []
    register_moderazione_utenti(users_group, ctx, alias_commands=aliases)

    by_name = {command.name: command for command in aliases}
    assert set(by_name) == {"kick", "ban", "unban", "tempban", "untempban", "grace", "ungrace"}
    assert "assign" not in by_name


def test_users_alias_revocation_groups_use_italian_temporal_variants_only() -> None:
    group = discord.app_commands.Group(name="users", description="x")
    ctx = SimpleNamespace(database=Mock(), footer=None, member_flow_notifications=None, barcello_service=None, config=SimpleNamespace())
    aliases: list[discord.app_commands.Command | discord.app_commands.Group] = []

    register_moderazione_utenti(group, ctx, alias_commands=aliases)

    by_name = {command.name: command for command in aliases}
    expected = {"oggi", "ieri", "ultimi", "range"}
    assert {cmd.name for cmd in by_name["unban"].commands} == expected
    assert {cmd.name for cmd in by_name["untempban"].commands} == expected
    assert {cmd.name for cmd in by_name["ungrace"].commands} == expected


def test_users_alias_tempban_and_grace_expose_quantity_unit_not_duration() -> None:
    group = discord.app_commands.Group(name="users", description="x")
    ctx = SimpleNamespace(database=Mock(), footer=None, member_flow_notifications=None, barcello_service=None)
    aliases: list[discord.app_commands.Command] = []

    register_moderazione_utenti(group, ctx, alias_commands=aliases)

    by_name = {command.name: command for command in aliases}
    tempban_params = [param.name for param in by_name["tempban"].parameters]
    grace_params = [param.name for param in by_name["grace"].parameters]

    assert tempban_params == ["nick_o_id", "quantità", "unità", "motivo"]
    assert grace_params == ["nick_o_id", "quantità", "unità", "motivo"]
    assert "duration" not in tempban_params
    assert "duration" not in grace_params


def test_users_unban_untempban_ungrace_range_use_from_to_parameters() -> None:
    users_group = discord.app_commands.Group(name="users", description="users")
    ctx = SimpleNamespace(database=Mock(), footer=None, member_flow_notifications=None, barcello_service=None, config=SimpleNamespace())
    register_moderazione_utenti(users_group, ctx)

    unban_range = _find_command(users_group, "unban", "range")
    untempban_range = _find_command(users_group, "untempban", "range")
    ungrace_range = _find_command(users_group, "ungrace", "range")

    def _option_names(command: discord.app_commands.Command) -> list[str]:
        return [str(param.display_name) for param in command.parameters]

    assert _option_names(unban_range) == ["from", "to", "reason"]
    assert _option_names(untempban_range) == ["from", "to", "reason"]
    assert _option_names(ungrace_range) == ["from", "to", "reason"]


def test_users_dms_cooldown_set_uses_quantity_and_unit_parameters() -> None:
    users_group = discord.app_commands.Group(name="users", description="users")
    ctx = SimpleNamespace(database=Mock(), footer=None, member_flow_notifications=None, barcello_service=None, config=SimpleNamespace())
    register_moderazione_utenti(users_group, ctx)

    cooldown_set = _find_command(users_group, "dms", "cooldown_set")
    param_names = [param.name for param in cooldown_set.parameters]
    assert param_names == ["quantity", "unit"]
    assert "days" not in param_names


def test_grace_alias_is_direct_command_without_assign_subcommand() -> None:
    users_group = discord.app_commands.Group(name="users", description="users")
    ctx = SimpleNamespace(database=Mock(), footer=None, member_flow_notifications=None, barcello_service=None)
    aliases: list[discord.app_commands.Command | discord.app_commands.Group] = []
    register_moderazione_utenti(users_group, ctx, alias_commands=aliases)

    by_name = {command.name: command for command in aliases}
    assert "grace" in by_name
    assert not isinstance(by_name["grace"], discord.app_commands.Group)
    assert [param.name for param in by_name["grace"].parameters] == ["nick_o_id", "quantità", "unità", "motivo"]

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


def test_alias_batch_revocations_support_oggi_ieri_ultimi_range_for_all_modes(monkeypatch) -> None:
    async def _run() -> None:
        send_standard_response = AsyncMock()
        monkeypatch.setattr(moderazione_utenti_module, "send_standard_response", send_standard_response)
        monkeypatch.setattr(moderazione_utenti_module, "check_permission", AsyncMock(return_value=True))

        guild = SimpleNamespace(id=1, unban=AsyncMock())
        interaction = SimpleNamespace(guild=guild, guild_id=1, user=SimpleNamespace(id=9), command=SimpleNamespace(qualified_name="alias test"))

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
            aliases: list[discord.app_commands.Command | discord.app_commands.Group] = []
            register_moderazione_utenti(users_group, ctx, alias_commands=aliases)
            mode_group = next(command for command in aliases if isinstance(command, discord.app_commands.Group) and command.name == mode)

            await _find_command(mode_group, "oggi").callback(interaction, "batch")
            await _find_command(mode_group, "ieri").callback(interaction, "batch")

            unit = discord.app_commands.Choice(name="ore", value="ore")
            await _find_command(mode_group, "ultimi").callback(interaction, 2, unit, "batch")
            await _find_command(mode_group, "range").callback(interaction, "20/03/2026 10:00", "21/03/2026 10:00", "batch")

            paths = [call.kwargs["subcommand_path"] for call in send_standard_response.await_args_list[-4:]]
            assert paths == [
                f"{mode} oggi",
                f"{mode} ieri",
                f"{mode} ultimi",
                f"{mode} range",
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


def test_users_tempban_and_grace_manual_expose_quantity_unit_not_duration() -> None:
    users_group = discord.app_commands.Group(name="users", description="users")
    ctx = SimpleNamespace(
        database=Mock(),
        footer=None,
        member_flow_notifications=None,
        barcello_service=None,
    )
    register_moderazione_utenti(users_group, ctx)

    tempban_command = _find_command(users_group, "tempban")
    grace_command = _find_command(users_group, "grace", "manual")

    tempban_params = [param.name for param in tempban_command.parameters]
    grace_params = [param.name for param in grace_command.parameters]

    assert tempban_params == ["nick_or_id", "quantity", "unit", "reason"]
    assert grace_params == ["nick_or_id", "quantity", "unit", "reason"]
    assert "duration" not in tempban_params
    assert "duration" not in grace_params


def test_users_unban_untempban_ungrace_groups_include_temporal_variants() -> None:
    users_group = discord.app_commands.Group(name="users", description="users")
    ctx = SimpleNamespace(database=Mock(), footer=None, member_flow_notifications=None, barcello_service=None, config=SimpleNamespace())
    register_moderazione_utenti(users_group, ctx)

    expected = {"today", "yesterday", "last", "range"}
    assert {cmd.name for cmd in _find_command(users_group, "unban").commands} == expected
    assert {cmd.name for cmd in _find_command(users_group, "untempban").commands} == expected
    assert {cmd.name for cmd in _find_command(users_group, "ungrace").commands} == expected


def test_users_moderation_commands_use_nick_or_id_for_live_targets() -> None:
    users_group = discord.app_commands.Group(name="users", description="users")
    ctx = SimpleNamespace(
        database=Mock(),
        footer=None,
        member_flow_notifications=None,
        barcello_service=None,
    )
    aliases: list[discord.app_commands.Command] = []
    register_moderazione_utenti(users_group, ctx, alias_commands=aliases)

    assert [param.name for param in _find_command(users_group, "kick").parameters] == ["nick_or_id", "reason"]
    assert [param.name for param in _find_command(users_group, "ban").parameters] == ["nick_or_id", "reason"]
    assert [param.name for param in _find_command(users_group, "tempban").parameters] == ["nick_or_id", "quantity", "unit", "reason"]
    assert [param.name for param in _find_command(users_group, "grace", "manual").parameters] == ["nick_or_id", "quantity", "unit", "reason"]

    by_name = {command.name: command for command in aliases}
    assert [param.name for param in by_name["kick"].parameters] == ["nick_o_id", "motivo"]
    assert [param.name for param in by_name["ban"].parameters] == ["nick_o_id", "motivo"]
    assert [param.name for param in by_name["tempban"].parameters] == ["nick_o_id", "quantità", "unità", "motivo"]
    assert [param.name for param in by_name["grace"].parameters] == ["nick_o_id", "quantità", "unità", "motivo"]


def test_users_live_target_signatures_accept_member_or_string_id() -> None:
    users_group = discord.app_commands.Group(name="users", description="users")
    ctx = SimpleNamespace(database=Mock(), footer=None, member_flow_notifications=None, barcello_service=None)
    aliases: list[discord.app_commands.Command] = []
    register_moderazione_utenti(users_group, ctx, alias_commands=aliases)

    expected = "discord.Member"
    assert str(inspect.signature(_find_command(users_group, "kick").callback).parameters["nick_or_id"].annotation) == expected
    assert str(inspect.signature(_find_command(users_group, "ban").callback).parameters["nick_or_id"].annotation) == expected
    assert str(inspect.signature(_find_command(users_group, "tempban").callback).parameters["nick_or_id"].annotation) == expected
    assert str(inspect.signature(_find_command(users_group, "grace", "manual").callback).parameters["nick_or_id"].annotation) == expected

    by_name = {command.name: command for command in aliases}
    assert str(inspect.signature(by_name["kick"].callback).parameters["nick_o_id"].annotation) == expected
    assert str(inspect.signature(by_name["ban"].callback).parameters["nick_o_id"].annotation) == expected
    assert str(inspect.signature(by_name["tempban"].callback).parameters["nick_o_id"].annotation) == expected
    assert str(inspect.signature(by_name["grace"].callback).parameters["nick_o_id"].annotation) == expected


def test_resolve_target_user_supports_member_and_manual_id() -> None:
    member = Mock(spec=discord.Member)
    member.id = 123
    guild = SimpleNamespace(get_member=Mock(return_value=member))

    assert moderazione_utenti_module.resolve_target_user(member, guild) is member
    assert moderazione_utenti_module.resolve_target_user("123", guild) is member
    assert moderazione_utenti_module.resolve_target_user("<@123>", guild) is member
    assert moderazione_utenti_module.resolve_target_user("not-an-id", guild) is None


def test_mod_users_kick_unknown_target_returns_controlled_error(monkeypatch) -> None:
    async def _run() -> None:
        send_standard_response = AsyncMock()
        monkeypatch.setattr(moderazione_utenti_module, "send_standard_response", send_standard_response)
        monkeypatch.setattr(moderazione_utenti_module, "check_permission", AsyncMock(return_value=True))

        ctx = SimpleNamespace(
            database=SimpleNamespace(),
            footer=None,
            member_flow_notifications=None,
            barcello_service=None,
        )
        users_group = discord.app_commands.Group(name="users", description="users")
        register_moderazione_utenti(users_group, ctx)
        command = _find_command(users_group, "kick")

        guild = SimpleNamespace(
            id=1,
            get_member=Mock(return_value=None),
            fetch_member=AsyncMock(side_effect=discord.NotFound(response=Mock(), message="missing")),
            members=[],
        )
        interaction = SimpleNamespace(guild=guild, guild_id=1, user=SimpleNamespace(id=9))

        await command.callback(interaction, "fakeuzzo")

        send_standard_response.assert_awaited_once()
        response = send_standard_response.await_args.kwargs
        assert response["kind"] == "error"
        assert response["subcommand_path"] == "users kick"
        assert any("Nessun membro trovato" in str(value) for _, value in response["lines"])

    asyncio.run(_run())


def test_mod_users_live_target_commands_return_controlled_error_when_missing(monkeypatch) -> None:
    async def _run() -> None:
        send_standard_response = AsyncMock()
        monkeypatch.setattr(moderazione_utenti_module, "send_standard_response", send_standard_response)
        monkeypatch.setattr(moderazione_utenti_module, "check_permission", AsyncMock(return_value=True))

        database = SimpleNamespace(add_temp_ban=AsyncMock(), extend_user_grace=AsyncMock())
        ctx = SimpleNamespace(
            database=database,
            footer=None,
            member_flow_notifications=SimpleNamespace(
                log_action=AsyncMock(return_value={"canonical_written": False, "canonical_visible": False}),
                send_notification=AsyncMock(),
                remember_departure_action=Mock(),
            ),
            barcello_service=None,
        )
        users_group = discord.app_commands.Group(name="users", description="users")
        register_moderazione_utenti(users_group, ctx)
        ban_cmd = _find_command(users_group, "ban")
        tempban_cmd = _find_command(users_group, "tempban")
        grace_cmd = _find_command(users_group, "grace", "manual")
        guild = SimpleNamespace(
            id=1,
            get_member=Mock(return_value=None),
            fetch_member=AsyncMock(side_effect=discord.NotFound(response=Mock(), message="missing")),
            members=[],
            ban=AsyncMock(),
        )
        interaction = SimpleNamespace(guild=guild, guild_id=1, user=SimpleNamespace(id=9))
        unit = discord.app_commands.Choice(name="ore", value="ore")

        await ban_cmd.callback(interaction, "999")
        await tempban_cmd.callback(interaction, "999", 1, unit, None)
        await grace_cmd.callback(interaction, "999", 1, unit, None)

        assert send_standard_response.await_count == 3
        for idx, expected_path in enumerate(("users ban", "users tempban", "users grace")):
            kwargs = send_standard_response.await_args_list[idx].kwargs
            assert kwargs["kind"] == "error"
            assert kwargs["subcommand_path"] == expected_path
        guild.ban.assert_not_awaited()
        database.add_temp_ban.assert_not_awaited()
        database.extend_user_grace.assert_not_awaited()

    asyncio.run(_run())

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

        target_user = SimpleNamespace(id=42, mention="<@42>", name="Dormiente")
        guild = SimpleNamespace(id=1, ban=AsyncMock(), get_member=Mock(return_value=target_user), fetch_member=AsyncMock())
        moderator = SimpleNamespace(id=9)
        interaction = SimpleNamespace(
            guild=guild,
            guild_id=1,
            user=moderator,
            command=SimpleNamespace(qualified_name="users tempban"),
        )
        unit = discord.app_commands.Choice(name="ore", value="ore")

        await command.callback(interaction, "42", 3, unit, "Motivo test")

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
        command = _find_command(users_group, "grace", "manual")

        target_user = SimpleNamespace(id=42, mention="<@42>", name="Dormiente")
        guild = SimpleNamespace(id=1, get_member=Mock(return_value=target_user), fetch_member=AsyncMock())
        moderator = SimpleNamespace(id=9)
        interaction = SimpleNamespace(
            guild=guild,
            guild_id=1,
            user=moderator,
            command=SimpleNamespace(qualified_name="users grace manual"),
        )
        unit = discord.app_commands.Choice(name="settimane", value="settimane")

        await command.callback(interaction, "42", 2, unit, "Protezione test")

        database.extend_user_grace.assert_awaited_once()
        notify_kwargs = member_flow_notifications.log_action.await_args.kwargs
        assert notify_kwargs["action_type"] == "grace"
        assert notify_kwargs["duration_seconds"] == 2 * 7 * 24 * 60 * 60
        response_kwargs = send_standard_response.await_args.kwargs
        assert response_kwargs["subcommand_path"] == "users grace"
        assert ("duration", "14g") in response_kwargs["lines"]

    asyncio.run(_run())


def test_mod_users_actions_include_dm_delivery_line_and_invoke_dm_service(monkeypatch) -> None:
    async def _run() -> None:
        send_standard_response = AsyncMock()
        monkeypatch.setattr(moderazione_utenti_module, "send_standard_response", send_standard_response)
        monkeypatch.setattr(moderazione_utenti_module, "check_permission", AsyncMock(return_value=True))

        dm_service = SimpleNamespace(send_for_event=AsyncMock(return_value={"sent": True}), send_for_event_by_user_id=AsyncMock())
        dm_cls = Mock(return_value=dm_service)
        monkeypatch.setattr(moderazione_utenti_module, "UsersModerationDmService", dm_cls)

        database = SimpleNamespace(add_temp_ban=AsyncMock(), extend_user_grace=AsyncMock())
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
            bot=SimpleNamespace(),
        )
        users_group = discord.app_commands.Group(name="users", description="users")
        register_moderazione_utenti(users_group, ctx)
        dm_cls.assert_called_once_with(database, bot=ctx.bot)

        target_user = SimpleNamespace(
            id=42,
            mention="<@42>",
            name="Dormiente",
            kick=AsyncMock(),
        )
        guild = SimpleNamespace(id=1, ban=AsyncMock(), get_member=Mock(return_value=target_user), fetch_member=AsyncMock())
        interaction = SimpleNamespace(
            guild=guild,
            guild_id=1,
            user=SimpleNamespace(id=9),
            command=SimpleNamespace(qualified_name="users moderation"),
        )
        hour = discord.app_commands.Choice(name="ore", value="ore")
        day = discord.app_commands.Choice(name="giorni", value="giorni")

        await _find_command(users_group, "kick").callback(interaction, "42", "Kick test")
        await _find_command(users_group, "ban").callback(interaction, "42", "Ban test")
        await _find_command(users_group, "tempban").callback(interaction, "42", 1, hour, "Tempban test")
        await _find_command(users_group, "grace", "manual").callback(interaction, "42", 2, day, "Grace test")

        assert dm_service.send_for_event_by_user_id.await_count == 0
        assert dm_service.send_for_event.await_count == 4

        kick_kwargs = send_standard_response.await_args_list[0].kwargs
        ban_kwargs = send_standard_response.await_args_list[1].kwargs
        tempban_kwargs = send_standard_response.await_args_list[2].kwargs
        grace_kwargs = send_standard_response.await_args_list[3].kwargs
        assert ("dm", "delivered") in kick_kwargs["lines"]
        assert ("dm", "delivered") in ban_kwargs["lines"]
        assert ("dm", "delivered") in tempban_kwargs["lines"]
        assert ("dm", "delivered") in grace_kwargs["lines"]

    asyncio.run(_run())


def test_mod_users_dm_delivery_status_mapping_in_response(monkeypatch) -> None:
    async def _run() -> None:
        send_standard_response = AsyncMock()
        monkeypatch.setattr(moderazione_utenti_module, "send_standard_response", send_standard_response)
        monkeypatch.setattr(moderazione_utenti_module, "check_permission", AsyncMock(return_value=True))

        dm_service = SimpleNamespace(
            send_for_event=AsyncMock(
                side_effect=[
                    {"sent": True},
                    {"sent": True, "fallback": "text"},
                    {"sent": False, "skipped": "error", "error": "Forbidden"},
                    {"sent": False, "skipped": "disabled"},
                    {"sent": False, "skipped": "user_unavailable"},
                ]
            ),
            send_for_event_by_user_id=AsyncMock(),
        )
        monkeypatch.setattr(moderazione_utenti_module, "UsersModerationDmService", Mock(return_value=dm_service))

        ctx = SimpleNamespace(
            database=SimpleNamespace(),
            footer=None,
            member_flow_notifications=SimpleNamespace(
                log_action=AsyncMock(return_value={"canonical_written": False, "canonical_visible": False}),
                send_notification=AsyncMock(),
                remember_departure_action=Mock(),
                forget_departure_action=Mock(),
            ),
            barcello_service=None,
            bot=SimpleNamespace(),
        )
        users_group = discord.app_commands.Group(name="users", description="users")
        register_moderazione_utenti(users_group, ctx)
        kick_cmd = _find_command(users_group, "kick")

        target_user = SimpleNamespace(id=42, mention="<@42>", name="Dormiente", kick=AsyncMock())
        guild = SimpleNamespace(id=1, get_member=Mock(return_value=target_user), fetch_member=AsyncMock())
        interaction = SimpleNamespace(guild=guild, guild_id=1, user=SimpleNamespace(id=9), command=SimpleNamespace(qualified_name="users kick"))

        for idx in range(5):
            await kick_cmd.callback(interaction, "42", f"Kick test {idx}")

        dm_values = [{key: value for key, value in call.kwargs["lines"]}["dm"] for call in send_standard_response.await_args_list]
        assert dm_values == [
            "delivered",
            "delivered (text fallback)",
            "failed (Forbidden)",
            "skipped (disabled)",
            "skipped (user_unavailable)",
        ]

    asyncio.run(_run())


def test_mod_users_manual_commands_send_dm_before_moderation_action(monkeypatch) -> None:
    async def _run() -> None:
        send_standard_response = AsyncMock()
        monkeypatch.setattr(moderazione_utenti_module, "send_standard_response", send_standard_response)
        monkeypatch.setattr(moderazione_utenti_module, "check_permission", AsyncMock(return_value=True))

        call_order: list[str] = []

        async def _send_for_event(**kwargs):
            event_type = str(kwargs["event_type"])
            call_order.append(f"dm:{event_type}")
            return {"sent": True}

        async def _kick(*args, **kwargs):
            _ = args, kwargs
            call_order.append("kick")

        async def _ban(*args, **kwargs):
            _ = args, kwargs
            call_order.append("ban")

        dm_service = SimpleNamespace(send_for_event=AsyncMock(side_effect=_send_for_event), send_for_event_by_user_id=AsyncMock())
        monkeypatch.setattr(moderazione_utenti_module, "UsersModerationDmService", Mock(return_value=dm_service))

        database = SimpleNamespace(add_temp_ban=AsyncMock())
        member_flow_notifications = SimpleNamespace(
            log_action=AsyncMock(return_value={"canonical_written": False, "canonical_visible": False}),
            send_notification=AsyncMock(),
            remember_departure_action=Mock(),
            forget_departure_action=Mock(),
        )
        ctx = SimpleNamespace(
            database=database,
            footer=None,
            member_flow_notifications=member_flow_notifications,
            barcello_service=None,
            bot=SimpleNamespace(),
        )
        users_group = discord.app_commands.Group(name="users", description="users")
        register_moderazione_utenti(users_group, ctx)

        target_user = SimpleNamespace(id=42, mention="<@42>", name="Dormiente", kick=AsyncMock(side_effect=_kick))
        guild = SimpleNamespace(id=1, ban=AsyncMock(side_effect=_ban), get_member=Mock(return_value=target_user), fetch_member=AsyncMock())
        interaction = SimpleNamespace(
            guild=guild,
            guild_id=1,
            user=SimpleNamespace(id=9),
            command=SimpleNamespace(qualified_name="users moderation"),
        )
        unit = discord.app_commands.Choice(name="ore", value="ore")

        await _find_command(users_group, "kick").callback(interaction, "42", "Kick test")
        await _find_command(users_group, "ban").callback(interaction, "42", "Ban test")
        await _find_command(users_group, "tempban").callback(interaction, "42", 1, unit, "Tempban test")

        assert call_order == [
            "dm:kick",
            "kick",
            "dm:ban",
            "ban",
            "dm:tempban",
            "ban",
        ]

    asyncio.run(_run())


def test_users_grace_tempban_set_show_reset() -> None:
    async def _run() -> None:
        send_standard_response = AsyncMock()
        monkeypatch = __import__("pytest").MonkeyPatch()
        monkeypatch.setattr(
            moderazione_utenti_module, "send_standard_response", send_standard_response
        )
        monkeypatch.setattr(
            moderazione_utenti_module, "check_permission", AsyncMock(return_value=True)
        )
        database = SimpleNamespace(
            set_setting=AsyncMock(),
            get_setting=AsyncMock(side_effect=["10800", "0"]),
        )
        ctx = SimpleNamespace(database=database, footer=None, member_flow_notifications=None, barcello_service=None)
        users_group = discord.app_commands.Group(name="users", description="users")
        register_moderazione_utenti(users_group, ctx)
        set_cmd = _find_command(users_group, "grace", "tempban_set")
        show_cmd = _find_command(users_group, "grace", "tempban_show")
        reset_cmd = _find_command(users_group, "grace", "tempban_reset")
        interaction = SimpleNamespace(guild_id=1, guild=SimpleNamespace(id=1), user=SimpleNamespace(id=7), command=SimpleNamespace(qualified_name="users grace tempban_set"))

        unit = discord.app_commands.Choice(name="ore", value="ore")
        await set_cmd.callback(interaction, 3, unit)
        await show_cmd.callback(interaction)
        await reset_cmd.callback(interaction)

        database.set_setting.assert_any_await("users.grace.tempban.default_seconds.1", "10800")
        database.set_setting.assert_any_await("users.grace.tempban.default_seconds.1", "0")
        assert send_standard_response.await_args_list[0].kwargs["subcommand_path"] == "users grace tempban_set"
        assert send_standard_response.await_args_list[0].kwargs["subtitle_args"] == [3, unit]
        assert ("default_tempban", "3h") in send_standard_response.await_args_list[0].kwargs["lines"]
        assert send_standard_response.await_args_list[1].kwargs["subcommand_path"] == "users grace tempban_show"
        assert ("default_tempban", "3h") in send_standard_response.await_args_list[1].kwargs["lines"]
        assert send_standard_response.await_args_list[2].kwargs["subcommand_path"] == "users grace tempban_reset"
        assert ("default_tempban", "0m") in send_standard_response.await_args_list[2].kwargs["lines"]
        monkeypatch.undo()

    asyncio.run(_run())


def test_moderation_list_formatter_uses_structured_italian_fields_only() -> None:
    kick_line = moderazione_utenti_module._format_moderation_list_line(
        {
            "user_id": "42",
            "action_type": "kick",
            "created_at": "2026-03-28T17:17:00+00:00",
            "reason": "È stato espulso da ... per la 1° volta",
        },
        list_kind="kick",
    )
    tempban_line = moderazione_utenti_module._format_moderation_list_line(
        {
            "user_id": "43",
            "action_type": "tempban",
            "created_at": "2026-03-28T17:17:00+00:00",
            "expires_at": "2026-03-30T17:17:00+00:00",
            "reason": "Che peccato.",
        },
        list_kind="tempban",
    )
    grace_line = moderazione_utenti_module._format_moderation_list_line(
        {
            "user_id": "44",
            "action_type": "grace",
            "created_at": "2026-03-28T17:17:00+00:00",
            "expires_at": "2026-03-29T17:17:00+00:00",
            "reason": "Provvedimento registrato.",
        },
        list_kind="grace",
        grace_post_tempban_seconds=2 * 24 * 60 * 60,
    )

    assert "28/03/2026 18:17" in kick_line
    assert "29/03/2026 19:17" in grace_line
    assert "Che peccato" not in tempban_line
    assert "Provvedimento registrato" not in grace_line
    assert "espulso da" not in kick_line
    assert "scade il 30/03/2026 19:17" in tempban_line
    assert "grace scade il 29/03/2026 19:17" in grace_line
    assert "tempban successivo: 2g" in grace_line
    assert "tempban previsto fino al 31/03/2026 19:17" in grace_line


def test_users_list_commands_render_structured_lines_and_no_narrative(monkeypatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(moderazione_utenti_module, "check_permission", AsyncMock(return_value=True))
        send_lines_mock = AsyncMock()
        monkeypatch.setattr(moderazione_utenti_module, "_send_lines", send_lines_mock)

        database = SimpleNamespace(
            list_recent_kicked_users=AsyncMock(
                return_value=[
                    {
                        "user_id": "42",
                        "action_type": "kick",
                        "created_at": "2026-03-28T17:17:00+00:00",
                        "reason": "è stato espulso da ... per la 1° volta",
                    }
                ]
            ),
            list_active_bans=AsyncMock(
                return_value=[
                    {
                        "user_id": "43",
                        "action_type": "ban",
                        "created_at": "2026-03-28T17:17:00+00:00",
                        "reason": "Provvedimento registrato.",
                    }
                ]
            ),
            list_active_tempbans=AsyncMock(
                return_value=[
                    {
                        "user_id": "44",
                        "action_type": "tempban",
                        "created_at": "2026-03-28T17:17:00+00:00",
                        "expires_at": "2026-03-30T17:17:00+00:00",
                        "reason": "Che peccato.",
                    }
                ]
            ),
            list_active_grace_users=AsyncMock(
                return_value=[
                    {
                        "user_id": "45",
                        "action_type": "grace",
                        "created_at": "2026-03-28T17:17:00+00:00",
                        "expires_at": "2026-03-29T17:17:00+00:00",
                        "reason": "Che peccato.",
                    }
                ]
            ),
            get_setting=AsyncMock(return_value=str(2 * 24 * 60 * 60)),
        )
        ctx = SimpleNamespace(database=database, footer=None, member_flow_notifications=None, barcello_service=None, config=SimpleNamespace())
        users_group = discord.app_commands.Group(name="users", description="users")
        register_moderazione_utenti(users_group, ctx)
        interaction = SimpleNamespace(guild_id=1, guild=SimpleNamespace(id=1), user=SimpleNamespace(id=9))

        await _find_command(users_group, "kick_list").callback(interaction)
        await _find_command(users_group, "ban_list").callback(interaction)
        await _find_command(users_group, "tempban_list").callback(interaction)
        await _find_command(users_group, "grace_list").callback(interaction)

        assert send_lines_mock.await_count == 4
        kick_lines = send_lines_mock.await_args_list[0].kwargs["lines"]
        ban_lines = send_lines_mock.await_args_list[1].kwargs["lines"]
        tempban_lines = send_lines_mock.await_args_list[2].kwargs["lines"]
        grace_lines = send_lines_mock.await_args_list[3].kwargs["lines"]

        assert kick_lines == ["• <@42> · evento: allontanamento · avvenuto il 28/03/2026 18:17"]
        assert ban_lines == ["• <@43> · evento: ban · avvenuto il 28/03/2026 18:17"]
        assert tempban_lines == ["• <@44> · evento: tempban · avvenuto il 28/03/2026 18:17 · scade il 30/03/2026 19:17"]
        assert (
            grace_lines
            == [
                "• <@45> · evento: grace · grace iniziato il 28/03/2026 18:17 · grace scade il 29/03/2026 19:17 · tempban successivo: 2g · tempban previsto fino al 31/03/2026 19:17"
            ]
        )
        for line in [*kick_lines, *ban_lines, *tempban_lines, *grace_lines]:
            assert "Che peccato" not in line
            assert "Provvedimento registrato" not in line
            assert "espulso da" not in line

    asyncio.run(_run())
