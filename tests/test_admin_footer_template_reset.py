from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
from discord import app_commands

from app.services.footer import FooterService


class _Response:
    def is_done(self) -> bool:
        return False

    async def send_message(self, *args, **kwargs) -> None:
        return None


class _Followup:
    async def send(self, *args, **kwargs) -> None:
        return None


class _Interaction:
    def __init__(self, command) -> None:
        self.command = command
        self.guild_id = 1
        self.channel_id = 2
        self.guild = None
        self.channel = None
        self.response = _Response()
        self.followup = _Followup()
        self.user = SimpleNamespace(id=99, guild_permissions=SimpleNamespace(administrator=True), roles=[])


class _FooterDatabase:
    def __init__(self) -> None:
        self.settings: dict[str, str] = {}

    async def get_setting(self, key: str) -> str | None:
        return self.settings.get(key)

    async def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value

    async def delete_setting(self, key: str) -> None:
        self.settings.pop(key, None)

    async def execute(self, _query: str, _params: tuple[str, ...] = ()) -> None:
        return None

    async def fetchall(self, query: str, params: tuple[str, ...] = ()):
        prefix = str(params[0]).replace('%', '') if params else ''
        if 'FROM settings' not in query:
            return []
        return [
            {'key': key, 'value': value}
            for key, value in sorted(self.settings.items())
            if not prefix or key.startswith(prefix)
        ]


def _find_command(group: discord.app_commands.Group, *names: str):
    current = group
    for name in names[:-1]:
        current = next(cmd for cmd in current.commands if isinstance(cmd, discord.app_commands.Group) and cmd.name == name)
    return next(cmd for cmd in current.commands if cmd.name == names[-1])


@pytest.fixture
def admin_module(import_fresh):
    return import_fresh("app.plugins.commands_modular.admin")


def _register_admin_with_footer(admin_module):
    database = _FooterDatabase()
    footer = FooterService(database)
    ctx = SimpleNamespace(
        database=database,
        footer=footer,
        ai=None,
        guard=None,
        timezone=None,
        message_scheduler=None,
        backfill=None,
        retention=None,
        status=None,
        bot=None,
        config=None,
        entitlements=None,
        barcello_service=None,
        barcello_calibration_service=None,
        summary_service=None,
        ingest=None,
        voice_ingest=None,
        daily_resoconto=None,
        trigger_engine=None,
        activity_insights=None,
        inactivity=None,
        daily_activity_report=None,
        inactive_members_moderation=None,
        channel_summary=None,
        aura_eligibility=None,
        aura_rolling=None,
        member_flow_notifications=None,
    )
    admin_group = app_commands.Group(name="admin", description="admin")
    admin_module.register_admin(admin_group, ctx)
    footer_group = next(cmd for cmd in admin_group.commands if isinstance(cmd, discord.app_commands.Group) and cmd.name == "footer")
    return footer_group, ctx


def test_global_template_show_after_reset_reports_no_custom_override(admin_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(admin_module, "check_permission", AsyncMock(return_value=True))
        send_legacy = AsyncMock()
        monkeypatch.setattr(admin_module, "send_legacy_standard_response", send_legacy)

        footer_group, ctx = _register_admin_with_footer(admin_module)
        await ctx.footer.set_global_phrase("Frase custom")
        await ctx.footer.set_global_phrase(None)
        await ctx.footer.set_version("dev11")
        await ctx.footer.set_version(None)

        command = _find_command(footer_group, "template_global_show")
        await command.callback(_Interaction(command))

        kwargs = send_legacy.await_args.kwargs
        assert kwargs["path_parts"] == ["footer", "template_global_show"]
        assert kwargs["entries"] == [
            ("Version", "No custom override (default brand version in use)"),
            ("Phrase", "No custom override (default footer phrase in use)"),
        ]

    asyncio.run(_run())


def test_service_template_show_after_reset_reports_no_custom_override(admin_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(admin_module, "check_permission", AsyncMock(return_value=True))
        send_legacy = AsyncMock()
        monkeypatch.setattr(admin_module, "send_legacy_standard_response", send_legacy)

        footer_group, ctx = _register_admin_with_footer(admin_module)
        await ctx.footer.set_service_phrase("riassunto", "Frase servizio")
        await ctx.footer.set_service_phrase("riassunto", None)

        command = _find_command(footer_group, "template_service_show")
        await command.callback(_Interaction(command), "riassunto")

        kwargs = send_legacy.await_args.kwargs
        assert kwargs["path_parts"] == ["footer", "template_service_show"]
        assert kwargs["entries"] == [
            ("Service", "riassunto"),
            ("Phrase", "No custom override (service uses default footer behavior)"),
        ]

    asyncio.run(_run())


def test_reset_commands_return_standard_success_embed(admin_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(admin_module, "check_permission", AsyncMock(return_value=True))
        send_standard = AsyncMock()
        send_legacy = AsyncMock()
        monkeypatch.setattr(admin_module, "send_standard_response", send_standard)
        monkeypatch.setattr(admin_module, "send_legacy_standard_response", send_legacy)

        footer_group, ctx = _register_admin_with_footer(admin_module)
        await ctx.footer.set_version("2.0")
        await ctx.footer.set_global_phrase("Frase custom")
        await ctx.footer.set_service_phrase("riassunto", "Frase servizio")

        global_reset = _find_command(footer_group, "template_global_reset")
        await global_reset.callback(_Interaction(global_reset))
        service_reset = _find_command(footer_group, "template_service_reset")
        await service_reset.callback(_Interaction(service_reset), "riassunto")

        assert send_standard.await_count == 2
        first = send_standard.await_args_list[0].kwargs
        second = send_standard.await_args_list[1].kwargs
        assert first == {
            "top_level": "admin",
            "subcommand_path": "footer template_global_reset",
            "lines": [("result", "reset")],
            "sections": None,
            "kind": "success",
            "footer_service": ctx.footer,
            "ephemeral": True,
        }
        assert second == {
            "top_level": "admin",
            "subcommand_path": "footer template_service_reset",
            "lines": [("service", "riassunto"), ("result", "reset")],
            "sections": None,
            "kind": "success",
            "footer_service": ctx.footer,
            "ephemeral": True,
        }
        send_legacy.assert_not_awaited()

    asyncio.run(_run())
