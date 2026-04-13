from pathlib import Path
from datetime import datetime
import re
import sys
import types

if "openai" not in sys.modules:
    sys.modules["openai"] = types.SimpleNamespace(AsyncOpenAI=object)
if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace()

from app.services.author import get_author_meta, render_author_name
from app.services.campaign_content_formatter import (
    build_fallback_embed,
    build_horoscope_embeds,
    build_news_embeds,
    build_news_page_map,
    news_edition_label_for_datetime,
    build_weather_embeds,
    sanitize_public_news_text,
)
from app.services.campaign_content_service import CampaignContentService
from app.services.embed_images import EmbedImagesService, get_embed_images_meta
from app.services.footer import get_footer_meta

_STANDARD_WRAP_RE = re.compile(r"^(?:(?P<emoji>\S+)\s+)?__\*\*(?P<inner>.*)\*\*__$")


def _title_inner_without_emoji(title: str) -> str:
    text = title.strip()
    while True:
        match = _STANDARD_WRAP_RE.match(text)
        if match is None:
            break
        text = match.group("inner").strip()
    if text and " " in text:
        first, rest = text.split(" ", 1)
        if not any(ch.isalnum() for ch in first):
            return rest.strip()
    return text


def test_weather_embeds_keep_clean_titles_and_shared_footer() -> None:
    embeds = build_weather_embeds(
        {"embed_title": "🌞 METEO CRICETOSO"},
        {
            "regions": {
                "Nord": [{"city": "Milano", "temperature": 22, "windspeed": 8}],
                "Centro": [{"city": "Roma", "temperature": 25, "windspeed": 5}],
                "Sud e Isole": [{"city": "Palermo", "temperature": 28, "windspeed": 11}],
            }
        },
    )

    assert _title_inner_without_emoji(embeds[0].title or "") == "METEO CRICETOSO • OVERVIEW ITALIA"
    assert _title_inner_without_emoji(embeds[1].title or "") == "METEO CRICETOSO • NORD"
    assert _title_inner_without_emoji(embeds[2].title or "") == "METEO CRICETOSO • CENTRO"
    assert _title_inner_without_emoji(embeds[3].title or "") == "METEO CRICETOSO • SUD E ISOLE"
    footer_meta = [get_footer_meta(embed) for embed in embeds]
    assert all(meta is not None for meta in footer_meta)
    assert {meta.service_name for meta in footer_meta if meta is not None} == {"campagne_meteo"}


def test_news_and_horoscope_embeds_have_shared_footer_without_page_in_title() -> None:
    news = build_news_embeds(
        {"embed_title": "📰 NOTIZIARIO CRICETOSO"},
            {
                "categories": {
                    "trash": [{"title": "T1", "summary": "S1", "source": "open-meteo", "link": "https://example.com"}],
                    "viral": [{"title": "T2", "summary": "S2", "source": "meteoam", "link": "https://example.com/2"}],
                },
                "sources": ["open-meteo", "meteoam"],
            },
        )
    horoscope = build_horoscope_embeds(
        {"embed_title": "🔮 OROSCOPO DEL GIORNO"},
        {"signs": {"Ariete": {"text": "Focus"}}},
    )
    assert "HAMSTER NEWS • EDIZIONE" in _title_inner_without_emoji(news[0].title or "")
    assert len(news) == 1
    assert _title_inner_without_emoji(horoscope[0].title or "") == "OROSCOPO DEL GIORNO • INIZIO"
    assert _title_inner_without_emoji(horoscope[1].title or "") == "OROSCOPO DEL GIORNO • ARIETE"
    news_meta = [get_footer_meta(embed) for embed in news]
    horoscope_meta = [get_footer_meta(embed) for embed in horoscope]
    assert all(meta is not None for meta in news_meta)
    assert all(meta is not None for meta in horoscope_meta)
    assert {meta.service_name for meta in news_meta if meta is not None} == {"campagne_notizie"}
    assert {meta.service_name for meta in horoscope_meta if meta is not None} == {"campagne_oroscopo"}


def test_news_overview_has_editorial_tone_without_technical_lines() -> None:
    news = build_news_embeds(
        {"embed_title": "📰 NOTIZIARIO CRICETOSO"},
        {
            "categories": {
                "spettacolo": [{"title": "Gran finale in diretta", "summary": "S1", "source": "s1", "link": "https://example.com/1"}],
                "gossip": [{"title": "Ritorno clamoroso", "summary": "S2", "source": "s2", "link": "https://example.com/2"}],
                "viral": [{"title": "Nuovo trend impazza", "summary": "S3", "source": "s3", "link": "https://example.com/3"}],
            }
        },
    )

    overview = news[0]
    description = overview.description or ""
    assert "Categorie attive" not in description
    assert "Notizie uniche aggregate" not in description
    assert "Barcellometro" in description
    assert "redazione" in description.lower()
    assert "Che ci racconta il mondo oggi?" in description
    assert "**Barcellometro in regia**" in description
    assert "📰" in description
    assert "📰" in description
    assert any(greeting in description for greeting in ["**Buongiorno**", "**Buon pomeriggio**", "**Buona sera**", "**Buonanotte**"])
    assert all(field.name != format_name for field in overview.fields for format_name in ["__**VARIE**__", "__**TITOLI IN EVIDENZA**__"])


def test_news_overview_intro_drops_old_generic_opening_copy() -> None:
    news = build_news_embeds(
        {},
        {"generated_at": "2026-01-01T09:00:00+00:00", "categories": {"cronaca": [{"title": "t", "summary": "s", "source": "ansa", "link": "https://ansa.it"}]}},
    )
    description = news[0].description or ""
    assert "Da quale categoria vuoi partire per il recap?" not in description
    assert "Turno di" not in description
    assert "Edizione di" not in description


def test_news_overview_field_copy_is_concise_and_has_source_line() -> None:
    news = build_news_embeds(
        {},
        {
            "categories": {
                "cronaca": [
                    {
                        "title": "Titolo fedele fonte",
                        "summary": "Prima frase del riassunto. Seconda frase del riassunto molto breve. Terza frase che non dovrebbe apparire.",
                        "source": "ansa.it",
                        "link": "https://www.ansa.it/sito/notizie/test.html",
                    }
                ]
            }
        },
    )
    field_value = news[0].fields[0].value
    assert field_value is not None
    assert field_value.count("\n") == 2
    assert field_value.split("\n")[0].startswith("• **")
    assert not field_value.split("\n")[1].startswith("•")
    assert "**In breve:**" not in field_value
    assert "🧃 In breve:" not in field_value
    assert "`fonte: www.ansa.it`" in field_value


def test_news_public_sanitization_strips_meta_prefixes_and_keeps_content() -> None:
    dirty = "🧃 In breve: Ecco la riscrizione\nRiassunto: **Focus** utile."
    cleaned = sanitize_public_news_text(dirty)
    assert "In breve" not in cleaned
    assert "Ecco la riscrizione" not in cleaned
    assert cleaned == "**Focus** utile."


def test_news_category_item_format_matches_single_item_field_format() -> None:
    payload = {
        "categories": {
            "cronaca": [
                {"title": f"Titolo {idx}", "summary": f"Sommario {idx}.", "source": "ansa.it", "link": f"https://example.com/{idx}"}
                for idx in range(1, 8)
            ]
        }
    }
    news = build_news_embeds({}, payload)
    overview = news[0]
    assert len(overview.fields) >= 3
    first_field_value = overview.fields[2].value or ""
    assert any(f"**[Titolo {idx}](https://example.com/{idx})**" in first_field_value for idx in range(2, 8))
    assert "**[Titolo 1](https://example.com/1)**" not in first_field_value
    assert overview.fields[0].name == "⚡ __**ULTIM'ORA**__"
    assert overview.fields[1].name == "🌟 __**IN EVIDENZA**__"
    assert overview.fields[2].name == "🕵️ __**CRONACA IN PRIMO PIANO**__"

    for idx, field in enumerate(overview.fields):
        value = field.value or ""
        assert len(value) <= 1024
        assert value.split("\n")[0].startswith("• **")
        assert not value.split("\n")[1].startswith("•")
        assert value.count("`fonte: www.ansa.it`") >= 1
        item_count = value.count("`fonte:")
        assert item_count <= 1, f"Field {idx} exceeds max 1 item: {item_count}"


def test_news_edition_label_coverage() -> None:
    assert news_edition_label_for_datetime(datetime.fromisoformat("2026-04-09T05:00:00+02:00"))[0] == "EDIZIONE MATTUTINA"
    assert news_edition_label_for_datetime(datetime.fromisoformat("2026-04-09T12:00:00+02:00"))[0] == "EDIZIONE POMERIDIANA"
    assert news_edition_label_for_datetime(datetime.fromisoformat("2026-04-09T18:00:00+02:00"))[0] == "EDIZIONE SERALE"
    assert news_edition_label_for_datetime(datetime.fromisoformat("2026-04-09T23:00:00+02:00"))[0] == "EDIZIONE NOTTURNA"


def test_news_embed_supports_extras_and_next_edition_for_recurring() -> None:
    news = build_news_embeds(
        {"next_scheduled_run_at": "2026-04-09T09:30:00+00:00", "extras_json": '["barzelletta","aforisma","canzone","meme"]'},
        {
            "generated_at": "2026-04-09T08:00:00+00:00",
            "categories": {"cronaca": [{"title": "Titolo 1", "summary": "S1", "source": "ansa.it", "link": "https://example.com/1"}]},
        },
    )
    field_names = [field.name for field in news[0].fields]
    assert "😂 __**BARZELLETTA DEL GIORNO**__" in field_names
    assert "🧠 __**AFORISMA DEL GIORNO**__" in field_names
    assert "🎵 __**CANZONE DEL GIORNO**__" in field_names
    assert "🖼️ __**MEME DEL GIORNO**__" in field_names
    assert "🔜 __**PROSSIMA EDIZIONE**__" in field_names


def test_news_fallback_uses_real_source_sentences_before_minimal_placeholder() -> None:
    payload = {
        "categories": {
            "cronaca": [
                {
                    "title": "Fallback reale",
                    "summary": "Aggiornamento in arrivo.",
                    "description": "Prima frase utile dal feed. Seconda frase utile dal feed. Terza non necessaria.",
                    "source": "ansa.it",
                    "link": "https://example.com/fallback",
                }
            ]
        }
    }
    news = build_news_embeds({}, payload)
    field_value = news[0].fields[0].value or ""
    assert "Aggiornamento in arrivo." not in field_value
    assert "Prima frase utile dal feed." in field_value


def test_news_minimal_fallback_used_only_when_all_text_is_empty() -> None:
    payload = {
        "categories": {
            "cronaca": [
                {"title": "Solo titolo", "summary": "", "description": "", "content": "", "source": "ansa.it", "link": "https://example.com/empty"}
            ]
        }
    }
    news = build_news_embeds({}, payload)
    field_value = news[0].fields[0].value or ""
    assert "Dettagli in aggiornamento." in field_value
    assert any(emoji in field_value for emoji in ("👀", "🐹", "🤹", "🫥", "😔"))


def test_news_fallback_embed_uses_campaigns_author_service_label() -> None:
    fallback = build_fallback_embed({}, ["https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml"], service_name="campagne_notizie")
    author_meta = get_author_meta(fallback[0])
    assert author_meta is not None
    assert author_meta.service_name == "campagne_notizie"
    assert render_author_name(service_name=author_meta.service_name) == "servizio CAMPAIGNS"


def test_weather_and_horoscope_overview_have_editorial_intro() -> None:
    weather = build_weather_embeds(
        {"embed_title": "🌞 METEO CRICETOSO"},
        {
            "generated_at": "2026-01-01T20:30:00+00:00",
            "regions": {
                "Nord": {"sampled_cities": [{"city": "Milano", "temperature": 21, "windspeed": 10, "condition": "pioggia"}]},
                "Centro": {"sampled_cities": [{"city": "Roma", "temperature": 24, "windspeed": 8, "condition": "sereno"}]},
                "Sud e Isole": {"sampled_cities": [{"city": "Palermo", "temperature": 29, "windspeed": 6, "condition": "sereno"}]},
            },
        },
    )
    horoscope = build_horoscope_embeds(
        {"embed_title": "🔮 OROSCOPO DEL GIORNO"},
        {
            "generated_at": "2026-01-01T20:30:00+00:00",
            "signs": {sign: {"love": "ok", "work": "ok", "money": "ok", "energy": "alta", "friction": "ok", "advice": "ok", "confidence": 1.0, "tone": "frizzante"} for sign in ["Ariete", "Toro", "Gemelli", "Cancro", "Leone", "Vergine", "Bilancia", "Scorpione", "Sagittario", "Capricorno", "Acquario", "Pesci"]},
        },
    )

    assert "Barcellometro" in (weather[0].description or "")
    assert "Clicca i pulsanti" in (weather[0].description or "")
    assert "Barcellometro" in (horoscope[0].description or "")
    assert "pulsanti" in (horoscope[0].description or "").lower()


def test_campaign_service_footer_pipeline_tracks_sources_model_and_metadata_fields() -> None:
    source = Path("app/services/campaign_content_service.py").read_text()
    assert "def _normalize_sources" in source
    assert "def _build_campaign_footer" in source
    assert '"campagne_notizie"' in source
    assert '"campagne_meteo"' in source
    assert '"campagne_oroscopo"' in source
    assert '"footer_text": footer_text' in source
    assert '"used_sources": used_sources' in source
    assert '"used_model": used_model' in source
    assert "attach_footer_meta_to_all" in source


def test_campaign_content_service_maps_editorial_footer_service_names() -> None:
    source = Path("app/services/campaign_content_service.py").read_text()
    assert 'def _campaign_footer_service_name' in source
    assert '"NEWS": "campagne_notizie"' in source
    assert '"WEATHER": "campagne_meteo"' in source
    assert '"HOROSCOPE": "campagne_oroscopo"' in source


def test_campaign_service_resolve_model_uses_task_parameter_for_editorial() -> None:
    source = Path("app/services/campaign_content_service.py").read_text()
    assert 'def _resolve_ai_model_name(self, task: str)' in source
    assert 'self._ai.get_model_config(task)' in source
    assert 'self._ai.get_model_config("summary")' not in source


def test_campaign_formatter_applies_footer_meta_in_all_builders() -> None:
    source = Path("app/services/campaign_content_formatter.py").read_text()
    assert 'def _apply_campaign_footer' in source
    assert 'return _apply_campaign_footer([overview], service_name="campagne_notizie")' in source
    assert 'return _apply_campaign_footer(embeds, service_name="campagne_meteo")' in source
    assert 'return _apply_campaign_footer(embeds, service_name="campagne_oroscopo")' in source
    assert 'return _apply_campaign_footer([embed], service_name=service_name)' in source


def test_news_service_label_maps_to_campaigns_and_not_unknown() -> None:
    assert render_author_name(service_name="campagne_notizie") == "servizio CAMPAIGNS"
    assert "UNKNOWN" not in render_author_name(service_name="campagne_notizie")


def test_news_overview_builds_category_fields_buttons_and_no_legacy_sections() -> None:
    payload = {
        "configured_categories": ["varie"],
        "categories": {
            "cronaca": [
                {"title": "C1", "summary": "S", "source": "ansa", "link": "https://example.com/1", "published_at": "2026-04-09T10:00:00+00:00"},
                {"title": "C2", "summary": "S", "source": "ansa", "link": "https://example.com/2", "published_at": "2026-04-09T09:00:00+00:00"},
            ],
            "varie": [{"title": "V1", "summary": "S", "source": "misc", "link": "https://example.com/3"}],
        }
    }
    news = build_news_embeds({"embed_title": "IGNORED"}, payload)
    overview = news[0]
    page_map = build_news_page_map(payload)
    overview_field_labels = [field.name for field in overview.fields]

    assert any("VARIE IN PRIMO PIANO" in name for name in overview_field_labels)
    assert all("TITOLI IN EVIDENZA" not in name for name in overview_field_labels)

    assert page_map == [{"type": "overview", "key": "overview", "label": "Inizio", "page": 0}]


def test_news_overview_selection_uses_configured_order_caps_at_five_categories_and_ten_news() -> None:
    payload = {
        "configured_categories": [f"cat{i}" for i in range(1, 13)],
        "categories": {
            **{
                f"cat{i}": [
                    {
                        "title": f"Titolo {i}",
                        "summary": f"Sintesi {i}",
                        "source": "ansa",
                        "link": f"https://example.com/{i}",
                    }
                ]
                for i in range(1, 13)
            },
            "varie": [{"title": "legacy", "summary": "x", "source": "misc", "link": "https://example.com/legacy"}],
        },
    }
    news = build_news_embeds({}, payload)
    overview = news[0]
    page_map = build_news_page_map(payload)

    assert len(overview.fields) == 5
    names = [field.name for field in overview.fields]
    assert names[0] == "⚡ __**ULTIM'ORA**__"
    assert names[1] == "🌟 __**IN EVIDENZA**__"
    assert len(names[2:]) == 3
    assert all(name.startswith("📌 __**CAT") and name.endswith("IN PRIMO PIANO**__") for name in names[2:])
    assert len([name for name in names if "IN PRIMO PIANO" in name]) == 3
    assert all("VARIE" not in name.upper() for name in names)
    assert page_map == [{"type": "overview", "key": "overview", "label": "Inizio", "page": 0}]


def test_news_overview_avoids_duplicate_main_story_across_categories_and_handles_empty_categories() -> None:
    payload = {
        "configured_categories": ["cronaca", "sport", "tech", "mondo"],
        "categories": {
            "cronaca": [
                {"title": "Titolo condiviso", "summary": "s1", "source": "ansa", "link": "https://example.com/shared"},
                {"title": "Cronaca esclusiva", "summary": "s2", "source": "ansa", "link": "https://example.com/cronaca"},
            ],
            "sport": [
                {"title": "Titolo condiviso", "summary": "s3", "source": "gazzetta", "link": "https://example.com/shared"},
                {"title": "Sport esclusivo", "summary": "s4", "source": "gazzetta", "link": "https://example.com/sport"},
            ],
            "tech": [],
            "mondo": [{"title": "", "summary": "vuoto", "source": "reuters", "link": "https://example.com/mondo"}],
        },
    }
    news = build_news_embeds({}, payload)
    overview = news[0]
    values = [field.value for field in overview.fields]
    names = [field.name for field in overview.fields]

    assert names[0] == "⚡ __**ULTIM'ORA**__"
    assert names[1] == "🌟 __**IN EVIDENZA**__"
    assert any("IN PRIMO PIANO" in name for name in names)
    assert any("Titolo condiviso" in value for value in values)
    assert any("Sport esclusivo" in value for value in values)
    assert sum("Titolo condiviso" in value for value in values) == 1

def test_news_overview_uses_first_available_story_image_and_survives_without_image() -> None:
    with_image = build_news_embeds(
        {},
        {
            "categories": {
                "cronaca": [{"title": "A", "summary": "S", "source": "ansa", "link": "https://example.com", "image_url": "https://cdn.example.com/img.jpg"}],
                "sport": [{"title": "B", "summary": "S", "source": "gazzetta", "link": "https://example.com"}],
            }
        },
    )
    without_image = build_news_embeds(
        {},
        {"categories": {"cronaca": [{"title": "A", "summary": "S", "source": "ansa", "link": "https://example.com"}]}},
    )

    with_image_meta = get_embed_images_meta(with_image[0])
    without_image_meta = get_embed_images_meta(without_image[0])
    assert with_image_meta is not None
    assert with_image_meta.service_name == "campagne_notizie"
    assert with_image_meta.image_url == "https://cdn.example.com/img.jpg"
    assert without_image_meta is not None
    assert without_image_meta.service_name == "campagne_notizie"
    assert without_image_meta.image_url is None
    assert with_image[0].image.url is None
    assert without_image[0].image.url is None

    class _Db:
        async def get_setting(self, _key):
            return None

        async def set_setting(self, _key, _value):
            return None

        async def fetchall(self, _query, _params):
            return []

    async def _run() -> None:
        service = EmbedImagesService(_Db())
        await service.apply(with_image[0], default_service_name="campagne_notizie")
        await service.apply(without_image[0], default_service_name="campagne_notizie")

    import asyncio

    asyncio.run(_run())
    assert str(with_image[0].image.url) == "https://cdn.example.com/img.jpg"
    assert without_image[0].image.url is None


def test_campaign_sources_are_shortened_in_footer_source_normalization() -> None:
    compact = CampaignContentService._normalize_sources(  # type: ignore[attr-defined]
        [
            "https://www.reuters.com/world/europe/very/long/path?query=1",
            "https://ANSA.it/politica/articolo-lungo",
            "open-meteo",
        ]
    )
    assert compact == ["reuters.com", "ansa.it", "open-meteo"]


def test_news_formatter_uses_global_standard_flow_for_title_description_and_field_names() -> None:
    source = Path("app/services/campaign_content_formatter.py").read_text()
    assert "format_standard_title" in source
    assert "format_standard_description" in source
    assert "format_standard_field_name" in source
    assert "def format_news_" not in source
    assert "def build_news_title" not in source
