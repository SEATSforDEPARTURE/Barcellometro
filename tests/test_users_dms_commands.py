from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from app.services.users_moderation_dms import USERS_DM_SUPPORTED_PLACEHOLDERS


class _FakeDatabase:
    def __init__(self) -> None:
        self.config: dict[str, object] = {
            "enabled": 1,
            "cooldown_days": 14,
            "cooldown_seconds": 14 * 86400,
            "invite_url": None,
            "grace_template": None,
            "tempban_template": None,
            "kick_template": None,
            "ban_template": None,
        }
        self.set_enabled_calls: list[tuple[str, bool]] = []
        self.stats_payload = {
            "total": 2,
            "ok": 1,
            "fail": 1,
            "skipped": 0,
            "by_event": [{"event_type": "grace", "total": 1}, {"event_type": "tempban", "total": 1}],
            "latest_success": {"user_id": "11", "sent_at": "2026-01-01T10:00:00+00:00", "reason": "ok"},
            "latest_fail": {"user_id": "12", "sent_at": "2026-01-01T11:00:00+00:00", "reason": "fail", "error_summary": "Forbidden"},
        }
        self.events_payload = [
            {
                "user_id": "11",
                "event_type": "grace",
                "reason": "ok",
                "sent_at": "2026-01-01T10:00:00+00:00",
                "outcome": "success",
                "error_summary": None,
            }
        ]

    async def get_users_dm_config(self, guild_id: str):
        _ = guild_id
        return self.config

    async def upsert_users_dm_config(self, guild_id: str, **fields):
        _ = guild_id
        self.config.update(fields)

    async def set_users_dm_enabled(self, guild_id: str, enabled: bool) -> None:
        self.set_enabled_calls.append((guild_id, enabled))
        self.config["enabled"] = 1 if enabled else 0

    async def get_users_dm_delivery_stats(self, guild_id: str):
        _ = guild_id
        return self.stats_payload

    async def list_users_dm_delivery_events(self, guild_id: str, *, limit: int = 10):
        _ = guild_id
        _ = limit
        return self.events_payload


@pytest.fixture
def users_module(import_fresh):
    return import_fresh("app.plugins.commands_modular.moderazione_utenti")


def _find_command(group: discord.app_commands.Group, *path: str):
    current = group
    for idx, name in enumerate(path):
        found = next(command for command in current.commands if command.name == name)
        if idx == len(path) - 1:
            return found
        current = found
    raise AssertionError(path)


def test_users_dms_on_off_status_and_settings(users_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        db = _FakeDatabase()
        send_response = AsyncMock()
        monkeypatch.setattr(users_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(users_module, "send_standard_response", send_response)

        ctx = SimpleNamespace(
            database=db,
            footer=None,
            author=None,
            member_flow_notifications=None,
            barcello_service=None,
            config=SimpleNamespace(),
        )
        users_group = discord.app_commands.Group(name="users", description="users")
        users_module.register_moderazione_utenti(users_group, ctx)

        interaction = SimpleNamespace(guild_id=123, guild=SimpleNamespace(id=123), user=SimpleNamespace(id=1))

        await _find_command(users_group, "dms", "on").callback(interaction)
        await _find_command(users_group, "dms", "off").callback(interaction)
        await _find_command(users_group, "dms", "template_grace_set").callback(interaction, "Grace {user}")
        await _find_command(users_group, "dms", "template_grace_show").callback(interaction)
        await _find_command(users_group, "dms", "template_grace_reset").callback(interaction)
        await _find_command(users_group, "dms", "template_tempban_set").callback(interaction, "Tempban {user}")
        await _find_command(users_group, "dms", "template_tempban_show").callback(interaction)
        await _find_command(users_group, "dms", "template_tempban_reset").callback(interaction)
        await _find_command(users_group, "dms", "template_kick_set").callback(interaction, "Kick {user}")
        await _find_command(users_group, "dms", "template_kick_show").callback(interaction)
        await _find_command(users_group, "dms", "template_kick_reset").callback(interaction)
        await _find_command(users_group, "dms", "template_ban_set").callback(interaction, "Ban {user}")
        await _find_command(users_group, "dms", "template_ban_show").callback(interaction)
        await _find_command(users_group, "dms", "template_ban_reset").callback(interaction)
        await _find_command(users_group, "dms", "cooldown_set").callback(interaction, 30, discord.app_commands.Choice(name="secondi", value="secondi"))
        await _find_command(users_group, "dms", "cooldown_set").callback(interaction, 5, discord.app_commands.Choice(name="minuti", value="minuti"))
        await _find_command(users_group, "dms", "cooldown_set").callback(interaction, 2, discord.app_commands.Choice(name="ore", value="ore"))
        await _find_command(users_group, "dms", "cooldown_set").callback(interaction, 3, discord.app_commands.Choice(name="giorni", value="giorni"))
        await _find_command(users_group, "dms", "cooldown_set").callback(interaction, 1, discord.app_commands.Choice(name="settimane", value="settimane"))
        await _find_command(users_group, "dms", "cooldown_set").callback(interaction, 0, discord.app_commands.Choice(name="secondi", value="secondi"))
        await _find_command(users_group, "dms", "cooldown_show").callback(interaction)
        await _find_command(users_group, "dms", "cooldown_reset").callback(interaction)
        await _find_command(users_group, "dms", "invite_set").callback(interaction, "https://discord.gg/test")
        await _find_command(users_group, "dms", "invite_show").callback(interaction)
        await _find_command(users_group, "dms", "invite_reset").callback(interaction)
        await _find_command(users_group, "dms", "status").callback(interaction)

        assert db.set_enabled_calls == [("123", True), ("123", False)]

        status_lines = send_response.await_args_list[-1].kwargs["lines"]
        as_map = {key: value for key, value in status_lines}
        assert as_map["dms"] == "off"
        assert as_map["template_grace"] == "not set"
        assert as_map["template_tempban"] == "not set"
        assert as_map["template_kick"] == "not set"
        assert as_map["template_ban"] == "not set"
        assert as_map["cooldown"] == "disabled (0 seconds)"
        assert as_map["cooldown_seconds"] == 0
        assert as_map["cooldown_disabled"] == "yes"
        assert as_map["invite_url"] == "not set"
        assert as_map["dm_sent_ok"] == 1
        assert as_map["dm_sent_fail"] == 1
        assert as_map["dm_sent_skipped"] == 0
        assert as_map["dm_events_by_type"] == "grace=1, tempban=1"
        assert "user=11" in as_map["last_success"]
        assert "user=12" in as_map["last_fail"]
        sections = send_response.await_args_list[-1].kwargs["sections"]
        assert sections[1].title == "Supported placeholders"
        assert sections[1].lines == [f"{{{name}}}" for name in USERS_DM_SUPPORTED_PLACEHOLDERS]
        assert "{mention}" in sections[1].lines
        assert "{now_it}" in sections[1].lines
        assert "{expires_at_it}" in sections[1].lines
        assert "{reason_text}" in sections[1].lines

        cooldown_set_calls = [call for call in send_response.await_args_list if call.kwargs.get("subcommand_path") == "users dms cooldown_set"]
        assert len(cooldown_set_calls) == 6
        assert cooldown_set_calls[0].kwargs["lines"][1] == ("cooldown_seconds", 30)
        assert cooldown_set_calls[1].kwargs["lines"][1] == ("cooldown_seconds", 300)
        assert cooldown_set_calls[2].kwargs["lines"][1] == ("cooldown_seconds", 7200)
        assert cooldown_set_calls[3].kwargs["lines"][1] == ("cooldown_seconds", 259200)
        assert cooldown_set_calls[4].kwargs["lines"][1] == ("cooldown_seconds", 604800)
        assert cooldown_set_calls[5].kwargs["lines"][0] == ("cooldown", "disabled (0 seconds)")

        cooldown_show_call = next(call for call in send_response.await_args_list if call.kwargs.get("subcommand_path") == "users dms cooldown_show")
        show_map = {key: value for key, value in cooldown_show_call.kwargs["lines"]}
        assert show_map["cooldown_disabled"] == "yes"

        cooldown_reset_call = next(call for call in send_response.await_args_list if call.kwargs.get("subcommand_path") == "users dms cooldown_reset")
        reset_map = {key: value for key, value in cooldown_reset_call.kwargs["lines"]}
        assert reset_map["cooldown_seconds"] == 0
        assert reset_map["cooldown_disabled"] == "yes"

    asyncio.run(_run())


def test_users_tempban_preview_is_safe_and_resolves_ban_days(users_module) -> None:
    template = "Tempban di {ban_days} giorni per {user}. {reason_line}{invite_line}"
    preview = users_module._render_users_dm_template_preview(template)
    assert "Template render error" not in preview
    assert "{ban_days}" not in preview
    assert "{user}" not in preview
    assert "periodo di grazia manuale scaduto" in preview
    assert "Reason:" not in preview
    assert "Manual grace expired" not in preview
    assert "2" in preview


def test_users_kick_and_ban_preview_are_safe(users_module) -> None:
    kick_preview = users_module._render_users_dm_template_preview("Kick {user} {reason_line}", event_type="kick")
    ban_preview = users_module._render_users_dm_template_preview("Ban {user} {reason_line}", event_type="ban")
    assert "Template render error" not in kick_preview
    assert "Template render error" not in ban_preview
    assert "ExampleUser" in kick_preview
    assert "Repeated abusive language" in kick_preview
    assert "ExampleUser" in ban_preview
    assert "Severe harassment" in ban_preview


def test_users_preview_unknown_placeholder_does_not_crash(users_module) -> None:
    preview = users_module._render_users_dm_template_preview("Hello {user} {unknown_placeholder}")
    assert "Template render error" not in preview
    assert "{unknown_placeholder}" not in preview
    assert "ExampleUser" in preview
