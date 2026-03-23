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
def audio_notes_module(import_fresh):
    return import_fresh("app.plugins.commands_modular.audio_notes")


def _register_group(module, db: _FakeDatabase):
    ctx = SimpleNamespace(database=db, footer=None)
    audio_group = discord.app_commands.Group(name="audio", description="audio")
    clips_group = discord.app_commands.Group(name="clips", description="clips")
    audio_group.add_command(clips_group)
    register = module.register_audio_notes
    register(audio_group, ctx, clips_group=clips_group)
    return ctx, audio_group, clips_group


def _get_command_callback(group: discord.app_commands.Group, name: str):
    for cmd in group.commands:
        if cmd.name == name:
            return cmd.callback
    raise AssertionError(f"Command {name} not found")


def _install_audio_notes_mocks(monkeypatch: pytest.MonkeyPatch, module, db: _FakeDatabase) -> AsyncMock:
    async def _get_setting(ctx, key: str, default: str) -> str:
        value = await db.get_setting(key)
        return default if value is None else value

    async def _set_setting(ctx, key: str, value: str) -> None:
        await db.set_setting(key, value)

    async def _reset_setting(ctx, key: str) -> None:
        await db.delete_setting(key)

    monkeypatch.setattr(module, "check_permission", AsyncMock(return_value=True))
    monkeypatch.setattr(module, "get_setting", AsyncMock(side_effect=_get_setting))
    monkeypatch.setattr(module, "set_setting", AsyncMock(side_effect=_set_setting))
    monkeypatch.setattr(module, "reset_setting", AsyncMock(side_effect=_reset_setting))
    send_response = AsyncMock()
    monkeypatch.setattr(module, "send_legacy_standard_response", send_response)
    return send_response


def test_audio_limits_set_updates_only_passed_fields(audio_notes_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        db = _FakeDatabase({"audio_notes.max_duration_s": "180", "audio_notes.discord_max_chars": "1900", "audio_notes.queue_max": "50"})
        send_response = _install_audio_notes_mocks(monkeypatch, audio_notes_module, db)
        _, _, clips_group = _register_group(audio_notes_module, db)

        callback = _get_command_callback(clips_group, "limits_set")
        await callback(SimpleNamespace(), max_mb=30, max_duration_s=None, discord_max_chars=None, queue_max=None, chars_summary=1200)

        assert db.values["audio_notes.max_mb"] == "30"
        assert db.values["audio_notes.chars_summary"] == "1200"
        assert db.values["audio_notes.max_duration_s"] == "180"
        assert db.set_calls == [("audio_notes.max_mb", "30"), ("audio_notes.chars_summary", "1200")]
        kwargs = send_response.await_args.kwargs
        assert send_response.await_count == 1
        assert kwargs["path_parts"] == ["audio", "clips", "limits_set"]
        assert kwargs["tone"] == "success"
        assert kwargs["entries"] == [("Status", "updated")]
        assert kwargs["service_name"] == "audio_notes"

    asyncio.run(_run())


def test_audio_status_reads_current_values_and_does_not_crash(audio_notes_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        db = _FakeDatabase(
            {
                "audio_notes.enabled": "true",
                "audio_notes.max_mb": "42",
                "audio_notes.max_duration_s": "360",
                "audio_notes.discord_max_chars": "2500",
                "audio_notes.queue_max": "99",
                "audio_notes.chars_summary": "1800",
                "stt.backend": "ai",
                "stt.local.model": "large-v3",
                "stt.local.compute_type": "float16",
                "stt.local.beam_size": "5",
                "stt.local.language_hint": "it",
                "translate.backend": "local",
                "translate.target_lang": "it",
            }
        )
        send_response = _install_audio_notes_mocks(monkeypatch, audio_notes_module, db)
        _, audio_group, _ = _register_group(audio_notes_module, db)

        callback = _get_command_callback(audio_group, "status")
        await callback(SimpleNamespace())

        kwargs = send_response.await_args.kwargs
        assert kwargs["path_parts"] == ["audio", "status"]
        assert kwargs["entries"] == [("Enabled", True)]
        assert ("Chars Summary", "1800") in kwargs["sections"][0][1]
        assert ("Backend", "ai") in kwargs["sections"][1][1]
        assert ("Target", "it") in kwargs["sections"][2][1]

    asyncio.run(_run())


def test_audio_limits_show_reads_current_values_and_does_not_crash(audio_notes_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        db = _FakeDatabase(
            {
                "audio_notes.enabled": "true",
                "audio_notes.max_mb": "42",
                "audio_notes.max_duration_s": "360",
                "audio_notes.discord_max_chars": "2500",
                "audio_notes.queue_max": "99",
                "audio_notes.chars_summary": "1800",
            }
        )
        send_response = _install_audio_notes_mocks(monkeypatch, audio_notes_module, db)
        _, _, clips_group = _register_group(audio_notes_module, db)

        callback = _get_command_callback(clips_group, "limits_show")
        await callback(SimpleNamespace())

        kwargs = send_response.await_args.kwargs
        assert kwargs["path_parts"] == ["audio", "clips", "limits_show"]
        assert ("Max Mb", "42") in kwargs["entries"]
        assert ("Chars Summary", "1800") in kwargs["entries"]

    asyncio.run(_run())


def test_audio_limits_set_with_all_none_returns_without_write(audio_notes_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        db = _FakeDatabase(
            {
                "audio_notes.max_mb": "25",
                "audio_notes.max_duration_s": "180",
                "audio_notes.discord_max_chars": "1900",
                "audio_notes.queue_max": "50",
                "audio_notes.chars_summary": "1500",
            }
        )
        send_response = _install_audio_notes_mocks(monkeypatch, audio_notes_module, db)
        _, _, clips_group = _register_group(audio_notes_module, db)

        callback = _get_command_callback(clips_group, "limits_set")
        await callback(SimpleNamespace(), max_mb=None, max_duration_s=None, discord_max_chars=None, queue_max=None, chars_summary=None)

        assert db.set_calls == []
        kwargs = send_response.await_args.kwargs
        assert kwargs["tone"] == "warning"
        assert ("Reason", "No changes provided") in kwargs["entries"]

    asyncio.run(_run())


def test_audio_limits_set_chars_summary_non_positive_disables_feature(audio_notes_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        db = _FakeDatabase({"audio_notes.chars_summary": "1300"})
        _install_audio_notes_mocks(monkeypatch, audio_notes_module, db)
        _, _, clips_group = _register_group(audio_notes_module, db)

        callback = _get_command_callback(clips_group, "limits_set")
        await callback(SimpleNamespace(), max_mb=None, max_duration_s=None, discord_max_chars=None, queue_max=None, chars_summary=0)

        assert db.values["audio_notes.chars_summary"] == ""
        assert ("audio_notes.chars_summary", "") in db.set_calls

    asyncio.run(_run())


def test_audio_limits_set_returns_updated_config_after_write(audio_notes_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        db = _FakeDatabase(
            {
                "audio_notes.max_mb": "25",
                "audio_notes.max_duration_s": "180",
                "audio_notes.discord_max_chars": "1900",
                "audio_notes.queue_max": "50",
                "audio_notes.chars_summary": "",
            }
        )
        send_response = _install_audio_notes_mocks(monkeypatch, audio_notes_module, db)
        _, _, clips_group = _register_group(audio_notes_module, db)

        callback = _get_command_callback(clips_group, "limits_set")
        await callback(SimpleNamespace(), max_mb=30, max_duration_s=None, discord_max_chars=2100, queue_max=None, chars_summary=None)

        assert db.values["audio_notes.max_mb"] == "30"
        assert db.values["audio_notes.discord_max_chars"] == "2100"
        kwargs = send_response.await_args.kwargs
        assert kwargs["path_parts"] == ["audio", "clips", "limits_set"]
        assert kwargs["tone"] == "success"
        assert kwargs["entries"] == [("Status", "updated")]
        sections = kwargs["sections"]
        config_section = sections[0]
        assert config_section[0] == "Config"
        assert ("Discord Max Chars", "2100") in config_section[1]

    asyncio.run(_run())


def test_audio_limits_reset_clears_stored_settings(audio_notes_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        db = _FakeDatabase({"audio_notes.max_mb": "42", "audio_notes.queue_max": "99"})
        _install_audio_notes_mocks(monkeypatch, audio_notes_module, db)
        _, _, clips_group = _register_group(audio_notes_module, db)

        callback = _get_command_callback(clips_group, "limits_reset")
        await callback(SimpleNamespace())

        assert "audio_notes.max_mb" in db.delete_calls
        assert "audio_notes.queue_max" in db.delete_calls

    asyncio.run(_run())


def test_audio_limits_reset_returns_defaults_after_reset(audio_notes_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        db = _FakeDatabase({"audio_notes.max_mb": "42", "audio_notes.queue_max": "99"})
        send_response = _install_audio_notes_mocks(monkeypatch, audio_notes_module, db)
        _, _, clips_group = _register_group(audio_notes_module, db)

        callback = _get_command_callback(clips_group, "limits_reset")
        await callback(SimpleNamespace())

        kwargs = send_response.await_args.kwargs
        assert kwargs["tone"] == "success"
        assert kwargs["path_parts"] == ["audio", "clips", "limits_reset"]
        config_entries = kwargs["sections"][0][1]
        assert ("Queue Max", "50") in config_entries
        assert ("Chars Summary", "off") in config_entries

    asyncio.run(_run())
