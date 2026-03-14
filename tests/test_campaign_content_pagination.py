from pathlib import Path


def test_news_weather_have_start_prev_next_navigation() -> None:
    source = Path("app/services/campaign_content_views.py").read_text()
    assert 'label="⏮️ INIZIO"' in source
    assert 'label="⬅️ INDIETRO"' in source
    assert 'label="➡️ AVANTI"' in source


def test_horoscope_has_all_sign_buttons() -> None:
    source = Path("app/services/campaign_content_formatter.py").read_text()
    for sign in [
        "Ariete",
        "Toro",
        "Gemelli",
        "Cancro",
        "Leone",
        "Vergine",
        "Bilancia",
        "Scorpione",
        "Sagittario",
        "Capricorno",
        "Acquario",
        "Pesci",
    ]:
        assert f'"{sign}"' in source
