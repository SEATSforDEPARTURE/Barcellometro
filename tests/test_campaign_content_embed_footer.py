from pathlib import Path
import re
import sys
import types

if "openai" not in sys.modules:
    sys.modules["openai"] = types.SimpleNamespace(AsyncOpenAI=object)
if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace()

from app.services.author import render_author_name
from app.services.campaign_content_formatter import build_horoscope_embeds, build_news_embeds, build_news_page_map, build_weather_embeds
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
    assert _title_inner_without_emoji(news[0].title or "") == "HAMSTER NEWS • PANORAMICA"
    assert _title_inner_without_emoji(news[1].title or "") == "HAMSTER NEWS • TRASH"
    assert _title_inner_without_emoji(news[2].title or "") == "HAMSTER NEWS • VIRAL"
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
    assert "Da quale categoria vuoi partire" in description
    assert "**" in description
    assert all(field.name != format_name for field in overview.fields for format_name in ["__**VARIE**__", "__**TITOLI IN EVIDENZA**__"])


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
    assert 'return _apply_campaign_footer(embeds, service_name="campagne_notizie")' in source
    assert 'return _apply_campaign_footer(embeds, service_name="campagne_meteo")' in source
    assert 'return _apply_campaign_footer(embeds, service_name="campagne_oroscopo")' in source
    assert 'return _apply_campaign_footer([embed], service_name=service_name)' in source


def test_news_service_label_maps_to_campaigns_and_not_unknown() -> None:
    assert render_author_name(service_name="campagne_notizie") == "servizio CAMPAIGNS"
    assert "UNKNOWN" not in render_author_name(service_name="campagne_notizie")


def test_news_overview_builds_category_fields_buttons_and_no_legacy_sections() -> None:
    payload = {
        "categories": {
            "cronaca": [{"title": "C1", "summary": "S", "source": "ansa", "link": "https://example.com/1"}],
            "sport": [{"title": "S1", "summary": "S", "source": "gazzetta", "link": "https://example.com/2"}],
            "varie": [{"title": "V1", "summary": "S", "source": "misc", "link": "https://example.com/3"}],
        }
    }
    news = build_news_embeds({"embed_title": "IGNORED"}, payload)
    overview = news[0]
    page_map = build_news_page_map(payload)
    overview_field_labels = [field.name for field in overview.fields]

    assert all("VARIE" not in name for name in overview_field_labels)
    assert all("TITOLI IN EVIDENZA" not in name for name in overview_field_labels)

    displayed_labels = [entry["label"] for entry in page_map if entry.get("type") == "category"]
    displayed_emoji = [label.split(" ", 1)[0] for label in displayed_labels]
    field_emoji = [name.split(" ", 1)[0] for name in overview_field_labels]
    assert len(displayed_labels) == len(overview_field_labels)
    assert displayed_emoji == field_emoji


def test_news_overview_selection_uses_configured_order_caps_at_ten_and_buttons_match() -> None:
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

    assert len(overview.fields) == 10
    names = [field.name for field in overview.fields]
    assert "CAT1" in names[0].upper()
    assert "CAT11" not in " ".join(name.upper() for name in names)
    assert all("VARIE" not in name.upper() for name in names)

    button_labels = [entry["label"] for entry in page_map if entry.get("type") == "category"]
    assert len(button_labels) == len(overview.fields) == len(news) - 1
    for label, field in zip(button_labels, overview.fields, strict=True):
        assert label.split(" ", 1)[1] in field.name


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

    assert len(overview.fields) == 2
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
