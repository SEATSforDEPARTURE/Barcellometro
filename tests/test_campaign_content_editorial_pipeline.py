import asyncio
from datetime import datetime, timezone
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
from app.services.database import DatabaseService


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
        assert metadata["page_map"][0]["type"] == "overview"

    asyncio.run(_run())


def test_horoscope_rewrite_is_single_batch_call_and_json_fallback() -> None:
    class _Ai:
        def __init__(self, output: str):
            self.ask_for_task = AsyncMock(return_value=output)

        def is_enabled(self):
            return True

        def get_model_config(self, _):
            return "ollama:qwen2.5:1.5b"

    payload = {"signs": {"Ariete": {"sign": "Ariete", "love": "a", "work": "b", "money": "c", "energy": "d", "friction": "e", "advice": "f"}}}
    for s in ["Toro","Gemelli","Cancro","Leone","Vergine","Bilancia","Scorpione","Sagittario","Capricorno","Acquario","Pesci"]:
        payload["signs"][s] = {"sign": s, "love": "a", "work": "b", "money": "c", "energy": "d", "friction": "e", "advice": "f"}

    async def _run_valid() -> None:
        ai = _Ai(json.dumps({k: {"love": "x", "work": "y", "money": "z", "energy": "w", "friction": "q", "advice": "p"} for k in payload["signs"]}))
        service = CampaignContentService(database=SimpleNamespace(), bot=SimpleNamespace(), ai_service=ai)
        await service._rewrite_horoscope_payload(payload)
        ai.ask_for_task.assert_awaited_once()
        assert ai.ask_for_task.await_args.args[0] == "campaign_editorial"

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


def test_load_message_record_accepts_aiosqlite_row_like_payload() -> None:
    class _RowLike:
        def __iter__(self):
            yield ("message_id", "123")
            yield ("guild_id", "1")
            yield ("channel_id", "2")
            yield ("service_type", "weather")
            yield ("config_id", 99)
            yield ("embeds_json", '[{"title":"A"},{"title":"B"}]')
            yield ("metadata_json", '{"page_map":[{"type":"overview","page":0}]}')
            yield ("current_index", "4")

    class _Db:
        async def get_campaign_content_message(self, _message_id):
            return _RowLike()

    async def _run() -> None:
        service = CampaignContentService(database=_Db(), bot=SimpleNamespace(), ai_service=None)
        row = await service.load_message_record("123")
        assert row is not None
        assert row["message_id"] == "123"
        assert row["service_type"] == "WEATHER"
        assert row["config_id"] == "99"
        assert len(row["embeds"]) == 2
        assert isinstance(row["metadata"], dict)
        assert row["current_index"] == 4

    asyncio.run(_run())


def test_load_message_record_handles_invalid_json() -> None:
    class _RowLike:
        def __iter__(self):
            yield ("message_id", "123")
            yield ("guild_id", "1")
            yield ("channel_id", "2")
            yield ("service_type", "news")
            yield ("config_id", 99)
            yield ("embeds_json", '{invalid')
            yield ("metadata_json", '{invalid')
            yield ("current_index", "0")

    class _Db:
        async def get_campaign_content_message(self, _message_id):
            return _RowLike()

    async def _run() -> None:
        service = CampaignContentService(database=_Db(), bot=SimpleNamespace(), ai_service=None)
        row = await service.load_message_record("123")
        assert row is not None
        assert row["embeds"] == []
        assert row["metadata"] == {}

    asyncio.run(_run())


def test_open_personal_navigator_clamps_target_index() -> None:
    class _Db:
        async def get_campaign_content_message(self, _message_id):
            return {
                "message_id": "777",
                "guild_id": "1",
                "channel_id": "2",
                "service_type": "WEATHER",
                "config_id": "9",
                "embeds_json": '[{"title":"P0"},{"title":"P1"}]',
                "metadata_json": '{"page_map": [{"type": "overview", "page": 0}]}',
                "current_index": 0,
            }

    class _Response:
        def __init__(self):
            self.send_message = AsyncMock()
            self._done = False

        def is_done(self):
            return self._done

    interaction = SimpleNamespace(message=SimpleNamespace(id=777), response=_Response())

    async def _run() -> None:
        service = CampaignContentService(database=_Db(), bot=SimpleNamespace(), ai_service=None)
        ok_low = await service.open_personal_navigator(interaction, target_index=-5, service_type="WEATHER")
        ok_high = await service.open_personal_navigator(interaction, target_index=55, service_type="WEATHER")
        assert ok_low is True and ok_high is True
        calls = interaction.response.send_message.await_args_list
        low_embed = calls[0].kwargs["embed"]
        high_embed = calls[1].kwargs["embed"]
        assert (low_embed.title or "") == "P0"
        assert (high_embed.title or "") == "P1"

    asyncio.run(_run())


def test_horoscope_rewrite_is_single_batch_call_and_json_fallback() -> None:
    class _Ai:
        def __init__(self, output: str):
            self.ask_for_task = AsyncMock(return_value=output)

        def is_enabled(self):
            return True

        def get_model_config(self, _):
            return "ollama:qwen2.5:1.5b"

    payload = {"signs": {"Ariete": {"sign": "Ariete", "love": "a", "work": "b", "money": "c", "energy": "d", "friction": "e", "advice": "f"}}}
    for s in ["Toro","Gemelli","Cancro","Leone","Vergine","Bilancia","Scorpione","Sagittario","Capricorno","Acquario","Pesci"]:
        payload["signs"][s] = {"sign": s, "love": "a", "work": "b", "money": "c", "energy": "d", "friction": "e", "advice": "f"}

    async def _run_valid() -> None:
        ai = _Ai(json.dumps({k: {"love": "x", "work": "y", "money": "z", "energy": "w", "friction": "q", "advice": "p"} for k in payload["signs"]}))
        service = CampaignContentService(database=SimpleNamespace(), bot=SimpleNamespace(), ai_service=ai)
        await service._rewrite_horoscope_payload(payload)
        ai.ask_for_task.assert_awaited_once()
        assert ai.ask_for_task.await_args.args[0] == "campaign_editorial"

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



def test_campaign_content_one_shot_disables_after_send() -> None:
    class DummyChannel:
        async def send(self, **kwargs):
            return type("M", (), {"id": 999})()

    class DummyBot:
        def get_channel(self, _channel_id: int):
            return DummyChannel()

        async def fetch_channel(self, _channel_id: int):
            return DummyChannel()

    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()
        service = CampaignContentService(db, DummyBot(), ai_service=None)
        guild_id = "1"
        channel_id = "2"
        cfg_id = await db.create_campaign_content_config(
            guild_id=guild_id,
            channel_id=channel_id,
            service_type="NEWS",
            enabled=True,
            time_local="10:00",
            interval_minutes=0,
            embed_title="T",
            embed_color="#112233",
            sources_json="[]",
            categories_json=None,
            next_run_at=datetime.now(timezone.utc).isoformat(),
        )
        config = await db.get_campaign_content_config(guild_id, cfg_id)
        assert config is not None
        await service._send_and_store(config, [discord.Embed(title="x")], "NEWS", configured_sources=[], used_sources=[], used_model=None, fallback_used=False, payload={})
        refreshed = await db.get_campaign_content_config(guild_id, cfg_id)
        assert refreshed is not None
        assert int(refreshed["enabled"]) == 0
        await db.close()

    asyncio.run(_run())
