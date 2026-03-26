from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from app.services.author import AuthorService
from app.services.footer import FooterService
from app.shared.discord.author_pipeline import finalize_embed_author, install_author_auto_finalize
from app.shared.discord.command_embeds import build_command_embeds, send_command_embeds
from app.shared.discord.delivery import send_dm_or_followup
from app.shared.discord.footer_pipeline import finalize_embed, install_footer_auto_finalize


class _FakeDatabase:
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

    async def fetchall(self, query: str, params: tuple[str, ...] = ()):  # noqa: ANN202
        prefix = str(params[0]).replace('%', '') if params else ''
        if 'FROM settings' not in query:
            return []
        return [
            {'key': key, 'value': value}
            for key, value in sorted(self.settings.items())
            if not prefix or key.startswith(prefix)
        ]


class _ResponseStub:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object]] = []

    def is_done(self) -> bool:
        return False

    async def send_message(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.sent_messages.append(kwargs)


class _FollowupStub:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object]] = []

    async def send(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.sent_messages.append(kwargs)


class _InteractionStub:
    def __init__(self) -> None:
        self.response = _ResponseStub()
        self.followup = _FollowupStub()
        self.user = SimpleNamespace(send=AsyncMock())


def _build_services() -> tuple[AuthorService, FooterService]:
    database = _FakeDatabase()
    return AuthorService(database), FooterService(database)


def _manual_embed(*, title: str = 'x') -> discord.Embed:
    embed = discord.Embed(title=title, description='payload')
    embed.set_author(name='Manual author')
    embed.set_footer(text='Manual footer')
    return embed


def _install_auto_finalize(monkeypatch, author_service: AuthorService, footer_service: FooterService) -> list[dict[str, object]]:
    captured: list[dict[str, object]] = []

    async def _capture(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        captured.append(kwargs)
        return kwargs

    monkeypatch.setattr(discord, '_barcellometro_author_patched', False, raising=False)
    monkeypatch.setattr(discord, '_barcellometro_footer_patched', False, raising=False)
    monkeypatch.setattr(discord.InteractionResponse, 'send_message', _capture)
    monkeypatch.setattr(discord.InteractionResponse, 'edit_message', _capture)
    monkeypatch.setattr(discord.Webhook, 'send', _capture)
    monkeypatch.setattr(discord.Message, 'reply', _capture)
    monkeypatch.setattr(discord.Message, 'edit', _capture)
    monkeypatch.setattr(discord.abc.Messageable, 'send', _capture)

    install_author_auto_finalize(author_service)
    install_footer_auto_finalize(footer_service)
    return captured


def test_author_off_removes_existing_author_even_without_meta() -> None:
    async def _run() -> None:
        author_service, _ = _build_services()
        await author_service.set_enabled(False)
        embed = _manual_embed(title='author off')

        await finalize_embed_author(embed, author_service, default_service_name='member_flow_notifications')

        assert embed.author.name is None

    asyncio.run(_run())


def test_footer_off_removes_existing_footer_even_when_rehydrated() -> None:
    async def _run() -> None:
        _, footer_service = _build_services()
        await footer_service.set_enabled(False)
        source = _manual_embed(title='footer off')
        embed = discord.Embed.from_dict(source.to_dict())

        await finalize_embed(embed, footer_service, default_service_name='daily_activity_report')

        assert embed.footer.text is None

    asyncio.run(_run())


def test_send_command_embeds_uses_real_services_for_global_off_semantics() -> None:
    async def _run() -> None:
        author_service, footer_service = _build_services()
        await author_service.set_enabled(False)
        await footer_service.set_enabled(False)
        interaction = _InteractionStub()
        embeds = await build_command_embeds(
            top_level='admin',
            subcommand_path='qna bonus_show',
            visual_top_level='qna',
            lines=[('result', 'ok')],
            footer_mode='meta',
            footer_service_name='qna',
        )

        await send_command_embeds(
            interaction,
            embeds=embeds,
            ephemeral=True,
            author_service=author_service,
            footer_service=footer_service,
            default_service_name='qna',
        )

        sent_embed = interaction.response.sent_messages[0]['embed']
        assert isinstance(sent_embed, discord.Embed)
        assert sent_embed.author.name is None
        assert sent_embed.footer.text is None

    asyncio.run(_run())


def test_send_command_embeds_applies_author_and_footer_when_enabled() -> None:
    async def _run() -> None:
        author_service, footer_service = _build_services()
        interaction = _InteractionStub()
        embeds = await build_command_embeds(
            top_level='admin',
            subcommand_path='qna bonus_show',
            visual_top_level='qna',
            lines=[('result', 'ok')],
            footer_mode='meta',
            footer_service_name='qna',
        )

        await send_command_embeds(
            interaction,
            embeds=embeds,
            ephemeral=True,
            author_service=author_service,
            footer_service=footer_service,
            default_service_name='qna',
        )

        sent_embed = interaction.response.sent_messages[0]['embed']
        assert isinstance(sent_embed, discord.Embed)
        assert sent_embed.author.name == 'servizio QNA'
        assert (sent_embed.footer.text or '').startswith('Barcellometro')

    asyncio.run(_run())


def test_auto_finalize_suppresses_author_and_footer_for_send_edit_followup_and_channel(monkeypatch) -> None:
    async def _run() -> None:
        author_service, footer_service = _build_services()
        await author_service.set_enabled(False)
        await footer_service.set_enabled(False)
        captured = _install_auto_finalize(monkeypatch, author_service, footer_service)

        response_send = _manual_embed(title='response send')
        response_edit = discord.Embed.from_dict(_manual_embed(title='response edit').to_dict())
        followup_embed = discord.Embed.from_dict(_manual_embed(title='followup').to_dict())
        channel_embed = _manual_embed(title='channel')

        await discord.InteractionResponse.send_message(object(), embed=response_send)
        await discord.InteractionResponse.edit_message(object(), embed=response_edit)
        await discord.Webhook.send(object(), embed=followup_embed)
        await discord.abc.Messageable.send(object(), embed=channel_embed)

        assert len(captured) == 4
        for payload in captured:
            embed = payload['embed']
            assert isinstance(embed, discord.Embed)
            assert embed.author.name is None
            assert embed.footer.text is None

    asyncio.run(_run())


def test_send_dm_or_followup_suppresses_manual_author_and_footer_when_disabled() -> None:
    async def _run() -> None:
        author_service, footer_service = _build_services()
        await author_service.set_enabled(False)
        await footer_service.set_enabled(False)
        interaction = _InteractionStub()
        cloned_embed = discord.Embed.from_dict(_manual_embed(title='dm clone').to_dict())

        delivered = await send_dm_or_followup(
            interaction,
            embeds=[cloned_embed],
            author_service=author_service,
            footer_service=footer_service,
            default_service_name='riassunto',
        )

        assert delivered is True
        sent_embeds = interaction.user.send.await_args.kwargs['embeds']
        assert len(sent_embeds) == 1
        assert sent_embeds[0].author.name is None
        assert sent_embeds[0].footer.text is None

    asyncio.run(_run())
