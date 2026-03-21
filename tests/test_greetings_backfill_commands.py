from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

import app.plugins.commands_modular.greetings as greetings_module
from app.plugins.commands_modular.greetings import register_greetings
from app.services.greetings_backfill_service import GreetingsBackfillRunResult


def _interaction() -> SimpleNamespace:
    return SimpleNamespace(
        guild_id=1,
        guild=SimpleNamespace(id=1, name="Barcellometro"),
        channel=SimpleNamespace(id=99),
        response=SimpleNamespace(send_message=AsyncMock(), is_done=Mock(return_value=False), defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
        user=SimpleNamespace(guild_permissions=SimpleNamespace(administrator=True)),
    )


def _backfill_group(group: discord.app_commands.Group) -> discord.app_commands.Group:
    return next(command for command in group.commands if isinstance(command, discord.app_commands.Group) and command.name == "backfill")


def _subcommand(group: discord.app_commands.Group, name: str):
    return next(command for command in group.commands if command.name == name)


def test_greetings_backfill_subgroup_exists() -> None:
    group = discord.app_commands.Group(name="greetings", description="x")
    ctx = SimpleNamespace(database=Mock(), footer=None, greetings_backfill=Mock())

    register_greetings(group, ctx)

    names = {command.name for command in group.commands}
    assert "backfill" in names
    nested = _backfill_group(group)
    assert {command.name for command in nested.commands} == {"on", "off", "status", "run"}


def test_greetings_backfill_on_off_status_and_run_commands() -> None:
    async def _run() -> None:
        group = discord.app_commands.Group(name="greetings", description="x")
        service = SimpleNamespace(
            set_enabled=AsyncMock(),
            status=AsyncMock(
                return_value={
                    "enabled": True,
                    "last_run_at": "2026-03-20T14:00:00+00:00",
                    "canonical_count": 9,
                    "last_run_imported_count": 7,
                    "last_run_skipped_count": 2,
                }
            ),
            is_enabled=AsyncMock(return_value=True),
            run_once=AsyncMock(
                return_value=GreetingsBackfillRunResult(
                    imported_count=7,
                    skipped_count=2,
                    canonical_count=9,
                    last_run_at="2026-03-20T14:00:00+00:00",
                )
            ),
        )
        ctx = SimpleNamespace(database=Mock(), footer=None, greetings_backfill=service)
        old_permission = greetings_module.check_permission
        old_send = greetings_module.send_standard_response
        greetings_module.check_permission = AsyncMock(return_value=True)
        greetings_module.send_standard_response = AsyncMock()
        try:
            register_greetings(group, ctx)
            backfill = _backfill_group(group)
            await _subcommand(backfill, "on").callback(_interaction())
            await _subcommand(backfill, "off").callback(_interaction())
            await _subcommand(backfill, "status").callback(_interaction())
            run_interaction = _interaction()
            await _subcommand(backfill, "run").callback(run_interaction)

            assert service.set_enabled.await_args_list[0].args == (True,)
            assert service.set_enabled.await_args_list[1].args == (False,)
            service.status.assert_awaited_once_with("1")
            service.run_once.assert_awaited_once_with(guild_id="1")
            run_interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)

            calls = greetings_module.send_standard_response.await_args_list
            assert [call.kwargs["subcommand_path"] for call in calls] == [
                "greetings backfill on",
                "greetings backfill off",
                "greetings backfill status",
                "greetings backfill run",
            ]
            assert calls[2].kwargs["lines"] == [
                ("enabled", "on"),
                ("last_run_at", "2026-03-20T14:00:00+00:00"),
                ("canonical_records", 9),
                ("last_run_imported", 7),
                ("last_run_skipped", 2),
            ]
            assert calls[3].kwargs["lines"] == [
                ("imported", 7),
                ("skipped", 2),
                ("canonical_records", 9),
                ("last_run_at", "2026-03-20T14:00:00+00:00"),
            ]
        finally:
            greetings_module.check_permission = old_permission
            greetings_module.send_standard_response = old_send

    asyncio.run(_run())


def test_greetings_backfill_run_requires_enabled_service() -> None:
    async def _run() -> None:
        group = discord.app_commands.Group(name="greetings", description="x")
        service = SimpleNamespace(
            is_enabled=AsyncMock(return_value=False),
            run_once=AsyncMock(),
        )
        ctx = SimpleNamespace(database=Mock(), footer=None, greetings_backfill=service)
        old_permission = greetings_module.check_permission
        old_send = greetings_module.send_standard_response
        greetings_module.check_permission = AsyncMock(return_value=True)
        greetings_module.send_standard_response = AsyncMock()
        try:
            register_greetings(group, ctx)
            backfill = _backfill_group(group)
            interaction = _interaction()
            await _subcommand(backfill, "run").callback(interaction)

            service.run_once.assert_not_called()
            interaction.response.defer.assert_not_called()
            kwargs = greetings_module.send_standard_response.await_args.kwargs
            assert kwargs["subcommand_path"] == "greetings backfill run"
            assert kwargs["kind"] == "warning"
            assert kwargs["lines"] == [("error", "backfill disabled"), ("action", "enable it first")]
        finally:
            greetings_module.check_permission = old_permission
            greetings_module.send_standard_response = old_send

    asyncio.run(_run())
