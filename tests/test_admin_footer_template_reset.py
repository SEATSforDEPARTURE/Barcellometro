from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
from discord import app_commands

from app.services.author import AuthorService
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
def embed_module(import_fresh):
    return import_fresh("app.plugins.commands_modular.embed")


def _register_embed_with_footer(embed_module):
    database = _FooterDatabase()
    footer = FooterService(database)
    author = AuthorService(database)
    ctx = SimpleNamespace(
        database=database,
        footer=footer,
        author=author,
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
    embed_group = app_commands.Group(name="embed", description="embed")
    embed_module.register_embed(embed_group, ctx)
    footer_group = next(cmd for cmd in embed_group.commands if isinstance(cmd, discord.app_commands.Group) and cmd.name == "footer")
    return embed_group, footer_group, ctx


def test_embed_footer_registers_under_top_level_embed_only(embed_module) -> None:
    embed_group, footer_group, _ = _register_embed_with_footer(embed_module)
    author_group = next(cmd for cmd in embed_group.commands if isinstance(cmd, discord.app_commands.Group) and cmd.name == "author")

    assert embed_group.name == "embed"
    assert {group.name for group in embed_group.commands if isinstance(group, discord.app_commands.Group)} == {"footer", "author"}
    assert footer_group.name == "footer"
    assert {command.name for command in footer_group.commands} == {
        "on",
        "off",
        "status",
        "template_global_set",
        "template_global_show",
        "template_global_reset",
        "template_service_set",
        "template_service_show",
        "template_service_reset",
    }
    assert {command.name for command in author_group.commands} == {
        "on",
        "off",
        "status",
        "template_global_set",
        "template_global_show",
        "template_global_reset",
        "template_service_set",
        "template_service_show",
        "template_service_reset",
    }


def test_admin_namespace_no_longer_registers_footer_commands(import_fresh) -> None:
    admin_module = import_fresh("app.plugins.commands_modular.admin")
    admin_group = app_commands.Group(name="admin", description="admin")
    ctx = SimpleNamespace(database=SimpleNamespace(), footer=None, ai=None)
    admin_module.register_admin(admin_group, ctx)

    assert all(
        not (isinstance(command, discord.app_commands.Group) and command.name == "footer")
        for command in admin_group.commands
    )


def _section_payload(kwargs: dict, index: int = 0):
    section = kwargs["sections"][index]
    return section.title, section.lines


def test_global_template_show_after_reset_reports_no_custom_override(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, "check_permission", AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, "send_standard_response", send_standard)

        embed_group, footer_group, ctx = _register_embed_with_footer(embed_module)
        await ctx.footer.set_global_phrase("Frase custom")
        await ctx.footer.set_global_phrase(None)
        await ctx.footer.set_version("dev11")
        await ctx.footer.set_version(None)
        await ctx.footer.set_global_thumbnail("https://example.com/footer.png")
        await ctx.footer.set_global_thumbnail(None)

        command = _find_command(footer_group, "template_global_show")
        await command.callback(_Interaction(command))

        kwargs = send_standard.await_args.kwargs
        assert kwargs["top_level"] == "embed"
        assert kwargs["subcommand_path"] == "footer template_global_show"
        assert kwargs["lines"] is None
        assert kwargs["kind"] == "info"
        assert _section_payload(kwargs) == (
            "Template",
            [
                ("Version", "No custom override (default brand version in use)"),
                ("Phrase", "No custom override (default footer phrase in use)"),
                ("Thumbnail", "No custom override (default footer thumbnail in use)"),
            ],
        )

    asyncio.run(_run())


def test_service_template_show_after_reset_reports_no_custom_override(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, "check_permission", AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, "send_standard_response", send_standard)

        embed_group, footer_group, ctx = _register_embed_with_footer(embed_module)
        await ctx.footer.set_service_phrase("riassunto", "Frase servizio")
        await ctx.footer.set_service_phrase("riassunto", None)
        await ctx.footer.set_service_thumbnail("riassunto", "https://example.com/service.png")
        await ctx.footer.set_service_thumbnail("riassunto", None)

        command = _find_command(footer_group, "template_service_show")
        await command.callback(_Interaction(command), "riassunto")

        kwargs = send_standard.await_args.kwargs
        assert kwargs["subcommand_path"] == "footer template_service_show"
        assert kwargs["subtitle_args"] == ["riassunto"]
        assert _section_payload(kwargs) == (
            "Template",
            [
                ("Phrase", "No custom override (service uses default footer behavior)"),
                ("Thumbnail", "No custom override (service uses default footer thumbnail behavior)"),
            ],
        )

    asyncio.run(_run())


def test_reset_commands_return_standard_success_embed(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, "check_permission", AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, "send_standard_response", send_standard)

        embed_group, footer_group, ctx = _register_embed_with_footer(embed_module)
        await ctx.footer.set_version("2.0")
        await ctx.footer.set_global_phrase("Frase custom")
        await ctx.footer.set_global_thumbnail("https://example.com/global.png")
        await ctx.footer.set_service_phrase("riassunto", "Frase servizio")
        await ctx.footer.set_service_thumbnail("riassunto", "https://example.com/service.png")

        global_reset = _find_command(footer_group, "template_global_reset")
        await global_reset.callback(_Interaction(global_reset))
        service_reset = _find_command(footer_group, "template_service_reset")
        await service_reset.callback(_Interaction(service_reset), "riassunto")

        assert send_standard.await_count == 2
        first = send_standard.await_args_list[0].kwargs
        second = send_standard.await_args_list[1].kwargs
        assert first == {
            "top_level": "embed",
            "subcommand_path": "footer template_global_reset",
            "subtitle_args": None,
            "lines": [("result", "reset")],
            "sections": None,
            "kind": "success",
            "footer_service": ctx.footer,
            "footer_service_name": "status",
            "ephemeral": True,
        }
        assert second == {
            "top_level": "embed",
            "subcommand_path": "footer template_service_reset",
            "subtitle_args": ["riassunto"],
            "lines": [("result", "reset")],
            "sections": None,
            "kind": "success",
            "footer_service": ctx.footer,
            "footer_service_name": "status",
            "ephemeral": True,
        }
        assert await ctx.footer.get_version() is None
        assert await ctx.footer.get_global_phrase() is None
        assert await ctx.footer.get_global_thumbnail() is None
        assert (await ctx.footer.get_service_phrases()).get("riassunto") is None
        assert (await ctx.footer.get_service_thumbnails()).get("riassunto") is None

    asyncio.run(_run())


def test_template_global_set_saves_version_phrase_and_thumbnail(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, "check_permission", AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, "send_standard_response", send_standard)

        embed_group, footer_group, ctx = _register_embed_with_footer(embed_module)
        command = _find_command(footer_group, "template_global_set")
        await command.callback(
            _Interaction(command),
            version="2.4",
            phrase="Footer globale",
            thumbnail="<:melon:1475962151502876695>",
        )

        kwargs = send_standard.await_args.kwargs
        assert kwargs["subcommand_path"] == "footer template_global_set"
        assert kwargs["lines"] == [("result", "updated")]
        assert _section_payload(kwargs) == (
            "Template",
            [
                ("Version", "2.4"),
                ("Phrase", "Footer globale"),
                ("Thumbnail", "https://cdn.discordapp.com/emojis/1475962151502876695.png"),
            ],
        )
        assert await ctx.footer.get_version() == "2.4"
        assert await ctx.footer.get_global_phrase() == "Footer globale"
        assert await ctx.footer.get_global_thumbnail() == "https://cdn.discordapp.com/emojis/1475962151502876695.png"

    asyncio.run(_run())


def test_template_global_set_updates_only_thumbnail(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, "check_permission", AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, "send_standard_response", send_standard)

        embed_group, footer_group, ctx = _register_embed_with_footer(embed_module)
        await ctx.footer.set_version("2.4")
        await ctx.footer.set_global_phrase("Footer globale")

        command = _find_command(footer_group, "template_global_set")
        await command.callback(_Interaction(command), thumbnail="https://example.com/new-thumb.png")

        kwargs = send_standard.await_args.kwargs
        assert _section_payload(kwargs) == (
            "Template",
            [
                ("Version", "2.4"),
                ("Phrase", "Footer globale"),
                ("Thumbnail", "https://example.com/new-thumb.png"),
            ],
        )
        assert await ctx.footer.get_version() == "2.4"
        assert await ctx.footer.get_global_phrase() == "Footer globale"
        assert await ctx.footer.get_global_thumbnail() == "https://example.com/new-thumb.png"

    asyncio.run(_run())


def test_template_service_set_accepts_thumbnail_without_phrase(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, "check_permission", AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, "send_standard_response", send_standard)

        embed_group, footer_group, ctx = _register_embed_with_footer(embed_module)
        command = _find_command(footer_group, "template_service_set")
        await command.callback(_Interaction(command), "riassunto", thumbnail="<a:pulse:1475962151502876696>")

        kwargs = send_standard.await_args.kwargs
        assert kwargs["subtitle_args"] == ["riassunto"]
        assert kwargs["lines"] == [("result", "updated")]
        assert _section_payload(kwargs) == (
            "Template",
            [
                ("Phrase", "(not set)"),
                ("Thumbnail", "https://cdn.discordapp.com/emojis/1475962151502876696.gif"),
            ],
        )
        assert (await ctx.footer.get_service_phrases()).get("riassunto") is None
        assert (await ctx.footer.get_service_thumbnails()).get("riassunto") == "https://cdn.discordapp.com/emojis/1475962151502876696.gif"

    asyncio.run(_run())


def test_template_global_show_displays_thumbnail_field(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, "check_permission", AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, "send_standard_response", send_standard)

        embed_group, footer_group, ctx = _register_embed_with_footer(embed_module)
        await ctx.footer.set_version("9.9")
        await ctx.footer.set_global_phrase("Globale")
        await ctx.footer.set_global_thumbnail("https://example.com/global.png")

        command = _find_command(footer_group, "template_global_show")
        await command.callback(_Interaction(command))

        kwargs = send_standard.await_args.kwargs
        assert _section_payload(kwargs) == (
            "Template",
            [
                ("Version", "9.9"),
                ("Phrase", "Globale"),
                ("Thumbnail", "https://example.com/global.png"),
            ],
        )

    asyncio.run(_run())


def test_template_service_show_displays_thumbnail_field(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, "check_permission", AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, "send_standard_response", send_standard)

        embed_group, footer_group, ctx = _register_embed_with_footer(embed_module)
        await ctx.footer.set_service_phrase("riassunto", "Servizio")
        await ctx.footer.set_service_thumbnail("riassunto", "https://example.com/service.png")

        command = _find_command(footer_group, "template_service_show")
        await command.callback(_Interaction(command), "riassunto")

        kwargs = send_standard.await_args.kwargs
        assert kwargs["subtitle_args"] == ["riassunto"]
        assert _section_payload(kwargs) == (
            "Template",
            [
                ("Phrase", "Servizio"),
                ("Thumbnail", "https://example.com/service.png"),
            ],
        )

    asyncio.run(_run())


def test_template_admin_set_invalid_thumbnail_returns_standard_error(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, "check_permission", AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, "send_standard_response", send_standard)

        embed_group, footer_group, ctx = _register_embed_with_footer(embed_module)
        global_command = _find_command(footer_group, "template_global_set")
        await global_command.callback(_Interaction(global_command), thumbnail="bad-value")

        global_kwargs = send_standard.await_args.kwargs
        assert global_kwargs["subcommand_path"] == "footer template_global_set"
        assert global_kwargs["lines"] == [("reason", "Thumbnail must be a Discord custom emoji or an http/https image URL")]
        assert global_kwargs["kind"] == "error"
        assert await ctx.footer.get_global_thumbnail() is None

        send_standard.reset_mock()

        service_command = _find_command(footer_group, "template_service_set")
        await service_command.callback(_Interaction(service_command), "riassunto", thumbnail="bad-value")

        service_kwargs = send_standard.await_args.kwargs
        assert service_kwargs["subcommand_path"] == "footer template_service_set"
        assert service_kwargs["subtitle_args"] == ["riassunto"]
        assert service_kwargs["lines"] == [("reason", "Thumbnail must be a Discord custom emoji or an http/https image URL")]
        assert service_kwargs["kind"] == "error"
        assert (await ctx.footer.get_service_thumbnails()).get("riassunto") is None

    asyncio.run(_run())


def test_author_global_template_show_after_reset_reports_no_custom_override(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, "check_permission", AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, "send_standard_response", send_standard)

        embed_group, _footer_group, ctx = _register_embed_with_footer(embed_module)
        author_group = next(cmd for cmd in embed_group.commands if isinstance(cmd, discord.app_commands.Group) and cmd.name == "author")
        await ctx.author.set_global_phrase("Linea author")
        await ctx.author.set_global_phrase(None)
        await ctx.author.set_version("v3")
        await ctx.author.set_version(None)
        await ctx.author.set_global_thumbnail("https://example.com/author.png")
        await ctx.author.set_global_thumbnail(None)

        command = _find_command(author_group, "template_global_show")
        await command.callback(_Interaction(command))

        kwargs = send_standard.await_args.kwargs
        assert kwargs["subcommand_path"] == "author template_global_show"
        assert _section_payload(kwargs) == (
            "Template",
            [
                ("Version", "No custom override (version is ignored without an author phrase)"),
                ("Phrase", "No custom override (services use semantic fallback author)"),
                ("Thumbnail", "No custom override (default author has no thumbnail)"),
                ("Preview", "📊 Status"),
            ],
        )

    asyncio.run(_run())



def test_author_service_template_show_after_reset_reports_fallback_preview(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, "check_permission", AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, "send_standard_response", send_standard)

        embed_group, _footer_group, ctx = _register_embed_with_footer(embed_module)
        author_group = next(cmd for cmd in embed_group.commands if isinstance(cmd, discord.app_commands.Group) and cmd.name == "author")
        await ctx.author.set_service_phrase("riassunto", "Linea riassunto")
        await ctx.author.set_service_phrase("riassunto", None)
        await ctx.author.set_service_thumbnail("riassunto", "https://example.com/riassunto.png")
        await ctx.author.set_service_thumbnail("riassunto", None)

        command = _find_command(author_group, "template_service_show")
        await command.callback(_Interaction(command), "riassunto")

        kwargs = send_standard.await_args.kwargs
        assert kwargs["subcommand_path"] == "author template_service_show"
        assert kwargs["subtitle_args"] == ["riassunto"]
        assert _section_payload(kwargs) == (
            "Template",
            [
                ("Phrase", "No custom override (service uses global/fallback author phrase)"),
                ("Thumbnail", "No custom override (service uses global/no thumbnail fallback)"),
                ("Preview", "🗒️ Riassunto"),
            ],
        )

    asyncio.run(_run())
