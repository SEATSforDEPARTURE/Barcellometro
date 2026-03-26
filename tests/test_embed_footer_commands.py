from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
from discord import app_commands

from tests._embed_test_utils import InteractionStub, find_command, register_embed_tree, section_payload


@pytest.fixture
def embed_module(import_fresh):
    return import_fresh('app.plugins.commands_modular.embed')


def test_embed_footer_registers_under_top_level_embed_only(embed_module) -> None:
    bundle = register_embed_tree(embed_module)

    assert bundle.embed_group.name == 'embed'
    assert {group.name for group in bundle.embed_group.commands if isinstance(group, discord.app_commands.Group)} == {
        'footer',
        'author',
        'images',
    }
    assert {command.name for command in bundle.footer_group.commands} == {
        'on',
        'off',
        'status',
        'template_global_set',
        'template_global_show',
        'template_global_reset',
        'template_service_set',
        'template_service_show',
        'template_service_reset',
    }


def test_admin_namespace_no_longer_registers_footer_commands(import_fresh) -> None:
    admin_module = import_fresh('app.plugins.commands_modular.admin')
    admin_group = app_commands.Group(name='admin', description='admin')
    admin_module.register_admin(admin_group, SimpleNamespace(database=SimpleNamespace(), footer=None, ai=None))

    assert all(
        not (isinstance(command, discord.app_commands.Group) and command.name == 'footer')
        for command in admin_group.commands
    )


def test_footer_template_global_set_show_and_reset_roundtrip(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, 'check_permission', AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, 'send_standard_response', send_standard)
        bundle = register_embed_tree(embed_module)

        set_command = find_command(bundle.footer_group, 'template_global_set')
        await set_command.callback(
            InteractionStub(set_command),
            version='2.4',
            phrase='Footer globale',
            thumbnail='<:melon:1475962151502876695>',
        )

        set_kwargs = send_standard.await_args.kwargs
        assert set_kwargs['top_level'] == 'embed'
        assert set_kwargs['subcommand_path'] == 'footer template_global_set'
        assert set_kwargs['lines'] == [('result', 'updated')]
        assert section_payload(set_kwargs) == (
            'Template',
            [
                ('Version', '2.4'),
                ('Phrase', 'Footer globale'),
                ('Thumbnail', 'https://cdn.discordapp.com/emojis/1475962151502876695.png'),
            ],
        )
        assert await bundle.ctx.footer.get_version() == '2.4'
        assert await bundle.ctx.footer.get_global_phrase() == 'Footer globale'
        assert await bundle.ctx.footer.get_global_thumbnail() == 'https://cdn.discordapp.com/emojis/1475962151502876695.png'

        send_standard.reset_mock()
        show_command = find_command(bundle.footer_group, 'template_global_show')
        await show_command.callback(InteractionStub(show_command))

        show_kwargs = send_standard.await_args.kwargs
        assert section_payload(show_kwargs) == (
            'Template',
            [
                ('Version', '2.4'),
                ('Phrase', 'Footer globale'),
                ('Thumbnail', 'https://cdn.discordapp.com/emojis/1475962151502876695.png'),
            ],
        )

        send_standard.reset_mock()
        reset_command = find_command(bundle.footer_group, 'template_global_reset')
        await reset_command.callback(InteractionStub(reset_command))

        reset_kwargs = send_standard.await_args.kwargs
        assert reset_kwargs['subcommand_path'] == 'footer template_global_reset'
        assert reset_kwargs['lines'] == [('result', 'reset')]
        assert await bundle.ctx.footer.get_version() is None
        assert await bundle.ctx.footer.get_global_phrase() is None
        assert await bundle.ctx.footer.get_global_thumbnail() is None

        send_standard.reset_mock()
        await show_command.callback(InteractionStub(show_command))
        assert section_payload(send_standard.await_args.kwargs) == (
            'Template',
            [
                ('Version', '(not set)'),
                ('Phrase', '(not set)'),
                ('Thumbnail', '(not set)'),
            ],
        )

    asyncio.run(_run())


def test_footer_template_service_set_show_and_reset_roundtrip(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, 'check_permission', AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, 'send_standard_response', send_standard)
        bundle = register_embed_tree(embed_module)

        set_command = find_command(bundle.footer_group, 'template_service_set')
        await set_command.callback(
            InteractionStub(set_command),
            'riassunto',
            phrase='Servizio dedicato',
            thumbnail='https://example.com/service.png',
        )

        set_kwargs = send_standard.await_args.kwargs
        assert set_kwargs['subtitle_args'] == ['riassunto']
        assert set_kwargs['lines'] == [('result', 'updated')]
        assert section_payload(set_kwargs) == (
            'Template',
            [
                ('Phrase', 'Servizio dedicato'),
                ('Thumbnail', 'https://example.com/service.png'),
            ],
        )

        send_standard.reset_mock()
        show_command = find_command(bundle.footer_group, 'template_service_show')
        await show_command.callback(InteractionStub(show_command), 'riassunto')
        assert section_payload(send_standard.await_args.kwargs) == (
            'Template',
            [
                ('Phrase', 'Servizio dedicato'),
                ('Thumbnail', 'https://example.com/service.png'),
            ],
        )

        send_standard.reset_mock()
        reset_command = find_command(bundle.footer_group, 'template_service_reset')
        await reset_command.callback(InteractionStub(reset_command), 'riassunto')
        assert send_standard.await_args.kwargs['lines'] == [('result', 'reset')]
        assert (await bundle.ctx.footer.get_service_phrases()).get('riassunto') is None
        assert (await bundle.ctx.footer.get_service_thumbnails()).get('riassunto') is None

        send_standard.reset_mock()
        await show_command.callback(InteractionStub(show_command), 'riassunto')
        assert section_payload(send_standard.await_args.kwargs) == (
            'Template',
            [
                ('Phrase', '(not set)'),
                ('Thumbnail', '(not set)'),
            ],
        )

    asyncio.run(_run())


def test_footer_template_set_rejects_invalid_thumbnail(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, 'check_permission', AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, 'send_standard_response', send_standard)
        bundle = register_embed_tree(embed_module)

        global_command = find_command(bundle.footer_group, 'template_global_set')
        await global_command.callback(InteractionStub(global_command), thumbnail='bad-value')
        assert send_standard.await_args.kwargs['kind'] == 'error'
        assert send_standard.await_args.kwargs['lines'] == [
            ('reason', 'Thumbnail must be a Discord custom emoji or an http/https image URL')
        ]
        assert await bundle.ctx.footer.get_global_thumbnail() is None

        send_standard.reset_mock()
        service_command = find_command(bundle.footer_group, 'template_service_set')
        await service_command.callback(InteractionStub(service_command), 'riassunto', thumbnail='bad-value')
        assert send_standard.await_args.kwargs['subtitle_args'] == ['riassunto']
        assert send_standard.await_args.kwargs['kind'] == 'error'
        assert (await bundle.ctx.footer.get_service_thumbnails()).get('riassunto') is None

    asyncio.run(_run())


def test_footer_template_set_without_changes_returns_warning_and_next_step(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, 'check_permission', AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, 'send_standard_response', send_standard)
        bundle = register_embed_tree(embed_module)

        global_command = find_command(bundle.footer_group, 'template_global_set')
        await global_command.callback(InteractionStub(global_command))
        global_kwargs = send_standard.await_args.kwargs
        assert global_kwargs['kind'] == 'warning'
        assert global_kwargs['lines'] == [('reason', 'No changes provided')]
        assert section_payload(global_kwargs) == ('Next Step', [('Command', '/embed footer template_global_show')])

        send_standard.reset_mock()
        service_command = find_command(bundle.footer_group, 'template_service_set')
        await service_command.callback(InteractionStub(service_command), 'riassunto')
        service_kwargs = send_standard.await_args.kwargs
        assert service_kwargs['subtitle_args'] == ['riassunto']
        assert service_kwargs['kind'] == 'warning'
        assert service_kwargs['lines'] == [('reason', 'No changes provided')]

    asyncio.run(_run())


def test_footer_status_command_uses_embed_namespace_and_interactive_view(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, 'check_permission', AsyncMock(return_value=True))
        send_command_embeds = AsyncMock()
        monkeypatch.setattr(embed_module, 'send_command_embeds', send_command_embeds)
        bundle = register_embed_tree(embed_module)
        await bundle.ctx.footer.record_service_footer_variant(
            service_name='riassunto',
            contributors=['gpt-4o-mini'],
            used_local_processing=False,
            last_rendered_footer='Footer riassunto',
            origin='runtime',
        )

        status_command = find_command(bundle.footer_group, 'status')
        await status_command.callback(InteractionStub(status_command))

        kwargs = send_command_embeds.await_args.kwargs
        assert kwargs['ephemeral'] is True
        assert len(kwargs['embeds']) == 1
        assert kwargs['embeds'][0].title == '📦 EMBED'
        assert isinstance(kwargs['view'], embed_module.FooterStatusPaginationView)
        assert kwargs['view']._embeds[0].title == '📦 EMBED'

    asyncio.run(_run())
