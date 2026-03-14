from pathlib import Path

from app.services.campaign_content_formatter import (
    apply_shared_footer_and_pagination,
    build_horoscope_embeds,
    build_news_embeds,
    build_weather_embeds,
)


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
    apply_shared_footer_and_pagination(embeds, "Barcellometro dev6 · Dati elaborati con open-meteo, meteoam, 3bmeteo e gpt-4o")

    assert embeds[0].title == "🌞 METEO CRICETOSO • Overview Italia"
    assert embeds[1].title == "🌞 METEO CRICETOSO • Nord"
    assert embeds[2].title == "🌞 METEO CRICETOSO • Centro"
    assert embeds[3].title == "🌞 METEO CRICETOSO • Sud e Isole"
    footers = [embed.footer.text for embed in embeds]
    assert len(set(footers)) == 1
    assert all("Pagina" not in (f or "") for f in footers)


def test_news_and_horoscope_embeds_have_shared_footer_without_page_in_title() -> None:
    news = build_news_embeds(
        {"embed_title": "📰 NOTIZIARIO CRICETOSO"},
        {
            "categories": {
                "trash": [{"title": "T1", "summary": "S1", "source": "open-meteo", "link": "https://example.com"}],
                "viral": [{"title": "T2", "summary": "S2", "source": "meteoam", "link": "https://example.com"}],
            },
            "sources": ["open-meteo", "meteoam"],
        },
    )
    horoscope = build_horoscope_embeds(
        {"embed_title": "🔮 OROSCOPO DEL GIORNO"},
        {"signs": {"Ariete": {"text": "Focus"}}},
    )
    footer_text = "Barcellometro dev6 · Dati elaborati con open-meteo e gpt-4o"
    apply_shared_footer_and_pagination(news, footer_text)
    apply_shared_footer_and_pagination(horoscope, footer_text)

    assert news[0].title == "📰 NOTIZIARIO CRICETOSO • Inizio"
    assert news[1].title == "📰 NOTIZIARIO CRICETOSO • Trash"
    assert news[2].title == "📰 NOTIZIARIO CRICETOSO • Viral"
    assert horoscope[0].title == "🔮 OROSCOPO DEL GIORNO • Inizio"
    assert horoscope[1].title == "🔮 OROSCOPO DEL GIORNO • Ariete"
    assert all(embed.footer.text == footer_text for embed in news)
    assert all(embed.footer.text == footer_text for embed in horoscope)
    assert all("Pagina" not in (embed.footer.text or "") for embed in news + horoscope)


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
    assert "Spettacolo" in description
    assert "Gossip" in description


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
    assert 'service_name="campagne"' in source
    assert '"footer_text": footer_text' in source
    assert '"used_sources": used_sources' in source
    assert '"used_model": used_model' in source
    assert "attach_footer_meta_to_all" in source
    assert "apply_shared_footer_and_pagination" in source
