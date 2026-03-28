from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest


class _FakeDatabase:
    def __init__(self) -> None:
        self.config: dict[str, object] = {
            "enabled": 1,
            "cooldown_days": 14,
            "invite_url": None,
            "grace_template": None,
            "tempban_template": None,
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
        await _find_command(users_group, "dms", "cooldown_set").callback(interaction, 21)
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
        assert as_map["cooldown_days"] == 14
        assert as_map["invite_url"] == "not set"
        assert as_map["dm_sent_ok"] == 1
        assert as_map["dm_sent_fail"] == 1
        assert as_map["dm_sent_skipped"] == 0
        assert as_map["dm_events_by_type"] == "grace=1, tempban=1"
        assert "user=11" in as_map["last_success"]
        assert "user=12" in as_map["last_fail"]

    asyncio.run(_run())
