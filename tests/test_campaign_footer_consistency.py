from __future__ import annotations

import asyncio
import json
import sys
import types
from types import SimpleNamespace

import discord

if 'app.services.ai' not in sys.modules:
    sys.modules['app.services.ai'] = types.SimpleNamespace(AiService=object)

from app.services.campaign_content_formatter import build_news_embeds
from app.services.campaign_content_service import CampaignContentService
from app.services.footer import FooterService, attach_footer_meta
from app.shared.discord.footer_pipeline import finalize_embed, finalize_embeds


class _FooterDb:
    def __init__(self) -> None:
        self.settings: dict[str, str] = {}
        self.saved_messages: list[dict[str, object]] = []

    async def get_setting(self, key: str) -> str | None:
        return self.settings.get(key)

    async def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value

    async def fetchall(self, _query: str, _params: tuple[str, ...]):
        return []

    async def upsert_campaign_content_message(self, **kwargs) -> None:
        self.saved_messages.append(kwargs)

    async def update_campaign_content_next_run(self, **kwargs) -> None:
        self.last_next_run = kwargs

    async def set_campaign_content_enabled(self, **kwargs) -> None:
        self.last_enabled = kwargs


class _FakeChannel(discord.abc.Messageable):
    def __init__(self) -> None:
        self.sent: list[discord.Embed] = []

    async def _get_channel(self):
        return self

    async def send(self, *, embed: discord.Embed | None = None, embeds: list[discord.Embed] | None = None, view=None, **kwargs):  # noqa: ANN003
        if embeds is not None:
            self.sent.extend(embeds)
            return SimpleNamespace(id=321, embed=embeds[0], view=view, kwargs=kwargs)
        if embed is not None:
            self.sent.append(embed)
            return SimpleNamespace(id=321, embed=embed, view=view, kwargs=kwargs)
        raise ValueError("No embed provided")


def _build_footer_service(db: _FooterDb) -> FooterService:
    return FooterService(db)


async def _build_news_payload() -> tuple[dict[str, object], dict[str, object]]:
    config = {
        'embed_title': '🗞️ Notizie del giorno',
        'embed_color': '#123456',
        'guild_id': '1',
        'channel_id': '99',
        'id': 7,
        'interval_minutes': 60,
    }
    payload = {
        'categories': {
            'cronaca': [
                {
                    'title': 'Titolo 1',
                    'summary': 'Riassunto 1',
                    'source': 'ansa',
                    'link': 'https://example.com/1',
                    'category': 'cronaca',
                }
            ]
        }
    }
    return config, payload


def test_campaign_embeds_include_global_phrase_after_finalize() -> None:
    async def _run() -> list[discord.Embed]:
        db = _FooterDb()
        footer_service = _build_footer_service(db)
        await footer_service.set_version('dev7.1')
        await footer_service.set_global_phrase('In via di sviluppo')
        config, payload = await _build_news_payload()
        embeds = build_news_embeds(config, payload)

        await finalize_embeds(embeds, footer_service, default_service_name='campagne_notizie')
        return embeds

    embeds = asyncio.run(_run())

    assert embeds
    assert all(embed.footer is not None for embed in embeds)
    assert all(embed.footer.text == 'Barcellometro dev7.1 · In via di sviluppo' for embed in embeds)


def test_campaign_send_and_store_persists_centralized_footer_with_phrase() -> None:
    async def _run() -> tuple[discord.Embed, str, object | None]:
        db = _FooterDb()
        footer_service = _build_footer_service(db)
        await footer_service.set_version('dev7.1')
        await footer_service.set_global_phrase('In via di sviluppo')
        channel = _FakeChannel()
        bot = SimpleNamespace(get_channel=lambda _channel_id: channel)
        service = CampaignContentService(db, bot)
        await service._footer.set_version('dev7.1')
        await service._footer.set_global_phrase('In via di sviluppo')
        config, payload = await _build_news_payload()
        embeds = build_news_embeds(config, payload)

        await service._send_and_store(
            config,
            embeds,
            'NEWS',
            configured_sources=['ansa'],
            used_sources=['ansa'],
            used_model=None,
            fallback_used=False,
            payload=payload,
        )

        saved = json.loads(db.saved_messages[0]['embeds_json'])
        return channel.sent[0], saved[0]['footer']['text'], db.saved_messages[0].get("metadata_json")

    sent_embed, stored_footer, metadata_json = asyncio.run(_run())

    assert sent_embed.footer is not None
    assert sent_embed.footer.text == 'Barcellometro dev7.1 · In via di sviluppo · Dati elaborati con Ansa RSS'
    assert stored_footer == 'Barcellometro dev7.1 · In via di sviluppo · Dati elaborati con Ansa RSS'
    assert metadata_json is not None


def test_footer_finalize_with_contributors_keeps_phrase_and_processing_order() -> None:
    async def _run() -> discord.Embed:
        db = _FooterDb()
        footer_service = _build_footer_service(db)
        await footer_service.set_version('dev7.1')
        await footer_service.set_global_phrase('Sempre acceso')
        embed = discord.Embed(title='x')
        attach_footer_meta(embed, service_name='riassunto', contributors=['gpt-4o-mini'], used_local_processing=False)

        await finalize_embed(embed, footer_service, default_service_name='riassunto')
        return embed

    embed = asyncio.run(_run())

    assert embed.footer is not None
    assert embed.footer.text == 'Barcellometro dev7.1 · Sempre acceso · Dati elaborati con gpt-4o-mini'


def test_footer_finalize_without_phrase_does_not_invent_fallback() -> None:
    async def _run() -> tuple[discord.Embed, discord.Embed]:
        db = _FooterDb()
        footer_service = _build_footer_service(db)
        await footer_service.set_version('dev7.1')
        plain = discord.Embed(title='plain')
        attach_footer_meta(plain, service_name='status', contributors=[], used_local_processing=True)
        ai = discord.Embed(title='ai')
        attach_footer_meta(ai, service_name='riassunto', contributors=['gpt-4o-mini'], used_local_processing=False)

        await finalize_embeds([plain, ai], footer_service, default_service_name='status')
        return plain, ai

    plain, ai = asyncio.run(_run())

    assert plain.footer is not None
    assert plain.footer.text == 'Barcellometro dev7.1'
    assert ai.footer is not None
    assert ai.footer.text == 'Barcellometro dev7.1 · Dati elaborati con gpt-4o-mini'
