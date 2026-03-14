import asyncio
import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

if "openai" not in sys.modules:
    sys.modules["openai"] = types.SimpleNamespace(AsyncOpenAI=object)
if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(Connection=object)

from app.services.campaign_content_fetchers import dedupe_news_items
from app.services.campaign_content_formatter import build_horoscope_embeds, build_news_embeds, build_weather_embeds
from app.services.campaign_content_service import CampaignContentService


def test_build_weather_embeds_page_order() -> None:
    embeds = build_weather_embeds(
        {"embed_title": "🌤️ METEO CRICETOSO"},
        {"regions": {"Nord": {"sampled_cities": []}, "Centro": {"sampled_cities": []}, "Sud e Isole": {"sampled_cities": []}}},
    )
    titles = [e.title for e in embeds]
    assert "Overview Italia" in (titles[0] or "")
    assert "Nord" in (titles[1] or "")
    assert "Centro" in (titles[2] or "")
    assert "Sud e Isole" in (titles[3] or "")


def test_build_news_embeds_respects_config_order_and_dedupes() -> None:
    payload = {
        "categories": {
            "cronaca": [{"title": "Titolo uguale", "summary": "S1", "source": "ansa.it", "link": "https://example.com/a"}],
            "sport": [{"title": "Titolo uguale", "summary": "S2 più lungo", "source": "open.online", "link": "https://example.com/a/"}],
            "tecnologia": [{"title": "Tech 1", "summary": "S3", "source": "wired.it", "link": "https://example.com/c"}],
        }
    }
    deduped = dedupe_news_items(payload["categories"]["cronaca"] + payload["categories"]["sport"] + payload["categories"]["tecnologia"])
    assert len(deduped) == 2
    embeds = build_news_embeds({"embed_title": "📰 NOTIZIARIO"}, payload)
    assert "Inizio" in (embeds[0].title or "")
    assert "Cronaca" in (embeds[1].title or "")
    assert "Sport" in (embeds[2].title or "")


def test_build_horoscope_embeds_strip_inner_headings() -> None:
    payload = {
        "signs": {
            "Acquario": {
                "love": "Acquario Love Alert: giornata positiva in amore.",
                "work": "Acquario: lavoro in recupero.",
                "money": "Money Vibes: prudenza.",
                "energy": "Energia del genio: alta.",
                "friction": "Con chi ti stressa.",
                "advice": "Respira.",
                "confidence": 1,
            }
        }
    }
    # fill required signs quickly
    for s in ["Ariete","Toro","Gemelli","Cancro","Leone","Vergine","Bilancia","Scorpione","Sagittario","Capricorno","Pesci"]:
        payload["signs"][s] = {"love":"ok","work":"ok","money":"ok","energy":"ok","friction":"ok","advice":"ok","confidence":1}
    embeds = build_horoscope_embeds({"embed_title": "🔮 OROSCOPO CRICETOSO"}, payload)
    acquario = next(e for e in embeds if (e.title or "").endswith("Acquario"))
    values = " ".join(f.value for f in acquario.fields)
    assert "Love Alert" not in values
    assert "Energia del genio" not in values


def test_send_and_store_metadata_contains_page_map() -> None:
    class _Db:
        async def upsert_campaign_content_message(self, **kwargs):
            self.kwargs = kwargs

        async def update_campaign_content_next_run(self, **kwargs):
            self.next_kwargs = kwargs

    class _Channel(discord.abc.Messageable):
        async def _get_channel(self):
            return self

        async def send(self, *args, **kwargs):
            return SimpleNamespace(id=123)

    class _Bot:
        def get_channel(self, _id):
            return _Channel()

    async def _run() -> None:
        db = _Db()
        service = CampaignContentService(database=db, bot=_Bot(), ai_service=None)
        service._build_campaign_footer = lambda **kwargs: asyncio.sleep(0, result="footer test")
        config = {"guild_id": "1", "channel_id": "2", "id": 99, "interval_minutes": 60}
        payload = {"categories": {"cronaca": [{"title": "t", "summary": "s", "source": "ansa", "link": "https://x"}]}}
        await service._send_and_store(
            config,
            [discord.Embed(title="x"), discord.Embed(title="y")],
            "NEWS",
            configured_sources=["ansa", "repubblica"],
            used_sources=["https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml"],
            used_model="gpt-4o",
            fallback_used=False,
            payload=payload,
        )
        metadata = json.loads(db.kwargs["metadata_json"])
        assert "page_map" in metadata
        assert metadata["page_map"][0]["label"] == "⏮️ INIZIO"

    asyncio.run(_run())


def test_horoscope_rewrite_is_single_batch_call_and_json_fallback() -> None:
    class _Ai:
        def __init__(self, output: str):
            self.ask_general = AsyncMock(return_value=output)

        def is_enabled(self):
            return True

        def get_model(self, _):
            return "gpt-4o"

    payload = {"signs": {"Ariete": {"sign": "Ariete", "love": "a", "work": "b", "money": "c", "energy": "d", "friction": "e", "advice": "f"}}}
    for s in ["Toro","Gemelli","Cancro","Leone","Vergine","Bilancia","Scorpione","Sagittario","Capricorno","Acquario","Pesci"]:
        payload["signs"][s] = {"sign": s, "love": "a", "work": "b", "money": "c", "energy": "d", "friction": "e", "advice": "f"}

    async def _run_valid() -> None:
        ai = _Ai(json.dumps({k: {"love": "x", "work": "y", "money": "z", "energy": "w", "friction": "q", "advice": "p"} for k in payload["signs"]}))
        service = CampaignContentService(database=SimpleNamespace(), bot=SimpleNamespace(), ai_service=ai)
        await service._rewrite_horoscope_payload(payload)
        ai.ask_general.assert_awaited_once()

    async def _run_invalid() -> None:
        ai = _Ai("not-json")
        local_payload = {"signs": {"Ariete": {"sign": "Ariete", "love": "orig", "work": "orig", "money": "orig", "energy": "orig", "friction": "orig", "advice": "orig"}}}
        for s in ["Toro","Gemelli","Cancro","Leone","Vergine","Bilancia","Scorpione","Sagittario","Capricorno","Acquario","Pesci"]:
            local_payload["signs"][s] = {"sign": s, "love": "orig", "work": "orig", "money": "orig", "energy": "orig", "friction": "orig", "advice": "orig"}
        service = CampaignContentService(database=SimpleNamespace(), bot=SimpleNamespace(), ai_service=ai)
        await service._rewrite_horoscope_payload(local_payload)
        assert local_payload["signs"]["Ariete"]["love"] == "orig"

    asyncio.run(_run_valid())
    asyncio.run(_run_invalid())
