import asyncio
from datetime import datetime, timezone
import json
import re
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
    SIGN_ORDER,
    build_horoscope_embeds,
    build_horoscope_page_map,
    build_news_embeds,
    build_news_page_map,
    build_weather_page_map,
    enforce_embed_size_limit,
    news_edition_label_for_datetime,
    build_weather_embeds,
)
from app.services.campaign_content_service import CampaignContentService
from app.services.database import DatabaseService
from app.shared.discord.embed_limits import (
    DISCORD_MAX_EMBED_TOTAL_CHARS,
    compute_embed_text_size,
    compute_embeds_message_text_size,
    is_valid_embed,
    split_embeds_for_discord_messages,
)

_HOROSCOPE_ENGLISH_RESIDUALS = (
    "youre",
    "you",
    "your",
    "channel",
    "brainstorming",
    "unexpected blessings",
    "today",
    "sessions",
)


def _normalize_standardized_title(title: str | None) -> str:
    raw = (title or "").strip()
    if raw.startswith("__**") and raw.endswith("**__"):
        raw = raw[4:-4]
    return " ".join(raw.split()).upper()


def test_build_weather_embeds_page_order() -> None:
    embeds = build_weather_embeds(
        {"embed_title": "🌤️ METEO CRICETOSO"},
        {"regions": {"Nord": {"sampled_cities": []}, "Centro": {"sampled_cities": []}, "Sud": {"sampled_cities": []}, "Isole": {"sampled_cities": []}}},
    )
    titles = [_normalize_standardized_title(e.title) for e in embeds]
    assert titles[0] == "🌦️ __**METEO CRICETOSO • PANORAMICA**__"
    assert titles[1] == "🌦️ __**METEO CRICETOSO • LE AREE**__"
    assert len(embeds) == 2
    names = [field.name for field in embeds[0].fields]
    detail_names = [field.name for field in embeds[1].fields]
    assert "🌩️ __**AREA PIÙ INSTABILE**__" in names
    assert "🌤️ __**AREA PIÙ SERENA**__" in names
    assert "🌡️ __**RANGE TERMICO**__" not in names
    assert all("NORD" not in name for name in names)
    assert any("NORD" in name for name in detail_names)
    assert any("CENTRO" in name for name in detail_names)
    assert any("SUD" in name for name in detail_names)
    assert any("ISOLE" in name for name in detail_names)
    assert detail_names[-1] == "🌡️ __**RANGE TERMICO**__"
    assert all("SUD E ISOLE" not in name for name in names)


def test_weather_embed_renders_sud_and_isole_as_distinct_fields_when_both_selected() -> None:
    embeds = build_weather_embeds(
        {"embed_title": "🌤️ METEO CRICETOSO", "categories_json": "sud,isole"},
        {
            "regions": {
                "Sud": {"sampled_cities": [{"city": "Napoli", "temperature": 27, "windspeed": 8, "condition": "sereno"}]},
                "Isole": {"sampled_cities": [{"city": "Palermo", "temperature": 28, "windspeed": 9, "condition": "sereno"}]},
            }
        },
    )
    names = [field.name for field in embeds[1].fields]
    assert any("SUD" in name for name in names)
    assert any("ISOLE" in name for name in names)
    assert all("SUD E ISOLE" not in name for name in names)
    field_map = {field.name: field.value or "" for field in embeds[1].fields}
    assert field_map["📍 __**SUD**__"].splitlines()[0].startswith("• ")
    assert not field_map["📍 __**SUD**__"].splitlines()[0].startswith("• 🐹")
    assert "• **Napoli** · **27°C** · vento **8 km/h** · sereno" in field_map["📍 __**SUD**__"]
    assert "• **Focus area:**" in field_map["📍 __**SUD**__"]


def test_weather_page_map_matches_total_pages() -> None:
    assert build_weather_page_map(2) == [
        {"type": "overview", "key": "overview", "label": "Inizio", "page": 0},
        {"type": "areas", "key": "areas_1", "label": "Aree · Pagina 1", "page": 1},
    ]


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
    assert len(embeds) == 2
    field_names = [field.name for field in embeds[0].fields]
    assert field_names[0] == "⚡ __**ULTIM'ORA**__"
    assert field_names[1] == "🌟 __**IN EVIDENZA**__"
    assert embeds[1].title == "📰 __**HAMSTER NEWS • LE NOTIZIE**__"


def test_news_fallback_summary_uses_single_sentence_without_ai_summary() -> None:
    payload = {
        "categories": {
            "economia": [
                {
                    "title": "Mercati in movimento",
                    "summary": "",
                    "description": "<p>Prima frase pulita.</p><p></p><p>Terza frase da ignorare.</p>",
                    "source": "ansa.it",
                    "link": "https://example.com/mercati",
                }
            ]
        }
    }
    embeds = build_news_embeds({}, payload)
    field_value = embeds[0].fields[0].value
    assert "Prima frase pulita." in field_value
    assert "Terza frase da ignorare." not in field_value


def test_news_fallback_summary_with_one_sentence_keeps_single_sentence() -> None:
    payload = {
        "categories": {
            "economia": [
                {
                    "title": "Mercati in movimento",
                    "summary": "",
                    "description": "<p>Solo una frase completa.</p>",
                    "source": "ansa.it",
                    "link": "https://example.com/mercati",
                }
            ]
        }
    }
    field_value = build_news_embeds({}, payload)[0].fields[0].value
    assert "Solo una frase completa." in field_value
    assert "Solo una frase completa.." not in field_value


def test_news_fallback_summary_never_cuts_sentence_midway() -> None:
    payload = {
        "categories": {
            "economia": [
                {
                    "title": "Mercati in movimento",
                    "summary": "",
                    "description": "<p>Prima frase molto lunga ma completa.</p><p>Seconda frase con chiusura!</p><p>Terza da escludere.</p>",
                    "source": "ansa.it",
                    "link": "https://example.com/mercati",
                }
            ]
        }
    }
    field_value = build_news_embeds({}, payload)[0].fields[0].value
    assert "Prima frase molto lunga ma completa." in field_value
    assert "Terza da escludere." not in field_value


def test_news_explicit_summary_is_preferred_over_description_fallback() -> None:
    payload = {
        "categories": {
            "economia": [
                {
                    "title": "Mercati in movimento",
                    "summary": "Sintesi editoriale pronta.",
                    "description": "<p>Prima frase.</p><p>Seconda frase.</p><p>Terza frase da ignorare.</p>",
                    "source": "ansa.it",
                    "link": "https://example.com/mercati",
                }
            ]
        }
    }
    field_value = build_news_embeds({}, payload)[0].fields[0].value
    assert "sintesi editoriale pronta." in field_value.lower()
    assert "Terza frase da ignorare." not in field_value


def test_news_highlight_formatting_survives_fallback_rendering() -> None:
    payload = {
        "categories": {
            "tecnologia": [
                {
                    "title": "Lancio piattaforma",
                    "summary": "",
                    "description": "<p>Accordo con Netflix per nuovi contenuti.</p><p></p><p>Terza frase da ignorare.</p>",
                    "source": "wired.it",
                    "link": "https://example.com/tech",
                }
            ]
        }
    }
    field_value = build_news_embeds({}, payload)[0].fields[0].value
    assert "Netflix" in field_value
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


def test_news_editorial_categories_follow_order_without_legacy_cap() -> None:
    payload = {
        "configured_categories": ["economia", "sport", "cronaca", "politica", "tecnologia"],
        "categories": {
            "cronaca": [{"title": "Cronaca: arresto dopo indagini della procura", "summary": "S", "source": "ansa.it", "link": "https://example.com/1"}],
            "sport": [{"title": "Sport: partita decisa al 90esimo", "summary": "S", "source": "ansa.it", "link": "https://example.com/2"}],
            "economia": [{"title": "Economia A", "summary": "Mercati e inflazione in primo piano", "source": "ansa.it", "link": "https://example.com/3"}],
            "politica": [{"title": "Politica: scontro tra governo e opposizione", "summary": "S", "source": "ansa.it", "link": "https://example.com/4"}],
            "tecnologia": [{"title": "Nuovo software AI per smartphone", "summary": "S", "source": "ansa.it", "link": "https://example.com/5"}],
        },
    }
    embeds = build_news_embeds({}, payload)
    editorial = [field.name for field in embeds[1].fields]
    assert len(editorial) == 3
    assert "⚽ __**SPORT**__" in editorial
    assert "🏛️ __**POLITICA**__" in editorial
    assert "💻 __**TECNOLOGIA**__" in editorial or "💼 __**ECONOMIA**__" in editorial


def test_news_embed_has_single_emoji_summary_per_slot() -> None:
    payload = {
        "configured_categories": ["cronaca", "politica", "tecnologia"],
        "categories": {
            "cronaca": [{"title": "Tragedia in montagna con due vittime", "summary": "Soccorsi sul posto.", "source": "ansa.it", "link": "https://example.com/c1"}],
            "politica": [{"title": "Scontro in Parlamento sulla riforma", "summary": "Dibattito acceso in aula.", "source": "ansa.it", "link": "https://example.com/p1"}],
            "tecnologia": [{"title": "Attacco informatico a una grande piattaforma", "summary": "Esperti al lavoro per il ripristino.", "source": "wired.it", "link": "https://example.com/t1"}],
        },
    }
    embeds = build_news_embeds({}, payload)
    fields = [*embeds[0].fields, *embeds[1].fields]
    target_fields = [f for f in fields if "ULTIM'ORA" in f.name or "IN EVIDENZA" in f.name or "CRONACA" in f.name or "POLITICA" in f.name or "TECNOLOGIA" in f.name]
    for field in target_fields:
        summary = str(field.value).split("\n")[1].strip()
        assert summary.endswith(("👀", "🤹", "📈", "⚡", "🎭", "😔", "🫥"))
        assert summary.count("👀") + summary.count("🤹") + summary.count("📈") + summary.count("⚡") + summary.count("🎭") + summary.count("😔") + summary.count("🫥") == 1


def test_news_title_has_emoji_outside_markdown() -> None:
    news = build_news_embeds(
        {},
        {"generated_at": "2026-04-09T13:00:00+02:00", "categories": {"cronaca": [{"title": "t", "summary": "s", "source": "ansa", "link": "https://x"}]}},
    )
    assert news[0].title == "📰 __**HAMSTER NEWS • PANORAMICA**__"
    assert news[1].title == "📰 __**HAMSTER NEWS • LE NOTIZIE**__"


def test_news_category_slot_is_skipped_when_item_does_not_match_requested_category() -> None:
    payload = {
        "configured_categories": ["tecnologia", "politica"],
        "categories": {
            "cronaca": [
                {
                    "title": "Incidente in autostrada, traffico bloccato",
                    "summary": "Code per chilometri e intervento dei soccorsi.",
                    "source": "ansa.it",
                    "link": "https://example.com/cronaca-filler-1",
                    "published_at": "2026-04-09T08:00:00+00:00",
                },
                {
                    "title": "Aggiornamento viabilità dopo il maltempo",
                    "summary": "Chiusure e deviazioni nelle prossime ore.",
                    "source": "ansa.it",
                    "link": "https://example.com/cronaca-filler-2",
                    "published_at": "2026-04-09T07:00:00+00:00",
                },
            ],
            "tecnologia": [
                {
                    "title": "FMI rivede il PIL: crescita debole e inflazione in aumento",
                    "summary": "Il rapporto parla di mercati, debito e banche centrali.",
                    "source": "wired.it",
                    "link": "https://example.com/economia-in-tech",
                    "category": "tecnologia",
                }
            ],
            "politica": [
                {
                    "title": "Il governo presenta un nuovo decreto in Senato",
                    "summary": "Maggioranza e opposizione al confronto.",
                    "source": "ansa.it",
                    "link": "https://example.com/politica-ok",
                    "category": "politica",
                    "classified_categories": ["politica"],
                }
            ],
        },
    }
    embeds = build_news_embeds({}, payload)
    joined = " ".join(field.name for field in embeds[1].fields)
    assert "TECNOLOGIA" not in joined
    assert "POLITICA" in joined


def test_news_description_uses_natural_greetings_by_daypart() -> None:
    cases = [
        ("2026-04-09T06:30:00+02:00", "**Buongiorno**"),
        ("2026-04-09T14:30:00+02:00", "**Buon pomeriggio**"),
        ("2026-04-09T20:30:00+02:00", "**Buona sera**"),
        ("2026-04-09T01:30:00+02:00", "**Buonanotte**"),
    ]
    for generated_at, expected in cases:
        news = build_news_embeds(
            {},
            {"generated_at": generated_at, "categories": {"cronaca": [{"title": "t", "summary": "s", "source": "ansa", "link": "https://x"}]}},
        )
        description = news[0].description or ""
        assert not description.lstrip().startswith("🐹")
        assert expected in description
        assert "**Barcellometro in regia**" in description
        assert "📰" in description
        assert "Che ci racconta il mondo oggi?" not in description
        assert len(news) == 2
        assert news[1].description == "*Che ci racconta il mondo oggi?*"
        assert "Buona pomeriggio" not in description


def test_news_rewrite_prefers_ai_summary_over_raw_summary() -> None:
    class _Ai:
        def is_enabled(self):
            return True

        async def ask_for_task(self, *_args, **_kwargs):
            return "Mini sintesi cricetosa 👀"

        def get_model_config(self, _task):
            return "gpt-4.1-mini"

        def get_model_display_name(self, _task):
            return "gpt-4.1-mini"

    async def _run() -> None:
        service = CampaignContentService(database=object(), bot=object(), ai_service=_Ai())  # type: ignore[arg-type]
        payload = {"categories": {"cronaca": [{"title": "T", "summary": "Raw summary", "source": "ansa", "category": "cronaca"}]}}
        await service._rewrite_news_payload(payload)  # type: ignore[attr-defined]
        item = payload["categories"]["cronaca"][0]
        assert item["ai_summary"] == "Mini sintesi cricetosa 👀"
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
        assert not item["ai_summary"].lstrip().startswith(("👀", "🤹", "📈", "⚡", "🎭", "🫥", "😔"))
        assert item["ai_summary"].endswith(("👀", "🤹", "📈", "⚡", "🎭", "🫥", "😔"))
        assert "Terza frase da ignorare." not in item["ai_summary"]

    asyncio.run(_run())


def test_build_horoscope_embeds_keeps_full_sign_text_unchanged() -> None:
    payload = {
        "signs": {
            "Acquario": {
                "horoscope": "Acquario Love Alert: giornata positiva in amore. Energia del genio: alta. 😎",
                "confidence": 1,
            }
        }
    }
    # fill required signs quickly
    for s in ["Ariete","Toro","Gemelli","Cancro","Leone","Vergine","Bilancia","Scorpione","Sagittario","Capricorno","Pesci"]:
        payload["signs"][s] = {"horoscope": "ok", "confidence": 1}
    embeds = build_horoscope_embeds({"embed_title": "🔮 OROSCOPO CRICETOSO"}, payload)
    assert len(embeds) >= 2
    acquario_field = next(field for embed in embeds[1:] for field in embed.fields if "ACQUARIO" in field.name)
    values = acquario_field.value or ""
    assert values == "- Acquario Love Alert: giornata positiva in amore. Energia del genio: alta. 😎"


def test_build_horoscope_embeds_paginate_signs_and_respect_embed_limits() -> None:
    verbose = (
        "Frase molto lunga ma utile per il contesto editoriale quotidiano. "
        "Seconda frase per spingere il limite senza perdere leggibilità. "
    ) * 8
    payload = {
        "generated_at": "2026-04-09T14:30:00+00:00",
        "signs": {
            sign: {"horoscope": verbose, "confidence": 1.0}
            for sign in SIGN_ORDER
        },
    }
    embeds = build_horoscope_embeds({}, payload)
    assert len(embeds) >= 2
    assert embeds[0].title is not None
    assert "OROSCOPO" in embeds[0].title.upper()
    assert all(sign.upper() not in " ".join(field.name.upper() for field in embeds[0].fields) for sign in SIGN_ORDER)
    assert any(
        any(sign.upper() in field.name.upper() for sign in SIGN_ORDER for field in embed.fields)
        for embed in embeds[1:]
    )
    assert all(is_valid_embed(embed) for embed in embeds)
    assert all(len(embed) <= DISCORD_MAX_EMBED_TOTAL_CHARS for embed in embeds)
    assert all(len(embed.fields) <= 25 for embed in embeds)
    assert all(len(field.value or "") <= 1024 for embed in embeds for field in embed.fields)


def test_build_horoscope_page_map_matches_embed_count() -> None:
    page_map = build_horoscope_page_map(4)
    assert page_map == [
        {"type": "overview", "key": "overview", "label": "Inizio", "page": 0},
        {"type": "signs", "key": "signs_1", "label": "Segni · Pagina 1", "page": 1},
        {"type": "signs", "key": "signs_2", "label": "Segni · Pagina 2", "page": 2},
        {"type": "signs", "key": "signs_3", "label": "Segni · Pagina 3", "page": 3},
    ]


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
        assert metadata["page_map"] == [
            {"type": "overview", "key": "overview", "label": "Inizio", "page": 0},
            {"type": "news", "key": "news_1", "label": "Notizie · Pagina 1", "page": 1},
        ]
        assert channel.last_view is None

    asyncio.run(_run())


def test_send_and_store_persists_normalized_embeds() -> None:
    class _Db:
        async def upsert_campaign_content_message(self, **kwargs):
            self.kwargs = kwargs

        async def update_campaign_content_next_run(self, **kwargs):
            self.next_kwargs = kwargs

    class _Channel(discord.abc.Messageable):
        async def _get_channel(self):
            return self

        async def send(self, *args, **kwargs):
            self.sent_embed = kwargs.get("embed")
            return SimpleNamespace(id=456)

    channel = _Channel()

    class _Bot:
        def get_channel(self, _id):
            return channel

    async def _run() -> None:
        db = _Db()
        service = CampaignContentService(database=db, bot=_Bot(), ai_service=None)
        service._build_campaign_footer = lambda **kwargs: asyncio.sleep(0, result="footer test")
        config = {"guild_id": "1", "channel_id": "2", "id": 100, "interval_minutes": 60}
        oversized = discord.Embed(title="x")
        oversized.add_field(name="Campo", value="A" * 3500, inline=False)
        oversized.add_field(name="Campo 2", value="B" * 3500, inline=False)
        await service._send_and_store(
            config,
            [oversized],
            "HOROSCOPE",
            configured_sources=[],
            used_sources=[],
            used_model=None,
            fallback_used=False,
            payload={},
        )
        persisted = json.loads(db.kwargs["embeds_json"])
        assert len(persisted) > 1
        for item in persisted:
            assert len(discord.Embed.from_dict(item)) <= DISCORD_MAX_EMBED_TOTAL_CHARS

    asyncio.run(_run())


def test_enforce_embed_size_limit_splits_long_payload_into_valid_embeds() -> None:
    embed = discord.Embed(title="Notizie", color=discord.Color.blue(), description="Intro")
    for idx in range(1, 10):
        embed.add_field(name=f"Campo {idx}", value=("Contenuto molto lungo. " * 70).strip(), inline=False)
    bounded = enforce_embed_size_limit([embed])
    assert len(bounded) > 1
    for item in bounded:
        assert len(item) <= DISCORD_MAX_EMBED_TOTAL_CHARS
        assert item.title == "Notizie"
        assert item.color == discord.Color.blue()


def test_compute_embed_text_size_counts_relevant_fields() -> None:
    embed = discord.Embed(title="Titolo", description="Descrizione")
    embed.set_footer(text="Footer")
    embed.set_author(name="Author")
    embed.add_field(name="Campo", value="Valore", inline=False)
    expected = len("Titolo") + len("Descrizione") + len("Footer") + len("Author") + len("Campo") + len("Valore")
    assert compute_embed_text_size(embed) == expected


def test_compute_embeds_message_text_size_sums_embeds() -> None:
    embed_a = discord.Embed(title="A")
    embed_b = discord.Embed(description="BBBB")
    assert compute_embeds_message_text_size([embed_a, embed_b]) == 5


def test_split_embeds_for_discord_messages_splits_on_aggregate_message_limit() -> None:
    embed_a = discord.Embed(title="A")
    embed_b = discord.Embed(title="B")
    for idx in range(3):
        embed_a.add_field(name=f"A{idx}", value="x" * 1000, inline=False)
        embed_b.add_field(name=f"B{idx}", value="y" * 1000, inline=False)
    batches = split_embeds_for_discord_messages([embed_a, embed_b])
    assert len(batches) == 2
    assert all(len(batch) == 1 for batch in batches)
    assert all(compute_embeds_message_text_size(batch) <= DISCORD_MAX_EMBED_TOTAL_CHARS for batch in batches)


def test_send_and_store_enforces_embed_upper_bound_after_footer_pipeline() -> None:
    class _Db:
        async def upsert_campaign_content_message(self, **kwargs):
            self.kwargs = kwargs

        async def update_campaign_content_next_run(self, **kwargs):
            self.next_kwargs = kwargs

    class _Channel(discord.abc.Messageable):
        async def _get_channel(self):
            return self

        async def send(self, *args, **kwargs):
            return SimpleNamespace(id=987)

    class _Bot:
        def get_channel(self, _id):
            return _Channel()

    async def _run() -> None:
        db = _Db()
        service = CampaignContentService(database=db, bot=_Bot(), ai_service=None)
        service._build_campaign_footer = lambda **kwargs: asyncio.sleep(0, result="footer test")
        config = {"guild_id": "1", "channel_id": "2", "id": 101, "interval_minutes": 60}
        heavy = discord.Embed(title="x", description="Descrizione")
        for idx in range(1, 10):
            heavy.add_field(name=f"Campo {idx}", value=("A" * 900), inline=False)
        await service._send_and_store(
            config,
            [heavy],
            "NEWS",
            configured_sources=[],
            used_sources=[],
            used_model=None,
            fallback_used=False,
            payload={},
        )
        persisted = json.loads(db.kwargs["embeds_json"])
        assert len(persisted) > 1
        assert all(len(discord.Embed.from_dict(item)) <= DISCORD_MAX_EMBED_TOTAL_CHARS for item in persisted)

    asyncio.run(_run())


def test_send_and_store_splits_publish_into_multiple_messages_when_batch_is_too_large() -> None:
    class _Db:
        async def upsert_campaign_content_message(self, **kwargs):
            self.kwargs = kwargs

        async def update_campaign_content_next_run(self, **kwargs):
            self.next_kwargs = kwargs

    class _Channel(discord.abc.Messageable):
        def __init__(self) -> None:
            self.send = AsyncMock(side_effect=[SimpleNamespace(id=1001), SimpleNamespace(id=1002)])

        async def _get_channel(self):
            return self

    class _Bot:
        def __init__(self) -> None:
            self.channel = _Channel()

        def get_channel(self, _id):
            return self.channel

    async def _run() -> None:
        db = _Db()
        bot = _Bot()
        service = CampaignContentService(database=db, bot=bot, ai_service=None)
        service._build_campaign_footer = lambda **kwargs: asyncio.sleep(0, result="footer test")
        config = {"guild_id": "1", "channel_id": "2", "id": 102, "interval_minutes": 60}
        embed_a = discord.Embed(title="A")
        embed_b = discord.Embed(title="B")
        for idx in range(3):
            embed_a.add_field(name=f"A{idx}", value="x" * 1000, inline=False)
            embed_b.add_field(name=f"B{idx}", value="y" * 1000, inline=False)
        await service._send_and_store(
            config,
            [embed_a, embed_b],
            "HOROSCOPE",
            configured_sources=[],
            used_sources=[],
            used_model=None,
            fallback_used=False,
            payload={},
        )
        assert bot.channel.send.await_count == 2
        first_send_kwargs = bot.channel.send.await_args_list[0].kwargs
        second_send_kwargs = bot.channel.send.await_args_list[1].kwargs
        assert len(first_send_kwargs["embeds"]) == 1
        assert len(second_send_kwargs["embeds"]) == 1
        metadata = json.loads(db.kwargs["metadata_json"])
        assert metadata["message_ids"] == ["1001", "1002"]
        assert len(metadata["message_batches"]) == 2

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


def test_horoscope_rewrite_calls_translator_for_each_sign_and_assigns_result() -> None:
    async def _run() -> None:
        translator = SimpleNamespace(translate=AsyncMock(side_effect=[
            SimpleNamespace(text="Ariete tradotto"),
            SimpleNamespace(text="Toro tradotto"),
        ]))
        payload = {
            "signs": {
                "Ariete": {"horoscope": "Aries full text"},
                "Toro": {"horoscope": "Taurus full text"},
            }
        }
        service = CampaignContentService(
            database=SimpleNamespace(),
            bot=SimpleNamespace(),
            ai_service=None,
            translate_service=translator,
        )

        used_model = await service._rewrite_horoscope_payload(payload)

        assert used_model is None
        assert translator.translate.await_count == 2
        assert payload["signs"]["Ariete"]["horoscope"] == "Ariete tradotto"
        assert payload["signs"]["Toro"]["horoscope"] == "Toro tradotto"

    asyncio.run(_run())


def test_horoscope_rewrite_does_not_call_ai_or_set_used_model() -> None:
    async def _run() -> None:
        ai = SimpleNamespace(ask_for_task=AsyncMock())
        translator = SimpleNamespace(translate=AsyncMock(return_value=SimpleNamespace(text="Tradotto")))
        service = CampaignContentService(
            database=SimpleNamespace(),
            bot=SimpleNamespace(),
            ai_service=ai,
            translate_service=translator,
        )
        payload = {"signs": {sign: {"horoscope": "Raw text"} for sign in SIGN_ORDER[:3]}}

        used_model = await service._rewrite_horoscope_payload(payload)

        assert used_model is None
        assert ai.ask_for_task.await_count == 0
        assert all(payload["signs"][sign]["horoscope"] == "Tradotto" for sign in SIGN_ORDER[:3])

    asyncio.run(_run())


def test_horoscope_rewrite_keeps_original_when_translation_raises() -> None:
    async def _run() -> None:
        translator = SimpleNamespace(translate=AsyncMock(side_effect=RuntimeError("boom")))
        service = CampaignContentService(
            database=SimpleNamespace(),
            bot=SimpleNamespace(),
            ai_service=None,
            translate_service=translator,
        )
        payload = {"signs": {"Ariete": {"horoscope": "Original untouched text"}}}

        used_model = await service._rewrite_horoscope_payload(payload)

        assert used_model is None
        assert payload["signs"]["Ariete"]["horoscope"] == "Original untouched text"

    asyncio.run(_run())


def test_weather_service_still_uses_editorial_ai_when_enabled() -> None:
    class _Channel(discord.abc.Messageable):
        async def _get_channel(self):
            return self

        async def send(self, *args, **kwargs):
            return SimpleNamespace(id=777)

    class _Bot:
        def get_channel(self, _id):
            return _Channel()

    class _Ai:
        def __init__(self) -> None:
            self.ask_for_task = AsyncMock(return_value="meteo riscritto")

        def is_enabled(self):
            return True

    async def _run() -> None:
        db = SimpleNamespace(upsert_campaign_content_message=AsyncMock(), update_campaign_content_next_run=AsyncMock())
        ai = _Ai()
        service = CampaignContentService(database=db, bot=_Bot(), ai_service=ai)
        weather_payload = {
            "regions": {
                "Nord": {
                    "summary": "Tempo variabile",
                    "source_points": ["Milano: sole"],
                }
            },
            "used_sources": ["meteo.it"],
            "fallback_used": False,
        }
        with patch("app.services.campaign_content_service.fetch_weather_content", return_value=weather_payload):
            await service.execute_weather_service({"guild_id": "1", "channel_id": "2", "id": 9, "interval_minutes": 60, "sources_json": "[]"})
        ai.ask_for_task.assert_awaited()

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


def test_weather_service_resolves_next_recurring_run_and_passes_it_to_embed_builder() -> None:
    async def _run() -> None:
        class _Db:
            async def list_campaign_content_recurring_schedule_runs(self, **_kwargs):
                return [{"next_effective_run_at": "2026-04-09T19:00:00+00:00"}]

        service = CampaignContentService(database=_Db(), bot=object(), ai_service=None)  # type: ignore[arg-type]
        config = {"guild_id": "1", "channel_id": "2", "service_type": "WEATHER"}
        next_run = await service._resolve_next_scheduled_run(config, service_type="WEATHER")  # type: ignore[attr-defined]
        assert next_run is not None
        assert next_run.isoformat() == "2026-04-09T19:00:00+00:00"

    asyncio.run(_run())
