from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import discord
import pytest

from app.services.author import attach_author_meta
from app.services.footer import attach_footer_meta
from app.shared.discord.delivery import _prepare_embeds_for_send
from tests._embed_test_utils import InteractionStub, find_command, register_embed_tree


@pytest.fixture
def embed_module(import_fresh):
    return import_fresh('app.plugins.commands_modular.embed')


def test_prepare_embeds_for_send_applies_footer_and_author_when_both_are_enabled() -> None:
    async def _run() -> None:
        embeds = [discord.Embed(title='Page 1'), discord.Embed(title='Page 2')]
        for embed in embeds:
            attach_author_meta(embed, service_name='riassunto')
            attach_footer_meta(embed, service_name='riassunto', contributors=['gpt-4o-mini'], used_local_processing=False)

        bundle = register_embed_tree(__import__('app.plugins.commands_modular.embed', fromlist=['register_embed']))
        prepared = await _prepare_embeds_for_send(
            embeds,
            footer_service=bundle.ctx.footer,
            author_service=bundle.ctx.author,
            default_service_name='riassunto',
        )

        assert [embed.author.name for embed in prepared] == ['servizio DM CHANNEL SUMMARY · (Pag. 1/2)', 'servizio DM CHANNEL SUMMARY · (Pag. 2/2)']
        assert all((embed.footer.text or '').startswith('Barcellometro') for embed in prepared)
        assert all('Dati elaborati con gpt-4o-mini' in (embed.footer.text or '') for embed in prepared)

    asyncio.run(_run())


def test_prepare_embeds_for_send_keeps_footer_when_author_is_disabled() -> None:
    async def _run() -> None:
        embed = discord.Embed(title='Page 1')
        attach_author_meta(embed, service_name='riassunto')
        attach_footer_meta(embed, service_name='riassunto', contributors=['gpt-4o-mini'], used_local_processing=False)

        bundle = register_embed_tree(__import__('app.plugins.commands_modular.embed', fromlist=['register_embed']))
        await bundle.ctx.author.set_enabled(False)
        prepared = await _prepare_embeds_for_send(
            [embed],
            footer_service=bundle.ctx.footer,
            author_service=bundle.ctx.author,
            default_service_name='riassunto',
        )

        assert prepared[0].author.name is None
        assert (prepared[0].footer.text or '').startswith('Barcellometro')
        assert 'Dati elaborati con gpt-4o-mini' in (prepared[0].footer.text or '')

    asyncio.run(_run())


def test_footer_status_command_is_ux_focused_and_uses_public_services(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, 'check_permission', AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, 'send_standard_response', send_standard)
        bundle = register_embed_tree(embed_module)

        await bundle.ctx.footer.set_service_phrase('riassunto', 'Footer riassunto')
        await bundle.ctx.footer.set_enabled(False)

        status_command = find_command(bundle.footer_group, 'status')
        await status_command.callback(InteractionStub(status_command))
        kwargs = send_standard.await_args.kwargs
        assert kwargs['subcommand_path'] == 'footer status'
        assert ('enabled', 'off') in kwargs['lines']
        assert ('supported services', 9) in kwargs['lines']
        default_section = next(section for section in kwargs['sections'] if section.title == 'Default Services')
        assert 'campagne_notizie' not in default_section.lines[0][1]
        assert 'service_1' not in default_section.lines[0][1]

    asyncio.run(_run())


def test_author_status_command_is_ux_focused_and_uses_public_services(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, 'check_permission', AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, 'send_standard_response', send_standard)
        bundle = register_embed_tree(embed_module)

        await bundle.ctx.author.set_service_phrase('riassunto', 'Author riassunto')
        await bundle.ctx.author.set_enabled(False)

        status_command = find_command(bundle.author_group, 'status')
        await status_command.callback(InteractionStub(status_command))
        kwargs = send_standard.await_args.kwargs
        assert kwargs['subcommand_path'] == 'author status'
        assert ('enabled', 'off') in kwargs['lines']
        assert ('supported services', 9) in kwargs['lines']
        default_section = next(section for section in kwargs['sections'] if section.title == 'Default Services')
        assert 'audio_notes' not in default_section.lines[0][1]
        assert 'service_1' not in default_section.lines[0][1]

    asyncio.run(_run())


def test_author_canonical_labels_use_top_level_command_tokens() -> None:
    from app.services.author import render_author_name

    assert render_author_name(service_name='status') == 'servizio EMBED'
    assert render_author_name(service_name='riassunto') == 'servizio DM CHANNEL SUMMARY'
    assert render_author_name(service_name='aura') == 'servizio DM SERVER SUMMARY'
