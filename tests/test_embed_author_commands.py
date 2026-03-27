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
        monkeypatch.setattr(embed_module, 'send_standard_response', send_standard)
        bundle = register_embed_tree(embed_module)
        await bundle.ctx.author.set_service_phrase('riassunto', 'Autore riassunto')
        await bundle.ctx.author.set_service_url('riassunto', 'https://example.com/riassunto')
        await bundle.ctx.author.set_enabled(False)

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
        send_standard.reset_mock()
        await status_command.callback(InteractionStub(status_command))
        status_kwargs = send_standard.await_args.kwargs
        assert status_kwargs['subcommand_path'] == 'author status'
        assert ('enabled', 'on') in status_kwargs['lines']
        assert ('supported services', 15) in status_kwargs['lines']
        assert ('services with custom template', 1) in status_kwargs['lines']
        assert ('services using default', 14) in status_kwargs['lines']
        assert ('runtime rule', 'ON = runtime uses service custom author when configured; otherwise standard default') in status_kwargs['lines']
        custom_section = next(section for section in status_kwargs['sections'] if section.title == 'Custom Templates')
        assert ('dmchannelsummary', 'phrase, url') in custom_section.lines
        default_section = next(section for section in status_kwargs['sections'] if section.title == 'Default Services')
        assert 'audio' in default_section.lines[0][1]
        assert 'triggers' in default_section.lines[0][1]
        assert 'audio_notes' not in default_section.lines[0][1]
        assert 'campaign_content_formatter' not in default_section.lines[0][1]
        placeholders = dict(next(section for section in status_kwargs['sections'] if section.title == 'PLACEHOLDERS').lines)
        assert "{service_name}" in placeholders
        assert "{service_label}" in placeholders
        assert "{bot_version}" in placeholders
        assert "{user_name}" not in placeholders
        all_text = " ".join(
            [
                *(f"{k} {v}" for k, v in status_kwargs['lines']),
                *(f"{section.title} {section.lines}" for section in status_kwargs['sections']),
            ]
        ).lower()
        for noisy_token in ('famiglie', 'varianti', 'sorgenti', 'navigazione', 'pagina'):
            assert noisy_token not in all_text

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
                ('Version', '(not set)'),
                ('Phrase', '(not set)'),
                ('Thumbnail', '(not set)'),
                ('URL', '(not set)'),
                ('Preview', 'servizio EMBED'),
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
        assert partial_kwargs['subtitle_args'] == ['dmchannelsummary']
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
        show_kwargs = send_standard.await_args.kwargs
        assert section_payload(show_kwargs) == (
            'Template',
            [
                ('Phrase', 'Linea dedicata'),
                ('Thumbnail', 'https://example.com/updated.png'),
                ('URL', '(not set)'),
                ('Preview', 'Linea dedicata · 2026.03'),
            ],
        )
        placeholders = dict(next(section for section in show_kwargs['sections'] if section.title == 'PLACEHOLDERS').lines)
        assert "{service_name}" in placeholders
        assert "{service_label}" in placeholders
        assert "{bot_version}" in placeholders
        assert "{user_name}" not in placeholders

        send_standard.reset_mock()
        reset_command = find_command(bundle.author_group, 'template_service_reset')
        await reset_command.callback(InteractionStub(reset_command), 'riassunto')
        assert send_standard.await_args.kwargs['lines'] == [('result', 'reset')]
        assert (await bundle.ctx.author.get_service_phrases()).get('dmchannelsummary') is None
        assert (await bundle.ctx.author.get_service_thumbnails()).get('dmchannelsummary') is None

        send_standard.reset_mock()
        await show_command.callback(InteractionStub(show_command), 'riassunto')
        fallback_kwargs = send_standard.await_args.kwargs
        assert section_payload(fallback_kwargs) == (
            'Template',
            [
                ('Phrase', '(not set)'),
                ('Thumbnail', '(not set)'),
                ('URL', '(not set)'),
                ('Preview', 'Centro embed · 2026.03'),
            ],
        )
        fallback_placeholders = dict(next(section for section in fallback_kwargs['sections'] if section.title == 'PLACEHOLDERS').lines)
        assert fallback_placeholders == placeholders

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
        assert send_standard.await_args.kwargs['subtitle_args'] == ['dmchannelsummary']
        assert send_standard.await_args.kwargs['kind'] == 'error'
        assert (await bundle.ctx.author.get_service_thumbnails()).get('dmchannelsummary') is None

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
        assert service_kwargs['subtitle_args'] == ['dmchannelsummary']
        assert service_kwargs['kind'] == 'warning'
        assert service_kwargs['lines'] == [('reason', 'No changes provided')]

    asyncio.run(_run())


def test_author_template_service_resolves_legacy_aliases(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, "check_permission", AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, "send_standard_response", send_standard)
        bundle = register_embed_tree(embed_module)
        bundle.database.settings["author.service_phrase.audio_notes"] = "Legacy author"

        show_command = find_command(bundle.author_group, "template_service_show")
        await show_command.callback(InteractionStub(show_command), "audio")
        assert section_payload(send_standard.await_args.kwargs) == (
            "Template",
            [
                ("Phrase", "Legacy author"),
                ("Thumbnail", "(not set)"),
                ("URL", "(not set)"),
                ("Preview", "Legacy author"),
            ],
        )

    asyncio.run(_run())
