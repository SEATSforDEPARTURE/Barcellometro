from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from app.services.inactivity_dm_templates import INACTIVITY_DM_SUPPORTED_PLACEHOLDERS


class _FakeDatabase:
    def __init__(self) -> None:
        self.config: dict[str, object] = {
            "dm_reminders_enabled": 1,
            "reminder_cooldown_days": 14,
            "reminder_cooldown_seconds": 14 * 86400,
            "invite_url": None,
            "template_grace": None,
            "template_tempban": None,
            "dm_reminder_template": None,
            "dm_kick_template": None,
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
        assert as_map["template_grace"] == "not set"
        assert as_map["template_tempban"] == "not set"
        assert as_map["cooldown"] == "2 settimane"
        assert as_map["cooldown_seconds"] == 14 * 86400
        assert as_map["cooldown_disabled"] == "no"
        assert as_map["invite_url"] == "not set"
        assert as_map["dm_sent_ok"] == 1
        assert as_map["dm_sent_fail"] == 1
        assert as_map["dm_sent_skipped"] == 0
        assert as_map["dm_events_by_type"] == "reminder=2"
        assert "user=11" in as_map["last_success"]
        assert "user=12" in as_map["last_fail"]
        sections = send_response.await_args_list[-1].kwargs["sections"]
        assert sections[0].title == "Recent DM deliveries"
        assert "event=reminder" in sections[0].lines[0]
        assert sections[1].title == "Supported placeholders"
        assert sections[1].lines == [f"{{{name}}}" for name in INACTIVITY_DM_SUPPORTED_PLACEHOLDERS]
        assert "{mention}" in sections[1].lines
        assert "{now_it}" in sections[1].lines
        assert "{expires_at_it}" in sections[1].lines

    asyncio.run(_run())


def test_inactivity_dms_template_commands_are_registered_with_final_surface(inattivi_module) -> None:
    inactivity_group = discord.app_commands.Group(name="inactivity", description="inactivity")
    ctx = SimpleNamespace(database=_FakeDatabase(), footer=None, author=None)
    inattivi_module.register_inattivi(inactivity_group, ctx)

    dms_group = _find_command(inactivity_group, "dms")
    names = {command.name for command in dms_group.commands}
    assert names == {
        "on",
        "off",
        "status",
        "template_grace_set",
        "template_grace_show",
        "template_grace_reset",
        "template_tempban_set",
        "template_tempban_show",
        "template_tempban_reset",
        "cooldown_set",
        "cooldown_show",
        "cooldown_reset",
        "invite_set",
        "invite_show",
        "invite_reset",
    }
    assert "template_reminder_set" not in names
    assert "template_reminder_show" not in names
    assert "template_reminder_reset" not in names


def test_inactivity_dms_template_grace_and_tempban_set_show_reset(inattivi_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        db = _FakeDatabase()
        send_response = AsyncMock()
        monkeypatch.setattr(inattivi_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(inattivi_module, "send_standard_response", send_response)

        ctx = SimpleNamespace(database=db, footer=None, author=None)
        inactivity_group = discord.app_commands.Group(name="inactivity", description="inactivity")
        inattivi_module.register_inattivi(inactivity_group, ctx)

        interaction = SimpleNamespace(guild_id=123, guild=None)
        await _find_command(inactivity_group, "dms", "template_grace_set").callback(interaction, "Grace {user}")
        await _find_command(inactivity_group, "dms", "template_grace_show").callback(interaction)
        await _find_command(inactivity_group, "dms", "template_grace_reset").callback(interaction)
        await _find_command(inactivity_group, "dms", "template_tempban_set").callback(interaction, "Tempban {user}")
        await _find_command(inactivity_group, "dms", "template_tempban_show").callback(interaction)
        await _find_command(inactivity_group, "dms", "template_tempban_reset").callback(interaction)

        assert db.config["template_grace"] is None
        assert db.config["template_tempban"] is None
        sent_paths = [call.kwargs["subcommand_path"] for call in send_response.await_args_list]
        assert "inactivity dms template_grace_show" in sent_paths
        assert "inactivity dms template_tempban_show" in sent_paths

    asyncio.run(_run())


def test_inactivity_dms_cooldown_set_supports_all_units_and_disable(inattivi_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        db = _FakeDatabase()
        send_response = AsyncMock()
        monkeypatch.setattr(inattivi_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(inattivi_module, "send_standard_response", send_response)

        ctx = SimpleNamespace(database=db, footer=None, author=None)
        inactivity_group = discord.app_commands.Group(name="inactivity", description="inactivity")
        inattivi_module.register_inattivi(inactivity_group, ctx)
        interaction = SimpleNamespace(guild_id=123, guild=None)

        await _find_command(inactivity_group, "dms", "cooldown_set").callback(interaction, 30, discord.app_commands.Choice(name="secondi", value="secondi"))
        await _find_command(inactivity_group, "dms", "cooldown_set").callback(interaction, 5, discord.app_commands.Choice(name="minuti", value="minuti"))
        await _find_command(inactivity_group, "dms", "cooldown_set").callback(interaction, 2, discord.app_commands.Choice(name="ore", value="ore"))
        await _find_command(inactivity_group, "dms", "cooldown_set").callback(interaction, 3, discord.app_commands.Choice(name="giorni", value="giorni"))
        await _find_command(inactivity_group, "dms", "cooldown_set").callback(interaction, 1, discord.app_commands.Choice(name="settimane", value="settimane"))
        await _find_command(inactivity_group, "dms", "cooldown_set").callback(interaction, 0, discord.app_commands.Choice(name="secondi", value="secondi"))
        await _find_command(inactivity_group, "dms", "cooldown_show").callback(interaction)
        await _find_command(inactivity_group, "dms", "cooldown_reset").callback(interaction)

        cooldown_set_calls = [call for call in send_response.await_args_list if call.kwargs.get("subcommand_path") == "inactivity dms cooldown_set"]
        assert len(cooldown_set_calls) == 6
        assert cooldown_set_calls[0].kwargs["lines"][1] == ("cooldown_seconds", 30)
        assert cooldown_set_calls[1].kwargs["lines"][1] == ("cooldown_seconds", 300)
        assert cooldown_set_calls[2].kwargs["lines"][1] == ("cooldown_seconds", 7200)
        assert cooldown_set_calls[3].kwargs["lines"][1] == ("cooldown_seconds", 259200)
        assert cooldown_set_calls[4].kwargs["lines"][1] == ("cooldown_seconds", 604800)
        assert cooldown_set_calls[5].kwargs["lines"][0] == ("cooldown", "disabled (0 seconds)")

        show_call = next(call for call in send_response.await_args_list if call.kwargs.get("subcommand_path") == "inactivity dms cooldown_show")
        show_map = {key: value for key, value in show_call.kwargs["lines"]}
        assert show_map["cooldown_seconds"] == 0
        assert show_map["cooldown_disabled"] == "yes"

        reset_call = next(call for call in send_response.await_args_list if call.kwargs.get("subcommand_path") == "inactivity dms cooldown_reset")
        reset_map = {key: value for key, value in reset_call.kwargs["lines"]}
        assert reset_map["cooldown_seconds"] == 0
        assert reset_map["cooldown_disabled"] == "yes"

    asyncio.run(_run())


def test_inactivity_dms_status_falls_back_to_legacy_templates(inattivi_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        db = _FakeDatabase()
        db.config.update(
            {
                "template_grace": None,
                "template_tempban": None,
                "dm_reminder_template": "Legacy reminder",
                "dm_kick_template": "Legacy tempban",
            }
        )
        send_response = AsyncMock()
        monkeypatch.setattr(inattivi_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(inattivi_module, "send_standard_response", send_response)

        ctx = SimpleNamespace(database=db, footer=None, author=None)
        inactivity_group = discord.app_commands.Group(name="inactivity", description="inactivity")
        inattivi_module.register_inattivi(inactivity_group, ctx)

        interaction = SimpleNamespace(guild_id=123, guild=None)
        await _find_command(inactivity_group, "dms", "status").callback(interaction)

        status_lines = send_response.await_args_list[-1].kwargs["lines"]
        as_map = {key: value for key, value in status_lines}
        assert as_map["template_grace"] == "Legacy reminder"
        assert as_map["template_tempban"] == "Legacy tempban"

    asyncio.run(_run())


def test_inactivity_dms_docs_inventory_matches_final_contract() -> None:
    docs = Path("docs/command_tree_report.md").read_text()

    for action in (
        "on",
        "off",
        "status",
        "template_grace_set",
        "template_grace_show",
        "template_grace_reset",
        "template_tempban_set",
        "template_tempban_show",
        "template_tempban_reset",
        "cooldown_set",
        "cooldown_show",
        "cooldown_reset",
        "invite_set",
        "invite_show",
        "invite_reset",
    ):
        assert f"| `inactivity` | `dms` | `{action}` |" in docs

    assert "| `inactivity` | `dms` | `template_reminder_set` |" not in docs
    assert "| `inactivity` | `dms` | `template_reminder_show` |" not in docs
    assert "| `inactivity` | `dms` | `template_reminder_reset` |" not in docs


def test_command_standards_pin_inactivity_dms_surface_and_legacy_policy() -> None:
    standards = Path("docs/command_standards.md").read_text()

    assert "## 10. Contratto canonico `/inactivity dms`" in standards
    assert "/inactivity dms template_grace_set" in standards
    assert "/inactivity dms template_tempban_set" in standards
    assert "`template_reminder_*`" in standards
    assert "`dm_reminder_template`, `dm_kick_template`" in standards


def test_inactivity_dms_cooldown_set_uses_quantity_and_unit_parameters(inattivi_module) -> None:
    inactivity_group = discord.app_commands.Group(name="inactivity", description="inactivity")
    ctx = SimpleNamespace(database=_FakeDatabase(), footer=None, author=None)
    inattivi_module.register_inattivi(inactivity_group, ctx)
    cooldown_set = _find_command(inactivity_group, "dms", "cooldown_set")
    param_names = [param.name for param in cooldown_set.parameters]
    assert param_names == ["quantity", "unit"]
    assert "days" not in param_names


def test_inactivity_tempban_preview_is_safe_and_resolves_ban_days(inattivi_module) -> None:
    template = "Ban di {ban_days} giorni per {user}. {reason_line}{invite_line}"
    preview = inattivi_module._render_template_preview(template)
    assert "Template render error" not in preview
    assert "{ban_days}" not in preview
    assert "{user}" not in preview
    assert "periodo di grazia per inattività scaduto" in preview
    assert "Reason:" not in preview
    assert "Inactivity" not in preview
    assert "7" in preview


def test_preview_behavior_is_consistent_between_users_and_inactivity(import_fresh) -> None:
    users_module = import_fresh("app.plugins.commands_modular.moderazione_utenti")
    inattivi_module = import_fresh("app.plugins.commands_modular.inattivi")
    template = "Hi {user} {unknown_placeholder}"
    users_preview = users_module._render_users_dm_template_preview(template)
    inactivity_preview = inattivi_module._render_template_preview(template)
    assert "Template render error" not in users_preview
    assert "Template render error" not in inactivity_preview
    assert "{unknown_placeholder}" not in users_preview
    assert "{unknown_placeholder}" not in inactivity_preview
    assert users_preview.startswith("Hi @ExampleUser")
    assert inactivity_preview.startswith("Hi @ExampleUser")
