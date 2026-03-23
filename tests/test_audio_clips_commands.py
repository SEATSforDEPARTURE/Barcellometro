from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest


class _FakeDatabase:
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self.values = dict(initial or {})
        self.set_calls: list[tuple[str, str]] = []
        self.delete_calls: list[str] = []

    async def get_setting(self, key: str):
        return self.values.get(key)

    async def set_setting(self, key: str, value: str) -> None:
        self.values[key] = value
        self.set_calls.append((key, value))

    async def delete_setting(self, key: str) -> None:
        self.values.pop(key, None)
        self.delete_calls.append(key)


@pytest.fixture
def stt_module(import_fresh):
    return import_fresh("app.plugins.commands_modular.stt")


@pytest.fixture
def translate_module(import_fresh):
    return import_fresh("app.plugins.commands_modular.translate")


def _get_command_callback(group: discord.app_commands.Group, name: str):
    for cmd in group.commands:
        if cmd.name == name:
            return cmd.callback
    raise AssertionError(f"Command {name} not found")


def test_audio_clips_stt_set_uses_canonical_permission_and_path(stt_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        db = _FakeDatabase({"stt.local.compute_type": "int8"})
        ctx = SimpleNamespace(database=db, footer=None)
        clips_group = discord.app_commands.Group(name="clips", description="clips")

        async def _get_setting(ctx, key: str, default: str) -> str:
            value = await db.get_setting(key)
            return default if value is None else value

        async def _set_setting(ctx, key: str, value: str) -> None:
            await db.set_setting(key, value)

        seen_permissions: list[str] = []

        async def _check_permission(interaction, command_name, ctx):
            seen_permissions.append(command_name)
            return True

        monkeypatch.setattr(stt_module, "check_permission", _check_permission)
        monkeypatch.setattr(stt_module, "get_setting", AsyncMock(side_effect=_get_setting))
        monkeypatch.setattr(stt_module, "set_setting", AsyncMock(side_effect=_set_setting))
        monkeypatch.setattr(stt_module, "reset_setting", AsyncMock())
        send_response = AsyncMock()
        monkeypatch.setattr(stt_module, "send_standard_response", send_response)

        stt_module.register_stt(clips_group, ctx)
        callback = _get_command_callback(clips_group, "stt_set")
        await callback(
            SimpleNamespace(),
            backend=SimpleNamespace(value="ai"),
            model=None,
            compute=SimpleNamespace(value="float16"),
            beam=None,
            language=None,
        )

        assert seen_permissions == ["audio.clips.stt_set"]
        assert db.set_calls == [("stt.backend", "ai"), ("stt.local.compute_type", "float16")]
        kwargs = send_response.await_args.kwargs
        assert kwargs["subcommand_path"] == "audio clips stt_set"
        assert kwargs["visual_top_level"] == "audio"

    asyncio.run(_run())


def test_audio_clips_translate_reset_clears_overrides_and_returns_canonical_path(translate_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        db = _FakeDatabase({"translate.backend": "ai", "translate.target_lang": "it"})
        ctx = SimpleNamespace(database=db, footer=None)
        clips_group = discord.app_commands.Group(name="clips", description="clips")

        async def _get_setting(ctx, key: str, default: str) -> str:
            value = await db.get_setting(key)
            return default if value is None else value

        async def _reset_setting(ctx, key: str) -> None:
            await db.delete_setting(key)

        seen_permissions: list[str] = []

        async def _check_permission(interaction, command_name, ctx):
            seen_permissions.append(command_name)
            return True

        monkeypatch.setattr(translate_module, "check_permission", _check_permission)
        monkeypatch.setattr(translate_module, "get_setting", AsyncMock(side_effect=_get_setting))
        monkeypatch.setattr(translate_module, "set_setting", AsyncMock())
        monkeypatch.setattr(translate_module, "reset_setting", AsyncMock(side_effect=_reset_setting))
        send_response = AsyncMock()
        monkeypatch.setattr(translate_module, "send_standard_response", send_response)

        translate_module.register_translate(clips_group, ctx)
        callback = _get_command_callback(clips_group, "translate_reset")
        await callback(SimpleNamespace())

        assert seen_permissions == ["audio.clips.translate_reset"]
        assert db.delete_calls == ["translate.backend", "translate.target_lang"]
        kwargs = send_response.await_args.kwargs
        assert kwargs["subcommand_path"] == "audio clips translate_reset"
        assert kwargs["visual_top_level"] == "audio"

    asyncio.run(_run())
