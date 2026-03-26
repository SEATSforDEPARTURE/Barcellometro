from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import discord
import pytest

from tests._embed_test_utils import InteractionStub, find_command, register_embed_tree, section_payload


@pytest.fixture
def embed_module(import_fresh):
    return import_fresh('app.plugins.commands_modular.embed')


def test_author_commands_register_under_embed_namespace(embed_module) -> None:
    bundle = register_embed_tree(embed_module)

    assert {command.name for command in bundle.author_group.commands} == {
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


def test_author_on_off_and_status_commands(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, 'check_permission', AsyncMock(return_value=True))
        send_standard = AsyncMock()
        send_command_embeds = AsyncMock()
        monkeypatch.setattr(embed_module, 'send_standard_response', send_standard)
        monkeypatch.setattr(embed_module, 'send_command_embeds', send_command_embeds)
        bundle = register_embed_tree(embed_module)
        await bundle.ctx.author.record_service_author(
            service_name='riassunto',
            last_rendered_author='🗒️ Riassunto',
            last_icon_url=None,
            origin='runtime',
        )

        off_command = find_command(bundle.author_group, 'off')
        await off_command.callback(InteractionStub(off_command))
        assert send_standard.await_args.kwargs['subcommand_path'] == 'author off'
        assert send_standard.await_args.kwargs['lines'] == [('result', 'disabled')]
        assert await bundle.ctx.author.is_enabled() is False

        send_standard.reset_mock()
        on_command = find_command(bundle.author_group, 'on')
        await on_command.callback(InteractionStub(on_command))
        assert send_standard.await_args.kwargs['subcommand_path'] == 'author on'
        assert send_standard.await_args.kwargs['lines'] == [('result', 'enabled')]
        assert await bundle.ctx.author.is_enabled() is True

        status_command = find_command(bundle.author_group, 'status')
        await status_command.callback(InteractionStub(status_command))
        status_kwargs = send_command_embeds.await_args.kwargs
        assert status_kwargs['ephemeral'] is True
        assert len(status_kwargs['embeds']) == 1
        assert status_kwargs['embeds'][0].title == '📦 EMBED'
        assert isinstance(status_kwargs['view'], embed_module.AuthorStatusPaginationView)

    asyncio.run(_run())


def test_author_template_global_set_show_reset_and_fallback_after_reset(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, 'check_permission', AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, 'send_standard_response', send_standard)
        bundle = register_embed_tree(embed_module)

        set_command = find_command(bundle.author_group, 'template_global_set')
        await set_command.callback(
            InteractionStub(set_command),
            version='v3',
            phrase='Linea author',
            thumbnail='<:melon:1475962151502876695>',
        )
        set_kwargs = send_standard.await_args.kwargs
        assert set_kwargs['subcommand_path'] == 'author template_global_set'
        assert section_payload(set_kwargs) == (
            'Template',
            [
                ('Version', 'v3'),
                ('Phrase', 'Linea author'),
                ('Thumbnail', 'https://cdn.discordapp.com/emojis/1475962151502876695.png'),
                ('URL', '(not set)'),
                ('Preview', 'Linea author · v3'),
            ],
        )

        send_standard.reset_mock()
        show_command = find_command(bundle.author_group, 'template_global_show')
        await show_command.callback(InteractionStub(show_command))
        assert section_payload(send_standard.await_args.kwargs) == (
            'Template',
            [
                ('Version', 'v3'),
                ('Phrase', 'Linea author'),
                ('Thumbnail', 'https://cdn.discordapp.com/emojis/1475962151502876695.png'),
                ('URL', '(not set)'),
                ('Preview', 'Linea author · v3'),
            ],
        )

        send_standard.reset_mock()
        reset_command = find_command(bundle.author_group, 'template_global_reset')
        await reset_command.callback(InteractionStub(reset_command))
        assert send_standard.await_args.kwargs['lines'] == [('result', 'reset')]
        assert await bundle.ctx.author.get_version() is None
        assert await bundle.ctx.author.get_global_phrase() is None
        assert await bundle.ctx.author.get_global_thumbnail() is None

        send_standard.reset_mock()
        await show_command.callback(InteractionStub(show_command))
        assert section_payload(send_standard.await_args.kwargs) == (
            'Template',
            [
                ('Version', 'No custom override (version is ignored without an author phrase)'),
                ('Phrase', 'No custom override (services use semantic fallback author)'),
                ('Thumbnail', 'No custom override (default author has no thumbnail)'),
                ('URL', 'No custom override (default author has no URL)'),
                ('Preview', 'servizio STATUS'),
            ],
        )

    asyncio.run(_run())


def test_author_template_service_set_show_reset_and_partial_updates(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, 'check_permission', AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, 'send_standard_response', send_standard)
        bundle = register_embed_tree(embed_module)
        await bundle.ctx.author.set_version('2026.03')
        await bundle.ctx.author.set_global_phrase('Centro embed')

        set_command = find_command(bundle.author_group, 'template_service_set')
        await set_command.callback(
            InteractionStub(set_command),
            'riassunto',
            phrase='Linea dedicata',
            thumbnail='https://example.com/service.png',
        )
        assert section_payload(send_standard.await_args.kwargs) == (
            'Template',
            [
                ('Phrase', 'Linea dedicata'),
                ('Thumbnail', 'https://example.com/service.png'),
                ('URL', '(not set)'),
                ('Preview', 'Linea dedicata · 2026.03'),
            ],
        )

        send_standard.reset_mock()
        await set_command.callback(InteractionStub(set_command), 'riassunto', thumbnail='https://example.com/updated.png')
        partial_kwargs = send_standard.await_args.kwargs
        assert partial_kwargs['subtitle_args'] == ['riassunto']
        assert section_payload(partial_kwargs) == (
            'Template',
            [
                ('Phrase', 'Linea dedicata'),
                ('Thumbnail', 'https://example.com/updated.png'),
                ('URL', '(not set)'),
                ('Preview', 'Linea dedicata · 2026.03'),
            ],
        )

        send_standard.reset_mock()
        show_command = find_command(bundle.author_group, 'template_service_show')
        await show_command.callback(InteractionStub(show_command), 'riassunto')
        assert section_payload(send_standard.await_args.kwargs) == (
            'Template',
            [
                ('Phrase', 'Linea dedicata'),
                ('Thumbnail', 'https://example.com/updated.png'),
                ('URL', '(not set)'),
                ('Preview', 'Linea dedicata · 2026.03'),
            ],
        )

        send_standard.reset_mock()
        reset_command = find_command(bundle.author_group, 'template_service_reset')
        await reset_command.callback(InteractionStub(reset_command), 'riassunto')
        assert send_standard.await_args.kwargs['lines'] == [('result', 'reset')]
        assert (await bundle.ctx.author.get_service_phrases()).get('riassunto') is None
        assert (await bundle.ctx.author.get_service_thumbnails()).get('riassunto') is None

        send_standard.reset_mock()
        await show_command.callback(InteractionStub(show_command), 'riassunto')
        assert section_payload(send_standard.await_args.kwargs) == (
            'Template',
            [
                ('Phrase', 'No custom override (service uses global/fallback author phrase)'),
                ('Thumbnail', 'No custom override (service uses global/no thumbnail fallback)'),
                ('URL', 'No custom override (service uses global/no URL fallback)'),
                ('Preview', 'Centro embed · 2026.03'),
            ],
        )

    asyncio.run(_run())


def test_author_template_set_rejects_invalid_thumbnail(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, 'check_permission', AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, 'send_standard_response', send_standard)
        bundle = register_embed_tree(embed_module)

        global_command = find_command(bundle.author_group, 'template_global_set')
        await global_command.callback(InteractionStub(global_command), thumbnail='bad-value')
        assert send_standard.await_args.kwargs['kind'] == 'error'
        assert send_standard.await_args.kwargs['lines'] == [
            ('reason', 'Thumbnail must be a Discord custom emoji or an http/https image URL')
        ]
        assert await bundle.ctx.author.get_global_thumbnail() is None

        send_standard.reset_mock()
        service_command = find_command(bundle.author_group, 'template_service_set')
        await service_command.callback(InteractionStub(service_command), 'riassunto', thumbnail='bad-value')
        assert send_standard.await_args.kwargs['subtitle_args'] == ['riassunto']
        assert send_standard.await_args.kwargs['kind'] == 'error'
        assert (await bundle.ctx.author.get_service_thumbnails()).get('riassunto') is None

    asyncio.run(_run())


def test_author_template_set_without_changes_returns_warning(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, 'check_permission', AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, 'send_standard_response', send_standard)
        bundle = register_embed_tree(embed_module)

        global_command = find_command(bundle.author_group, 'template_global_set')
        await global_command.callback(InteractionStub(global_command))
        global_kwargs = send_standard.await_args.kwargs
        assert global_kwargs['kind'] == 'warning'
        assert global_kwargs['lines'] == [('reason', 'No changes provided')]
        assert section_payload(global_kwargs) == ('Next Step', [('Command', '/embed author template_global_show')])

        send_standard.reset_mock()
        service_command = find_command(bundle.author_group, 'template_service_set')
        await service_command.callback(InteractionStub(service_command), 'riassunto')
        service_kwargs = send_standard.await_args.kwargs
        assert service_kwargs['subtitle_args'] == ['riassunto']
        assert service_kwargs['kind'] == 'warning'
        assert service_kwargs['lines'] == [('reason', 'No changes provided')]

    asyncio.run(_run())
