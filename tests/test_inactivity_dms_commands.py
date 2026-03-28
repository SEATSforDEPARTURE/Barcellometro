from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest


class _FakeDatabase:
    def __init__(self) -> None:
        self.config: dict[str, object] = {
            "dm_reminders_enabled": 1,
            "reminder_cooldown_days": 14,
            "invite_url": None,
            "dm_reminder_template": None,
        }
        self.set_dm_enabled_calls: list[tuple[str, bool]] = []
        self.stats_payload = {
            "total": 2,
            "ok": 1,
            "fail": 1,
            "skipped": 0,
            "by_event": [{"event_type": "reminder", "total": 2}],
            "latest_success": {"user_id": "11", "sent_at": "2026-01-01T10:00:00+00:00", "reason": "ok"},
            "latest_fail": {"user_id": "12", "sent_at": "2026-01-01T11:00:00+00:00", "reason": "fail", "error_summary": "Forbidden"},
        }
        self.events_payload = [
            {
                "user_id": "11",
                "event_type": "reminder",
                "reason": "ok",
                "sent_at": "2026-01-01T10:00:00+00:00",
                "outcome": "success",
                "error_summary": None,
            }
        ]

    async def get_inactivity_config(self, guild_id: str):
        _ = guild_id
        return self.config

    async def upsert_inactivity_config(self, guild_id: str, **fields):
        _ = guild_id
        self.config.update(fields)

    async def set_inactivity_dm_reminders_enabled(self, guild_id: str, enabled: bool) -> None:
        self.set_dm_enabled_calls.append((guild_id, enabled))
        self.config["dm_reminders_enabled"] = 1 if enabled else 0

    async def get_inactivity_dm_delivery_stats(self, guild_id: str):
        _ = guild_id
        return self.stats_payload

    async def list_inactivity_dm_delivery_events(self, guild_id: str, *, limit: int = 10):
        _ = guild_id
        _ = limit
        return self.events_payload

    async def list_inactivity_role_policies(self, guild_id: str):
        _ = guild_id
        return []


@pytest.fixture
def inattivi_module(import_fresh):
    return import_fresh("app.plugins.commands_modular.inattivi")


def _find_command(group: discord.app_commands.Group, *path: str):
    current = group
    for idx, name in enumerate(path):
        found = next(command for command in current.commands if command.name == name)
        if idx == len(path) - 1:
            return found
        current = found
    raise AssertionError(path)


def test_inactivity_dms_on_off_and_status(inattivi_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        db = _FakeDatabase()
        send_response = AsyncMock()
        monkeypatch.setattr(inattivi_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(inattivi_module, "send_standard_response", send_response)

        ctx = SimpleNamespace(database=db, footer=None, author=None)
        inactivity_group = discord.app_commands.Group(name="inactivity", description="inactivity")
        inattivi_module.register_inattivi(inactivity_group, ctx)

        on_callback = _find_command(inactivity_group, "dms", "on").callback
        off_callback = _find_command(inactivity_group, "dms", "off").callback
        status_callback = _find_command(inactivity_group, "dms", "status").callback

        interaction = SimpleNamespace(guild_id=123, guild=None)
        await on_callback(interaction)
        await off_callback(interaction)
        await status_callback(interaction)

        assert db.set_dm_enabled_calls == [("123", True), ("123", False)]
        status_lines = send_response.await_args_list[-1].kwargs["lines"]
        as_map = {key: value for key, value in status_lines}
        assert as_map["dms"] == "off"
        assert as_map["cooldown_days"] == 14
        assert as_map["invite_url"] == "not set"
        assert as_map["dm_sent_ok"] == 1
        assert as_map["dm_sent_fail"] == 1
        assert as_map["dm_sent_skipped"] == 0
        assert as_map["dm_events_by_type"] == "reminder=2"
        assert "user=11" in as_map["last_success"]
        assert "user=12" in as_map["last_fail"]

    asyncio.run(_run())
