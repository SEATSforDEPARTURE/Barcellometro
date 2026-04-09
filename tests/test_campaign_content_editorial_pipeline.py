import asyncio
from datetime import datetime, timezone
import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch

import discord

from tests._sqlite_stub import ensure_sqlite_stub

ensure_sqlite_stub()

if "openai" not in sys.modules:
    sys.modules["openai"] = types.SimpleNamespace(AsyncOpenAI=object)
if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace()

from app.services.campaign_content_fetchers import dedupe_news_items
from app.services.campaign_content_formatter import (
    build_horoscope_embeds,
    build_news_embeds,
    build_news_page_map,
    news_edition_label_for_datetime,
    build_weather_embeds,
)
from app.services.campaign_content_service import CampaignContentService
from app.services.database import DatabaseService


def _normalize_standardized_title(title: str | None) -> str:
    raw = (title or "").strip()
    if raw.startswith("__**") and raw.endswith("**__"):
        raw = raw[4:-4]
    return " ".join(raw.split()).upper()


def test_build_weather_embeds_page_order() -> None:
    embeds = build_weather_embeds(
        {"embed_title": "🌤️ METEO CRICETOSO"},
        {"regions": {"Nord": {"sampled_cities": []}, "Centro": {"sampled_cities": []}, "Sud e Isole": {"sampled_cities": []}}},
    )
    titles = [_normalize_standardized_title(e.title) for e in embeds]
    assert "OVERVIEW ITALIA" in titles[0]
    assert "NORD" in titles[1]
    assert "CENTRO" in titles[2]
    assert "SUD E ISOLE" in titles[3]


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
    assert len(embeds) == 1
    field_names = [field.name for field in embeds[0].fields]
    assert field_names[0] == "⚡ __**ULTIM'ORA**__"
    assert field_names[1] == "🌟 __**IN EVIDENZA**__"
    assert all("IN PRIMO PIANO" not in name for name in field_names)
    assert "__**SPORT IN PRIMO PIANO**__" not in " ".join(field_names)


def test_news_fallback_summary_uses_two_sentences_without_ai_summary() -> None:
    payload = {
        "categories": {
            "economia": [
                {
                    "title": "Mercati in movimento",
                    "summary": "",
                    "description": "<p>Prima frase pulita.</p><p>Seconda frase utile.</p><p>Terza frase da ignorare.</p>",
                    "source": "ansa.it",
                    "link": "https://example.com/mercati",
                }
            ]
        }
    }
    embeds = build_news_embeds({}, payload)
    field_value = embeds[0].fields[0].value
    assert "Prima frase pulita." in field_value
    assert "Seconda frase utile." in field_value
    assert "Terza frase da ignorare." not in field_value


def test_news_edition_label_switches_by_timeslot() -> None:
    morning = news_edition_label_for_datetime(datetime.fromisoformat("2026-04-09T05:30:00+02:00"))[0]
    afternoon = news_edition_label_for_datetime(datetime.fromisoformat("2026-04-09T12:30:00+02:00"))[0]
    evening = news_edition_label_for_datetime(datetime.fromisoformat("2026-04-09T18:30:00+02:00"))[0]
    night = news_edition_label_for_datetime(datetime.fromisoformat("2026-04-09T23:30:00+02:00"))[0]
    assert morning == "EDIZIONE MATTUTINA"
    assert afternoon == "EDIZIONE POMERIDIANA"
    assert evening == "EDIZIONE SERALE"
    assert night == "EDIZIONE NOTTURNA"


def test_news_editorial_categories_follow_order_and_cap_to_three() -> None:
    payload = {
        "configured_categories": ["economia", "sport", "cronaca", "politica", "tecnologia"],
        "categories": {
            "cronaca": [{"title": "Cronaca A", "summary": "S", "source": "ansa.it", "link": "https://example.com/1"}],
            "sport": [{"title": "Sport A", "summary": "S", "source": "ansa.it", "link": "https://example.com/2"}],
            "economia": [{"title": "Economia A", "summary": "S", "source": "ansa.it", "link": "https://example.com/3"}],
            "politica": [{"title": "Politica A", "summary": "S", "source": "ansa.it", "link": "https://example.com/4"}],
            "tecnologia": [{"title": "Tech A", "summary": "S", "source": "ansa.it", "link": "https://example.com/5"}],
        },
    }
    fields = [field.name for field in build_news_embeds({}, payload)[0].fields]
    editorial = [name for name in fields if "IN PRIMO PIANO" in name]
    assert len(editorial) == 3
    assert all("IN PRIMO PIANO" in name for name in editorial)


def test_news_title_has_emoji_outside_markdown() -> None:
    news = build_news_embeds(
        {},
        {"generated_at": "2026-04-09T13:00:00+02:00", "categories": {"cronaca": [{"title": "t", "summary": "s", "source": "ansa", "link": "https://x"}]}},
    )
    assert news[0].title == "📰 __**HAMSTER NEWS • EDIZIONE POMERIDIANA**__"


def test_news_description_uses_natural_greetings_by_daypart() -> None:
    cases = [
        ("2026-04-09T06:30:00+02:00", "Buon mattino"),
        ("2026-04-09T14:30:00+02:00", "Buon pomeriggio"),
        ("2026-04-09T20:30:00+02:00", "Buonasera"),
        ("2026-04-09T01:30:00+02:00", "Buona notte"),
    ]
    for generated_at, expected in cases:
        news = build_news_embeds(
            {},
            {"generated_at": generated_at, "categories": {"cronaca": [{"title": "t", "summary": "s", "source": "ansa", "link": "https://x"}]}},
        )
        description = news[0].description or ""
        assert not description.lstrip().startswith("🐹")
        assert expected in description
        assert "📰" in description
        assert "**Che ci racconta il mondo oggi?**" in description
        assert "Buona pomeriggio" not in description


def test_news_rewrite_prefers_ai_summary_over_raw_summary() -> None:
    class _Ai:
        def is_enabled(self):
            return True

        async def ask_for_task(self, *_args, **_kwargs):
            return "Mini sintesi cricetosa. Seconda frase."

        def get_model_config(self, _task):
            return "gpt-4.1-mini"

        def get_model_display_name(self, _task):
            return "gpt-4.1-mini"

    async def _run() -> None:
        service = CampaignContentService(database=object(), bot=object(), ai_service=_Ai())  # type: ignore[arg-type]
        payload = {"categories": {"cronaca": [{"title": "T", "summary": "Raw summary", "source": "ansa", "category": "cronaca"}]}}
        await service._rewrite_news_payload(payload)  # type: ignore[attr-defined]
        item = payload["categories"]["cronaca"][0]
        assert item["ai_summary"] == "Mini sintesi cricetosa. Seconda frase."
        assert item["summary"] == "Raw summary"

    asyncio.run(_run())


def test_news_rewrite_falls_back_when_ai_fails() -> None:
    class _Ai:
        def is_enabled(self):
            return True

        async def ask_for_task(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    async def _run() -> None:
        service = CampaignContentService(database=object(), bot=object(), ai_service=_Ai())  # type: ignore[arg-type]
        payload = {"categories": {"cronaca": [{"title": "T", "summary": "Prima. Seconda. Terza.", "source": "ansa", "category": "cronaca"}]}}
        await service._rewrite_news_payload(payload)  # type: ignore[attr-defined]
        item = payload["categories"]["cronaca"][0]
        assert item["summary_fallback_used"] is True
        assert "ai_summary" in item
        assert "👀" not in item["ai_summary"]
        assert "Terza frase da ignorare." not in item["ai_summary"]

    asyncio.run(_run())


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
    acquario = next(e for e in embeds if "ACQUARIO" in _normalize_standardized_title(e.title))
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
        def __init__(self):
            self.last_view = object()

        async def _get_channel(self):
            return self

        async def send(self, *args, **kwargs):
            self.last_view = kwargs.get("view")
            return SimpleNamespace(id=123)

    channel = _Channel()

    class _Bot:
        def get_channel(self, _id):
            return channel

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
        assert metadata["page_map"] == [{"type": "overview", "key": "overview", "label": "Inizio", "page": 0}]
        assert channel.last_view is None

    asyncio.run(_run())


def test_news_rewrite_sanitizes_prompt_leakage_prefixes() -> None:
    dirty = "🧃 In breve: Ecco la riscrizione del testo con tono leggero e ironico:\nNuova versione pulita."
    cleaned = CampaignContentService._sanitize_editorial_text(dirty)  # type: ignore[attr-defined]
    assert "Ecco la riscrizione" not in cleaned
    assert "tono leggero e ironico" not in cleaned
    assert cleaned == "Nuova versione pulita."


def test_news_summary_input_sanitization_removes_boilerplate_and_duplicates() -> None:
    service = CampaignContentService(database=object(), bot=object(), ai_service=None)  # type: ignore[arg-type]
    cleaned = service._build_news_summary_input(  # type: ignore[attr-defined]
        {
            "title": "- Ecco una possibile versione in italiano: Titolo pulito",
            "summary": "Titolo pulito. fonte: ansa.it continua a leggere",
            "description": "Ecco una possibile versione in italiano: dettaglio reale.",
            "category": "cronaca",
            "source": "ansa.it",
        }
    )
    assert cleaned["title"] == "Titolo pulito"
    assert "fonte:" not in cleaned["content"].lower()
    assert "continua a leggere" not in cleaned["content"].lower()
    assert "versione in italiano" not in cleaned["content"].lower()
    assert cleaned["content"] == "dettaglio reale."


def test_execute_news_service_reads_csv_categories_fallback_column() -> None:
    class _Db:
        async def upsert_campaign_content_message(self, **_kwargs):
            return None

        async def update_campaign_content_next_run(self, **_kwargs):
            return None

        async def set_campaign_content_enabled(self, **_kwargs):
            return None

    class _Channel(discord.abc.Messageable):
        async def _get_channel(self):
            return self

        async def send(self, *args, **kwargs):
            return SimpleNamespace(id=999)

    class _Bot:
        def get_channel(self, _id):
            return _Channel()

    async def _run() -> None:
        service = CampaignContentService(database=_Db(), bot=_Bot(), ai_service=None)
        config = {
            "guild_id": "1",
            "channel_id": "2",
            "id": 5,
            "interval_minutes": 0,
            "service_type": "NEWS",
            "categories": "cronaca,spettacolo",
            "categories_json": None,
            "sources_json": '["ansa"]',
        }
        with patch("app.services.campaign_content_service.fetch_news_content", return_value={"categories": {}, "sources": [], "used_sources": []}) as mocked_fetch:
            await service.execute_news_service(config)
        mocked_fetch.assert_called_once()
        args, _kwargs = mocked_fetch.call_args
        assert args[1] == ["cronaca", "spettacolo"]

    asyncio.run(_run())


def test_horoscope_rewrite_is_single_batch_call_and_json_fallback() -> None:
    class _Ai:
        def __init__(self, output: str):
            self.ask_for_task = AsyncMock(return_value=output)

        def is_enabled(self):
            return True

        def get_model_config(self, _):
            return "ollama:qwen2.5:1.5b"

        def get_model_display_name(self, _):
            return "qwen2.5:1.5b"

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


def test_news_page_map_has_only_overview_entry() -> None:
    page_map = build_news_page_map(
        {
            "categories": {
                "cronaca": [{"title": "a"}],
                "sport": [{"title": "b"}],
            }
        }
    )
    assert page_map == [{"type": "overview", "key": "overview", "label": "Inizio", "page": 0}]


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
    class DummyChannel(discord.abc.Messageable):
        async def _get_channel(self):
            return self

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
            extras_json=None,
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


def test_horoscope_publish_continues_when_editorial_ai_fails() -> None:
    class _Channel(discord.abc.Messageable):
        async def _get_channel(self):
            return self

        async def send(self, *args, **kwargs):
            return SimpleNamespace(id=321)

    class _Bot:
        def get_channel(self, _id):
            return _Channel()

    class _Ai:
        def is_enabled(self):
            return True

        async def ask_for_task(self, *args, **kwargs):
            raise TimeoutError("editorial-timeout")

    async def _run() -> None:
        payload = {"signs": {"Ariete": {"love": "orig", "work": "orig", "money": "orig", "energy": "orig", "friction": "orig", "advice": "orig"}}}
        for s in ["Toro", "Gemelli", "Cancro", "Leone", "Vergine", "Bilancia", "Scorpione", "Sagittario", "Capricorno", "Acquario", "Pesci"]:
            payload["signs"][s] = {"love": "orig", "work": "orig", "money": "orig", "energy": "orig", "friction": "orig", "advice": "orig"}
        db = SimpleNamespace(upsert_campaign_content_message=AsyncMock(), update_campaign_content_next_run=AsyncMock())
        service = CampaignContentService(database=db, bot=_Bot(), ai_service=_Ai())
        from unittest.mock import patch

        with patch("app.services.campaign_content_service.fetch_horoscope_content", return_value=payload):
            await service.execute_horoscope_service({"guild_id": "1", "channel_id": "2", "id": 4, "interval_minutes": 60, "sources_json": "[]"})

        metadata = json.loads(db.upsert_campaign_content_message.await_args.kwargs["metadata_json"])
        assert metadata["used_model"] is None
        assert metadata["ai_model_used"] is None

    asyncio.run(_run())


def test_invalid_editorial_json_does_not_fail_horoscope_publish() -> None:
    class _Ai:
        def is_enabled(self):
            return True

        async def ask_for_task(self, *args, **kwargs):
            return "not-json"

    async def _run() -> None:
        payload = {"signs": {"Ariete": {"love": "orig", "work": "orig", "money": "orig", "energy": "orig", "friction": "orig", "advice": "orig"}}}
        for s in ["Toro", "Gemelli", "Cancro", "Leone", "Vergine", "Bilancia", "Scorpione", "Sagittario", "Capricorno", "Acquario", "Pesci"]:
            payload["signs"][s] = {"love": "orig", "work": "orig", "money": "orig", "energy": "orig", "friction": "orig", "advice": "orig"}
        service = CampaignContentService(database=SimpleNamespace(), bot=SimpleNamespace(), ai_service=_Ai())
        used_model = await service._rewrite_horoscope_payload(payload)
        assert used_model is None
        assert payload["signs"]["Ariete"]["love"] == "orig"

    asyncio.run(_run())


def test_weather_and_news_publish_succeed_when_rewrite_text_ai_fails() -> None:
    class _Channel(discord.abc.Messageable):
        async def _get_channel(self):
            return self

        async def send(self, *args, **kwargs):
            return SimpleNamespace(id=111)

    class _Bot:
        def get_channel(self, _id):
            return _Channel()

    class _Ai:
        def is_enabled(self):
            return True

        async def ask_for_task(self, *args, **kwargs):
            raise RuntimeError("ai-down")

    from unittest.mock import patch

    async def _run() -> None:
        db = SimpleNamespace(upsert_campaign_content_message=AsyncMock(), update_campaign_content_next_run=AsyncMock())
        service = CampaignContentService(database=db, bot=_Bot(), ai_service=_Ai())
        weather_payload = {"regions": {"Nord": {"summary": "meteo ok", "source_points": []}}, "used_sources": []}
        news_payload = {"categories": {"cronaca": [{"title": "t", "summary": "s", "category": "cronaca", "source": "ansa", "link": "https://x"}]}, "used_sources": []}
        with patch("app.services.campaign_content_service.fetch_weather_content", return_value=weather_payload):
            await service.execute_weather_service({"guild_id": "1", "channel_id": "2", "id": 9, "interval_minutes": 60, "sources_json": "[]"})
        with patch("app.services.campaign_content_service.fetch_news_content", return_value=news_payload):
            await service.execute_news_service(
                {"guild_id": "1", "channel_id": "2", "id": 10, "interval_minutes": 60, "sources_json": "[]", "categories_json": "[]"}
            )
        assert db.upsert_campaign_content_message.await_count == 2

    asyncio.run(_run())
