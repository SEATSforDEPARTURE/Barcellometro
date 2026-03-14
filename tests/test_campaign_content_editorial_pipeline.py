import asyncio
import json
import sys
import types
from types import SimpleNamespace

import discord

if "openai" not in sys.modules:
    sys.modules["openai"] = types.SimpleNamespace(AsyncOpenAI=object)
if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(Connection=object)

from app.services.campaign_content_formatter import SIGN_EMOJIS, build_horoscope_embeds, build_news_embeds, build_weather_embeds
from app.services.campaign_content_service import CampaignContentService


def test_horoscope_overview_is_rich_and_signs_distinct_and_emojis() -> None:
    payload = {
        "signs": {
            sign: {
                "sign": sign,
                "love": f"Amore specifico {sign}",
                "work": f"Lavoro specifico {sign}",
                "money": f"Soldi specifici {sign}",
                "energy": f"Energia specifica {sign}",
                "friction": f"Friction {sign}",
                "advice": f"Advice {sign}",
                "tone": f"tono-{sign}",
                "confidence": 0.7,
                "fallback_used": False,
            }
            for sign in SIGN_EMOJIS
        }
    }
    embeds = build_horoscope_embeds({"embed_title": "🔮 OROSCOPO CRICETOSO"}, payload)
    assert len(embeds) == 13
    overview_text = embeds[0].description or ""
    assert "✨ **Mood del giorno**" in overview_text
    assert "🔥 **Segni più frizzanti**" in overview_text
    assert "🌧️ **Segni da trattare con dolcezza**" in overview_text
    assert "💼 **Focus lavoro/energia**" in overview_text
    assert "🐹 **Consiglio cricetoso**" in overview_text
    sign_field_values = [embed.fields[0].value for embed in embeds[1:]]
    assert len(set(sign_field_values)) == 12


def test_weather_and_news_overview_are_richer() -> None:
    weather = build_weather_embeds(
        {"embed_title": "🌤️ METEO CRICETOSO"},
        {
            "regions": {
                "Nord": {
                    "summary": "Nord variabile",
                    "precipitation_summary": "possibili piogge",
                    "wind_summary": "vento medio 12 km/h",
                    "sampled_cities": [
                        {"city": "Milano", "temperature": 21, "windspeed": 8, "condition": "pioggia"},
                        {"city": "Torino", "temperature": 20, "windspeed": 10, "condition": "nuvoloso"},
                        {"city": "Genova", "temperature": 22, "windspeed": 14, "condition": "rovesci"},
                    ],
                },
                "Centro": {
                    "summary": "Centro sereno",
                    "precipitation_summary": "precipitazioni poco probabili",
                    "wind_summary": "vento medio 5 km/h",
                    "sampled_cities": [
                        {"city": "Roma", "temperature": 25, "windspeed": 5, "condition": "sereno"},
                        {"city": "Firenze", "temperature": 24, "windspeed": 6, "condition": "sereno"},
                        {"city": "Perugia", "temperature": 23, "windspeed": 4, "condition": "quasi sereno"},
                    ],
                },
                "Sud e Isole": {
                    "summary": "Sud caldo",
                    "precipitation_summary": "precipitazioni poco probabili",
                    "wind_summary": "vento medio 11 km/h",
                    "sampled_cities": [
                        {"city": "Napoli", "temperature": 28, "windspeed": 12, "condition": "sereno"},
                        {"city": "Palermo", "temperature": 29, "windspeed": 14, "condition": "sereno"},
                        {"city": "Cagliari", "temperature": 30, "windspeed": 9, "condition": "sereno"},
                    ],
                },
            }
        },
    )
    assert "Area più instabile" in (weather[0].description or "")
    assert "Range termico nazionale" in (weather[0].description or "")
    assert "Milano" in (weather[1].description or "")

    news = build_news_embeds(
        {"embed_title": "📰 NOTIZIARIO"},
        {
            "categories": {
                "cronaca": [
                    {"title": "Titolo 1", "summary": "Sommario 1", "source": "ansa.it", "link": "https://example.com/1"},
                    {"title": "Titolo 2", "summary": "Sommario 2", "source": "ansa.it", "link": "https://example.com/2"},
                ],
                "sport": [
                    {"title": "Titolo 3", "summary": "Sommario 3", "source": "open.online", "link": "https://example.com/3"},
                ],
            }
        },
    )
    assert "Cosa fa più rumore oggi" in (news[0].description or "")
    assert "Top highlight" in (news[0].description or "")


def test_horoscope_similarity_guard_reformats_duplicate_outputs() -> None:
    service = CampaignContentService(database=SimpleNamespace(), bot=SimpleNamespace(), ai_service=None)
    payload = {
        "signs": {
            "Ariete": {"love": "test comune", "work": "test comune", "money": "x", "energy": "y", "friction": "z", "advice": "a"},
            "Toro": {"love": "test comune", "work": "test comune", "money": "x", "energy": "y", "friction": "z", "advice": "a"},
        }
    }
    service._enforce_horoscope_diversity(payload)
    assert "Versione personalizzata" in payload["signs"]["Toro"]["advice"]


def test_send_and_store_metadata_tracks_configured_and_used_sources_and_ai_model() -> None:
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
        await service._send_and_store(
            config,
            [discord.Embed(title="x")],
            "NEWS",
            configured_sources=["ansa", "repubblica"],
            used_sources=["https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml"],
            used_model="gpt-4o",
            fallback_used=False,
        )
        metadata = json.loads(db.kwargs["metadata_json"])
        assert metadata["configured_sources"] == ["ansa", "repubblica"]
        assert metadata["used_sources"] == ["https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml"]
        assert metadata["ai_model_used"] == "gpt-4o"
        assert metadata["fallback_used"] is False

    asyncio.run(_run())
