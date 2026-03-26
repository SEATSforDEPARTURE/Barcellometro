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

        assert [embed.author.name for embed in prepared] == ['servizio SUMMARY · (Pag. 1/2)', 'servizio SUMMARY · (Pag. 2/2)']
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


def test_footer_status_command_supports_multipage_navigation(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, 'check_permission', AsyncMock(return_value=True))
        send_command_embeds = AsyncMock()
        monkeypatch.setattr(embed_module, 'send_command_embeds', send_command_embeds)
        bundle = register_embed_tree(embed_module)

        for idx in range(40):
            await bundle.ctx.footer.record_service_footer_variant(
                service_name=f'service_{idx}',
                contributors=[f'model_{idx}', f'fallback_{idx}'],
                used_local_processing=idx % 2 == 0,
                last_rendered_footer=f'Footer {idx} ' + ('x' * 120),
                origin='runtime',
            )

        status_command = find_command(bundle.footer_group, 'status')
        await status_command.callback(InteractionStub(status_command))

        kwargs = send_command_embeds.await_args.kwargs
        view = kwargs['view']
        assert isinstance(view, embed_module.FooterStatusPaginationView)
        assert len(view._embeds) > 1
        assert all('• Pagina: **' in (page.description or '') for page in view._embeds)
        assert all('Pagina ' not in (page.footer.text or '') for page in view._embeds)
        assert all((page.title or '') == '📦 EMBED' for page in view._embeds)

    asyncio.run(_run())


def test_author_status_command_supports_multipage_navigation(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, 'check_permission', AsyncMock(return_value=True))
        send_command_embeds = AsyncMock()
        monkeypatch.setattr(embed_module, 'send_command_embeds', send_command_embeds)
        bundle = register_embed_tree(embed_module)

        for idx in range(24):
            await bundle.ctx.author.record_service_author(
                service_name=f'service_{idx}',
                last_rendered_author=f'Author render {idx} ' + ('x' * 100),
                last_icon_url=None,
                origin='runtime',
            )

        status_command = find_command(bundle.author_group, 'status')
        await status_command.callback(InteractionStub(status_command))

        kwargs = send_command_embeds.await_args.kwargs
        view = kwargs['view']
        assert isinstance(view, embed_module.AuthorStatusPaginationView)
        assert len(view._embeds) > 1
        assert all('• Pagina ' in (page.description or '') for page in view._embeds)
        assert all((page.author.name or '').startswith('servizio STATUS') for page in view._embeds)
        assert all((page.footer.text or '').startswith('Barcellometro') for page in view._embeds)

    asyncio.run(_run())
