import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

ctx_stub = types.ModuleType("app.plugins.commands_modular.ctx")
ctx_stub.CommandContext = object
sys.modules["app.plugins.commands_modular.ctx"] = ctx_stub

permissions_stub = types.ModuleType("app.plugins.commands_modular.permissions")
permissions_stub.check_permission = AsyncMock(return_value=True)
sys.modules["app.plugins.commands_modular.permissions"] = permissions_stub

helpers_stub = types.ModuleType("app.plugins.commands_modular.command_helpers")
helpers_stub.add_group_once = lambda parent, subgroup, logger: parent.add_command(subgroup)
helpers_stub.count_child_commands = lambda parent: len(getattr(parent, "commands", []))
sys.modules["app.plugins.commands_modular.command_helpers"] = helpers_stub

scheduler_stub = types.ModuleType("app.services.scheduler_utils")
scheduler_stub.calculate_initial_next_run = lambda now, ora_inizio, every, timezone: now
scheduler_stub.calculate_next_run_after_send = lambda now, every, timezone: now
sys.modules["app.services.scheduler_utils"] = scheduler_stub

module_path = Path(__file__).resolve().parents[1] / "app" / "plugins" / "commands_modular" / "messaggi.py"
spec = importlib.util.spec_from_file_location("messaggi_module_for_tests", module_path)
messaggi_module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(messaggi_module)


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


def test_campagne_test_guides_user_to_editorial_subcommand_when_id_is_service() -> None:
    async def _run() -> None:
        db = _FakeDb()
        db.message_campaign = None
        db.service_campaign = {"id": 7, "service_type": "WEATHER"}
        scheduler = _FakeScheduler()
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone="Europe/Rome")

        group = discord.app_commands.Group(name="campagne", description="x")
        permission_mock = AsyncMock(return_value=True)
        old_permission = messaggi_module.check_permission
        messaggi_module.check_permission = permission_mock
        try:
            messaggi_module.register_messaggi(group, ctx)
            callback = _get_command_callback(group, "test")
            interaction = _FakeInteraction()
            await callback(interaction, id=7)
        finally:
            messaggi_module.check_permission = old_permission

        interaction.response.send_message.assert_awaited_once_with(
            "Questo ID appartiene a un servizio editoriale. Usa /campagne servizi test.",
            ephemeral=True,
        )

    asyncio.run(_run())


def test_campagne_test_keeps_not_found_when_id_missing_everywhere() -> None:
    async def _run() -> None:
        db = _FakeDb()
        scheduler = _FakeScheduler()
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone="Europe/Rome")
        group = discord.app_commands.Group(name="campagne", description="x")

        permission_mock = AsyncMock(return_value=True)
        old_permission = messaggi_module.check_permission
        messaggi_module.check_permission = permission_mock
        try:
            messaggi_module.register_messaggi(group, ctx)
            callback = _get_command_callback(group, "test")
            interaction = _FakeInteraction()
            await callback(interaction, id=99)
        finally:
            messaggi_module.check_permission = old_permission

        interaction.response.send_message.assert_awaited_once_with("Campagna non trovata.", ephemeral=True)

    asyncio.run(_run())


def test_campagne_servizi_test_dispatches_by_service_type() -> None:
    async def _run() -> None:
        for service_type in ["WEATHER", "NEWS", "HOROSCOPE"]:
            db = _FakeDb()
            db.service_campaign = {"id": 3, "service_type": service_type}
            scheduler = _FakeScheduler()
            ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone="Europe/Rome")
            group = discord.app_commands.Group(name="campagne", description="x")

            permission_mock = AsyncMock(return_value=True)
            old_permission = messaggi_module.check_permission
            messaggi_module.check_permission = permission_mock
            try:
                messaggi_module.register_messaggi(group, ctx)
                servizi_group = _get_subgroup(group, "servizi")
                callback = _get_command_callback(servizi_group, "test")
                interaction = _FakeInteraction()
                await callback(interaction, id=3)
            finally:
                messaggi_module.check_permission = old_permission

            interaction.response.send_message.assert_awaited_once_with(
                "Invio test servizio editoriale in corso.",
                ephemeral=True,
            )
            assert scheduler._campaign_content_service.execute_weather_service.await_count == (1 if service_type == "WEATHER" else 0)
            assert scheduler._campaign_content_service.execute_news_service.await_count == (1 if service_type == "NEWS" else 0)
            assert scheduler._campaign_content_service.execute_horoscope_service.await_count == (1 if service_type == "HOROSCOPE" else 0)

    asyncio.run(_run())


def test_campagne_test_keeps_existing_behavior_for_message_campaign() -> None:
    async def _run() -> None:
        db = _FakeDb()
        db.message_campaign = {"id": 11, "text": "hello", "mood_mode": "AUTO"}
        scheduler = _FakeScheduler()
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone="Europe/Rome")
        group = discord.app_commands.Group(name="campagne", description="x")

        permission_mock = AsyncMock(return_value=True)
        old_permission = messaggi_module.check_permission
        messaggi_module.check_permission = permission_mock
        try:
            messaggi_module.register_messaggi(group, ctx)
            callback = _get_command_callback(group, "test")
            interaction = _FakeInteraction()
            await callback(interaction, id=11)
        finally:
            messaggi_module.check_permission = old_permission

        interaction.response.send_message.assert_awaited_once_with("Invio test in corso.", ephemeral=True)
        scheduler.send_campaign_embed.assert_awaited_once()

    asyncio.run(_run())
