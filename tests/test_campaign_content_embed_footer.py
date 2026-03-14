from pathlib import Path

from app.services.campaign_content_formatter import (
    apply_shared_footer_and_pagination,
    build_horoscope_embeds,
    build_news_embeds,
    build_weather_embeds,
)


def test_weather_embeds_have_page_in_title_and_shared_footer() -> None:
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

    assert embeds[0].title == "🌞 METEO CRICETOSO • Overview Italia • Pagina 1/4"
    assert embeds[1].title == "🌞 METEO CRICETOSO • Nord • Pagina 2/4"
    assert embeds[2].title == "🌞 METEO CRICETOSO • Centro • Pagina 3/4"
    assert embeds[3].title == "🌞 METEO CRICETOSO • Sud e Isole • Pagina 4/4"
    footers = [embed.footer.text for embed in embeds]
    assert len(set(footers)) == 1
    assert all("Pagina" not in (f or "") for f in footers)


def test_news_and_horoscope_embeds_have_shared_footer_and_page_in_title() -> None:
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

    assert news[0].title.endswith("• Pagina 1/3")
    assert news[1].title.endswith("• Pagina 2/3")
    assert news[2].title.endswith("• Pagina 3/3")
    assert horoscope[0].title == "🔮 OROSCOPO DEL GIORNO • Overview • Pagina 1/13"
    assert horoscope[1].title == "🔮 OROSCOPO DEL GIORNO • Ariete • Pagina 2/13"
    assert all(embed.footer.text == footer_text for embed in news)
    assert all(embed.footer.text == footer_text for embed in horoscope)
    assert all("Pagina" not in (embed.footer.text or "") for embed in news + horoscope)


def test_campaign_service_footer_pipeline_tracks_sources_model_and_metadata_fields() -> None:
    source = Path("app/services/campaign_content_service.py").read_text()
    assert "def _normalize_sources" in source
    assert 'service_name="campagne"' in source
    assert '"footer_text": footer_text' in source
    assert '"used_sources": used_sources' in source
    assert '"used_model": used_model' in source
    assert "attach_footer_meta_to_all" in source
    assert "apply_shared_footer_and_pagination" in source
