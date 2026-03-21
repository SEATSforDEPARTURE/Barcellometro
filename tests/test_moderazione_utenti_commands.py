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
    assert '@greetings_group.command(name="template_set"' in greetings
    assert '@greetings_group.command(name="template_show"' in greetings
    assert '@greetings_group.command(name="template_reset"' in greetings
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
        "template_set",
        "template_show",
        "template_reset",
        "user_card_set",
        "user_card_show",
        "user_card_reset",
    }
    assert "preview" not in names


def test_greetings_template_show_with_type_renders_template_and_preview_sections() -> None:
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
            template_show_cmd = next(command for command in group.commands if command.name == "template_show")
            mock_build = AsyncMock(return_value=["embed"])
            mock_send = AsyncMock()
            old_build = greetings_module.build_command_embeds
            old_send = greetings_module.send_command_embeds
            greetings_module.build_command_embeds = mock_build
            greetings_module.send_command_embeds = mock_send
            interaction = SimpleNamespace(
                guild_id=1,
                guild=SimpleNamespace(id=1, name="Barcellometro"),
                channel=SimpleNamespace(id=99),
                response=SimpleNamespace(send_message=AsyncMock(), is_done=Mock(return_value=False)),
                followup=SimpleNamespace(send=AsyncMock()),
                user=SimpleNamespace(
                    id=7,
                    name="Mod",
                    display_name="Moderator",
                    mention="<@7>",
                    guild_permissions=SimpleNamespace(administrator=True),
                ),
            )

            await template_show_cmd.callback(interaction, type="kick")

            sections = mock_build.await_args.kwargs["sections"]
            assert mock_build.await_args.kwargs["subcommand_path"] == "greetings template_show"
            assert mock_build.await_args.kwargs["subtitle_args"] == ["kick"]
            assert [section.title for section in sections] == ["Template", "Preview"]
            assert sections[0].lines == ["Kick notice for {display_name} by {moderator}."]
            assert sections[1].lines == ["Kick notice for New User by Moderator."]
            assert mock_send.await_count == 1
            assert mock_send.await_args.kwargs["files"] is None
        finally:
            greetings_module.build_command_embeds = old_build
            greetings_module.send_command_embeds = old_send
            greetings_module.check_permission = old_permission
            await db.close()

    asyncio.run(_run())


def test_greetings_template_show_with_type_uses_render_preview_helper() -> None:
    async def _run() -> None:
        group = discord.app_commands.Group(name="greetings", description="x")
        ctx = SimpleNamespace(
            database=SimpleNamespace(get_moderation_templates=AsyncMock(return_value={"template_kick_reason": "Configured"})),
            footer=None,
        )
        old_permission = greetings_module.check_permission
        old_render_preview = greetings_module._render_preview
        old_build = greetings_module.build_command_embeds
        old_send = greetings_module.send_command_embeds
        greetings_module.check_permission = AsyncMock(return_value=True)
        greetings_module._render_preview = AsyncMock(return_value=("Configured", "Rendered"))
        greetings_module.build_command_embeds = AsyncMock(return_value=["embed"])
        greetings_module.send_command_embeds = AsyncMock()
        try:
            register_greetings(group, ctx)
            template_show_cmd = next(command for command in group.commands if command.name == "template_show")
            interaction = SimpleNamespace(
                guild_id=1,
                guild=SimpleNamespace(id=1, name="Barcellometro"),
                channel=SimpleNamespace(id=99),
                response=SimpleNamespace(send_message=AsyncMock(), is_done=Mock(return_value=False)),
                followup=SimpleNamespace(send=AsyncMock()),
                user=SimpleNamespace(guild_permissions=SimpleNamespace(administrator=True)),
            )

            await template_show_cmd.callback(interaction, type="kick")

            greetings_module._render_preview.assert_awaited_once_with(ctx, interaction, "kick")
        finally:
            greetings_module.check_permission = old_permission
            greetings_module._render_preview = old_render_preview
            greetings_module.build_command_embeds = old_build
            greetings_module.send_command_embeds = old_send

    asyncio.run(_run())


def test_greetings_template_show_rejects_invalid_type_with_standard_error() -> None:
    async def _run() -> None:
        group = discord.app_commands.Group(name="greetings", description="x")
        ctx = SimpleNamespace(
            database=SimpleNamespace(get_moderation_templates=AsyncMock(return_value={})),
            footer=None,
        )
        old_permission = greetings_module.check_permission
        old_send_standard = greetings_module.send_standard_response
        greetings_module.check_permission = AsyncMock(return_value=True)
        greetings_module.send_standard_response = AsyncMock()
        try:
            register_greetings(group, ctx)
            template_show_cmd = next(command for command in group.commands if command.name == "template_show")
            interaction = SimpleNamespace(
                guild_id=1,
                guild=SimpleNamespace(id=1, name="Barcellometro"),
                channel=SimpleNamespace(id=99),
                response=SimpleNamespace(send_message=AsyncMock(), is_done=Mock(return_value=False)),
                followup=SimpleNamespace(send=AsyncMock()),
                user=SimpleNamespace(guild_permissions=SimpleNamespace(administrator=True)),
            )

            await template_show_cmd.callback(interaction, type="unknown")

            assert greetings_module.send_standard_response.await_count == 1
            kwargs = greetings_module.send_standard_response.await_args.kwargs
            assert kwargs["subcommand_path"] == "greetings template_show"
            assert kwargs["kind"] == "error"
            assert kwargs["lines"] == [("error", "Invalid type. Use inactivity, kick, ban, tempban, grace.")]
        finally:
            greetings_module.check_permission = old_permission
            greetings_module.send_standard_response = old_send_standard

    asyncio.run(_run())


def test_greetings_template_show_without_type_keeps_overview_templates() -> None:
    async def _run() -> None:
        group = discord.app_commands.Group(name="greetings", description="x")
        templates = {
            "template_inactivity_reason": "Inactivity template",
            "template_kick_reason": "Kick template",
            "template_ban_reason": "Ban template",
            "template_tempban_reason": "Tempban template",
            "template_grace_reason": "Grace template",
        }
        ctx = SimpleNamespace(
            database=SimpleNamespace(get_moderation_templates=AsyncMock(return_value=templates)),
            footer=None,
        )
        old_permission = greetings_module.check_permission
        old_build = greetings_module.build_command_embeds
        old_send = greetings_module.send_command_embeds
        old_render_preview = greetings_module._render_preview
        greetings_module.check_permission = AsyncMock(return_value=True)
        greetings_module.build_command_embeds = AsyncMock(return_value=["embed"])
        greetings_module.send_command_embeds = AsyncMock()
        greetings_module._render_preview = AsyncMock()
        try:
            register_greetings(group, ctx)
            template_show_cmd = next(command for command in group.commands if command.name == "template_show")
            interaction = SimpleNamespace(
                guild_id=1,
                guild=SimpleNamespace(id=1, name="Barcellometro"),
                channel=SimpleNamespace(id=99),
                response=SimpleNamespace(send_message=AsyncMock(), is_done=Mock(return_value=False)),
                followup=SimpleNamespace(send=AsyncMock()),
                user=SimpleNamespace(guild_permissions=SimpleNamespace(administrator=True)),
            )

            await template_show_cmd.callback(interaction)

            greetings_module._render_preview.assert_not_called()
            sections = greetings_module.build_command_embeds.await_args.kwargs["sections"]
            assert len(sections) == 1
            assert sections[0].title == "Templates"
            assert sections[0].lines == [
                ("Inactivity", "Inactivity template"),
                ("Kick", "Kick template"),
                ("Ban", "Ban template"),
                ("Tempban", "Tempban template"),
                ("Grace", "Grace template"),
            ]
            assert greetings_module.build_command_embeds.await_args.kwargs["subcommand_path"] == "greetings template_show"
        finally:
            greetings_module.check_permission = old_permission
            greetings_module.build_command_embeds = old_build
            greetings_module.send_command_embeds = old_send
            greetings_module._render_preview = old_render_preview

    asyncio.run(_run())
