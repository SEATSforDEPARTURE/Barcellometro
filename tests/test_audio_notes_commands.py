import importlib.util
import asyncio
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

settings_stub = types.ModuleType("app.plugins.commands_modular.settings")


async def _set_setting(ctx, key: str, value: str) -> None:
    await ctx.database.set_setting(key, value)


async def _get_setting(ctx, key: str, default: str) -> str:
    value = await ctx.database.get_setting(key)
    return value if value is not None else default


settings_stub.set_setting = _set_setting
settings_stub.get_setting = _get_setting
sys.modules["app.plugins.commands_modular.settings"] = settings_stub

module_path = Path(__file__).resolve().parents[1] / "app" / "plugins" / "commands_modular" / "audio_notes.py"
spec = importlib.util.spec_from_file_location("audio_notes_module_for_tests", module_path)
audio_notes_module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(audio_notes_module)
register_audio_notes = audio_notes_module.register_audio_notes


class _FakeDatabase:
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._values = dict(initial or {})
        self.set_calls: list[tuple[str, str]] = []

    async def get_setting(self, key: str):
        return self._values.get(key)

    async def set_setting(self, key: str, value: str) -> None:
        self._values[key] = value
        self.set_calls.append((key, value))


class _FakeInteractionResponse:
    def __init__(self) -> None:
        self.send_message = AsyncMock()


class _FakeInteraction:
    def __init__(self) -> None:
        self.response = _FakeInteractionResponse()


def _get_command_callback(group: discord.app_commands.Group, name: str):
    for cmd in group.commands:
        if cmd.name == name:
            return cmd.callback
    raise AssertionError(f"Command {name} not found")


def test_audio_notes_limits_updates_only_passed_fields() -> None:
    async def _run() -> None:
        db = _FakeDatabase({"audio_notes.max_duration_s": "180", "audio_notes.discord_max_chars": "1900", "audio_notes.queue_max": "50"})
        ctx = SimpleNamespace(database=db)
        group = discord.app_commands.Group(name="audio_notes", description="audio notes")
        register_audio_notes(group, ctx)

        callback = _get_command_callback(group, "limits")
        interaction = _FakeInteraction()
        await callback(
            interaction,
            max_mb=30,
            max_duration_s=None,
            discord_max_chars=None,
            queue_max=None,
            chars_summary=1200,
        )

        assert db._values["audio_notes.max_mb"] == "30"
        assert db._values["audio_notes.chars_summary"] == "1200"
        assert db._values["audio_notes.max_duration_s"] == "180"
        assert db.set_calls == [("audio_notes.max_mb", "30"), ("audio_notes.chars_summary", "1200")]

    asyncio.run(_run())


def test_audio_notes_limits_all_none_returns_status_without_write() -> None:
    async def _run() -> None:
        db = _FakeDatabase({
            "audio_notes.max_mb": "25",
            "audio_notes.max_duration_s": "180",
            "audio_notes.discord_max_chars": "1900",
            "audio_notes.queue_max": "50",
            "audio_notes.chars_summary": "1500",
        })
        ctx = SimpleNamespace(database=db)
        group = discord.app_commands.Group(name="audio_notes", description="audio notes")
        register_audio_notes(group, ctx)

        callback = _get_command_callback(group, "limits")
        interaction = _FakeInteraction()
        await callback(interaction, max_mb=None, max_duration_s=None, discord_max_chars=None, queue_max=None, chars_summary=None)

        assert db.set_calls == []
        call = interaction.response.send_message.await_args
        assert "Valori correnti audio notes" in call.args[0]

    asyncio.run(_run())


def test_audio_notes_limits_chars_summary_non_positive_disables_feature() -> None:
    async def _run() -> None:
        db = _FakeDatabase({"audio_notes.chars_summary": "1300"})
        ctx = SimpleNamespace(database=db)
        group = discord.app_commands.Group(name="audio_notes", description="audio notes")
        register_audio_notes(group, ctx)

        callback = _get_command_callback(group, "limits")
        interaction = _FakeInteraction()
        await callback(interaction, max_mb=None, max_duration_s=None, discord_max_chars=None, queue_max=None, chars_summary=0)

        assert db._values["audio_notes.chars_summary"] == ""
        assert ("audio_notes.chars_summary", "") in db.set_calls

    asyncio.run(_run())
