import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest


@pytest.fixture
def messaggi_module(monkeypatch):
    commands_modular_pkg = types.ModuleType("app.plugins.commands_modular")
    commands_modular_pkg.__path__ = [str(Path(__file__).resolve().parents[1] / "app" / "plugins" / "commands_modular")]
    monkeypatch.setitem(sys.modules, "app.plugins.commands_modular", commands_modular_pkg)

    ctx_stub = types.ModuleType("app.plugins.commands_modular.ctx")
    ctx_stub.CommandContext = object
    monkeypatch.setitem(sys.modules, "app.plugins.commands_modular.ctx", ctx_stub)

    permissions_stub = types.ModuleType("app.plugins.commands_modular.permissions")
    permissions_stub.check_permission = AsyncMock(return_value=True)
    monkeypatch.setitem(sys.modules, "app.plugins.commands_modular.permissions", permissions_stub)

    helpers_stub = types.ModuleType("app.plugins.commands_modular.command_helpers")
    helpers_stub.add_group_once = lambda parent, subgroup, logger: parent.add_command(subgroup)
    helpers_stub.count_child_commands = lambda parent: len(getattr(parent, "commands", []))
    monkeypatch.setitem(sys.modules, "app.plugins.commands_modular.command_helpers", helpers_stub)

    scheduler_stub = types.ModuleType("app.services.scheduler_utils")
    scheduler_stub.calculate_initial_next_run = lambda now, ora_inizio, every, timezone: now
    scheduler_stub.calculate_next_run_after_send = lambda now, every, timezone: now
    scheduler_stub.ROME_TZ = object()
    monkeypatch.setitem(sys.modules, "app.services.scheduler_utils", scheduler_stub)

    command_embeds_stub = types.ModuleType("app.shared.discord.command_embeds")
    command_embeds_stub.CommandEmbedSection = lambda *args, **kwargs: {"args": args, "kwargs": kwargs}
    command_embeds_stub.CommandKind = str
    command_embeds_stub.send_standard_response = AsyncMock()
    monkeypatch.setitem(sys.modules, "app.shared.discord.command_embeds", command_embeds_stub)

    module_path = Path(__file__).resolve().parents[1] / "app" / "plugins" / "commands_modular" / "messaggi.py"
    spec = importlib.util.spec_from_file_location("messaggi_module_for_tests", module_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class _FakeDb:
    def __init__(self) -> None:
        self.message_campaign = None
        self.service_campaign = None

    async def get_message_campaign(self, guild_id: str, campaign_id: int):
        _ = guild_id, campaign_id
        return self.message_campaign

    async def get_campaign_content_config(self, guild_id: str, campaign_id: int):
        _ = guild_id, campaign_id
        return self.service_campaign

    async def get_campaign_content_config_by_service(self, guild_id: str, channel_id: str, service_type: str):
        _ = guild_id, channel_id
        if self.service_campaign and self.service_campaign.get("service_type") == service_type:
            return self.service_campaign
        return None

    async def get_message_channel_status(self, guild_id: str, channel_id: str):
        _ = guild_id, channel_id
        return True


class _FakeScheduler:
    def __init__(self) -> None:
        self.preview_campaign_text = AsyncMock(return_value=("ciao", None, None))
        self.send_campaign_embed = AsyncMock()
        self._campaign_content_service = SimpleNamespace(
            execute_news_service=AsyncMock(),
            execute_weather_service=AsyncMock(),
            execute_horoscope_service=AsyncMock(),
        )


class _FakeChannel(discord.abc.Messageable):
    async def _get_channel(self):
        return self

    async def send(self, *args, **kwargs):
        return SimpleNamespace(id=1)


class _FakeResponse:
    def __init__(self) -> None:
        self.send_message = AsyncMock()
        self.is_done = lambda: False


class _FakeInteraction:
    def __init__(self) -> None:
        self.guild_id = 1
        self.channel_id = 10
        self.channel = _FakeChannel()
        self.user = SimpleNamespace(id=55)
        self.response = _FakeResponse()


def _get_subgroup(group: discord.app_commands.Group, name: str):
    return next(cmd for cmd in group.commands if isinstance(cmd, discord.app_commands.Group) and cmd.name == name)


def _get_command_callback(group: discord.app_commands.Group, name: str):
    return next(cmd.callback for cmd in group.commands if cmd.name == name)


def test_custom_run_reports_not_found_when_campaign_missing(messaggi_module) -> None:
    async def _run() -> None:
        db = _FakeDb()
        scheduler = _FakeScheduler()
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone="Europe/Rome", footer=object())

        group = discord.app_commands.Group(name="campagne", description="x")
        messaggi_module.register_messaggi(group, ctx)
        custom_group = _get_subgroup(group, "custom")
        callback = _get_command_callback(custom_group, "run")
        interaction = _FakeInteraction()
        await callback(interaction, id=99)

        messaggi_module.send_standard_response.assert_awaited_once_with(
            interaction,
            top_level="admin",
            subcommand_path="campagne custom run",
            lines=[("warning", "Custom schedule not found.")],
            sections=None,
            kind="warning",
            footer_service=ctx.footer,
        )

    asyncio.run(_run())


def test_weather_run_dispatches_editorial_service(messaggi_module) -> None:
    async def _run() -> None:
        db = _FakeDb()
        db.service_campaign = {"id": 7, "service_type": "WEATHER"}
        scheduler = _FakeScheduler()
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone="Europe/Rome", footer=object())

        group = discord.app_commands.Group(name="campagne", description="x")
        messaggi_module.register_messaggi(group, ctx)
        weather_group = _get_subgroup(group, "weather")
        callback = _get_command_callback(weather_group, "run")
        interaction = _FakeInteraction()
        await callback(interaction)

        messaggi_module.send_standard_response.assert_awaited_once_with(
            interaction,
            top_level="admin",
            subcommand_path="campagne weather run",
            lines=[("channel", "<#10>"), ("result", "running")],
            sections=None,
            kind="success",
            footer_service=ctx.footer,
        )
        scheduler._campaign_content_service.execute_weather_service.assert_awaited_once_with(db.service_campaign)
        scheduler._campaign_content_service.execute_news_service.assert_not_called()
        scheduler._campaign_content_service.execute_horoscope_service.assert_not_called()

    asyncio.run(_run())


def test_service_runs_dispatch_by_service_type(messaggi_module) -> None:
    async def _run() -> None:
        for subgroup_name, service_type, attr_name in [
            ("weather", "WEATHER", "execute_weather_service"),
            ("news", "NEWS", "execute_news_service"),
            ("horoscope", "HOROSCOPE", "execute_horoscope_service"),
        ]:
            db = _FakeDb()
            db.service_campaign = {"id": 3, "service_type": service_type}
            scheduler = _FakeScheduler()
            ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone="Europe/Rome", footer=object())
            group = discord.app_commands.Group(name="campagne", description="x")

            messaggi_module.send_standard_response.reset_mock()
            messaggi_module.register_messaggi(group, ctx)
            subgroup = _get_subgroup(group, subgroup_name)
            callback = _get_command_callback(subgroup, "run")
            interaction = _FakeInteraction()
            await callback(interaction)

            getattr(scheduler._campaign_content_service, attr_name).assert_awaited_once_with(db.service_campaign)

    asyncio.run(_run())


def test_custom_run_keeps_existing_behavior_for_message_campaign(messaggi_module) -> None:
    async def _run() -> None:
        db = _FakeDb()
        db.message_campaign = {"id": 11, "type": "CUSTOM", "text": "hello", "mood_mode": "AUTO"}
        scheduler = _FakeScheduler()
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone="Europe/Rome", footer=object())
        group = discord.app_commands.Group(name="campagne", description="x")

        messaggi_module.register_messaggi(group, ctx)
        custom_group = _get_subgroup(group, "custom")
        callback = _get_command_callback(custom_group, "run")
        interaction = _FakeInteraction()
        await callback(interaction, id=11)

        messaggi_module.send_standard_response.assert_awaited_once_with(
            interaction,
            top_level="admin",
            subcommand_path="campagne custom run",
            lines=[("schedule_id", 11), ("result", "running")],
            sections=None,
            kind="success",
            footer_service=ctx.footer,
        )
        scheduler.preview_campaign_text.assert_awaited_once_with(db.message_campaign, channel_id_override="10")
        scheduler.send_campaign_embed.assert_awaited_once()

    asyncio.run(_run())


def test_custom_run_checks_permission_candidates_in_order(messaggi_module) -> None:
    async def _run() -> None:
        db = _FakeDb()
        db.message_campaign = {"id": 12, "type": "CUSTOM", "text": "hello", "mood_mode": "AUTO"}
        scheduler = _FakeScheduler()
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone="Europe/Rome", footer=object())
        group = discord.app_commands.Group(name="campagne", description="x")

        messaggi_module.check_permission.reset_mock()
        messaggi_module.check_permission.side_effect = [False, True]

        messaggi_module.register_messaggi(group, ctx)
        custom_group = _get_subgroup(group, "custom")
        callback = _get_command_callback(custom_group, "run")
        interaction = _FakeInteraction()
        await callback(interaction, id=12)

        assert [call.args[1] for call in messaggi_module.check_permission.await_args_list] == [
            "campagne.custom.run",
            "campagne.custom.entry_run",
        ]
        messaggi_module.send_standard_response.assert_awaited_once_with(
            interaction,
            top_level="admin",
            subcommand_path="campagne custom run",
            lines=[("schedule_id", 12), ("result", "running")],
            sections=None,
            kind="success",
            footer_service=ctx.footer,
        )
        scheduler.preview_campaign_text.assert_awaited_once_with(db.message_campaign, channel_id_override="10")

    asyncio.run(_run())
