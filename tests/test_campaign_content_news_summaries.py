import re

from app.services.campaign_content_formatter import (
    _build_news_item_summary,
    _build_news_summary_body,
    _classify_news_tone,
    _compose_news_embed_summary,
    _normalize_news_summary_for_embed,
    highlight_key_terms,
)


def _sentence_count(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()])


def test_news_summary_structure_has_two_body_sentences_and_tail_comment() -> None:
    item = {
        "title": "Mercati in tensione dopo il nuovo piano fiscale",
        "summary": "Il governo presenta il piano fiscale. Le opposizioni criticano tempi e coperture.",
        "source": "ansa.it",
        "link": "https://example.com/mercati",
    }
    summary = _normalize_news_summary_for_embed(item["summary"], item=item, display="IN EVIDENZA")
    assert _sentence_count(summary) == 3
    assert not summary.lstrip().startswith(("👀", "🐹", "🤹", "🫥", "😔"))
    assert summary.endswith(("👀", "🐹", "🤹", "🫥", "😔"))


def test_news_summary_tone_serious_uses_sober_tail() -> None:
    item = {
        "title": "Incidente grave in autostrada, due vittime",
        "summary": "Scontro tra più mezzi con traffico bloccato per ore.",
        "source": "ansa.it",
        "link": "https://example.com/incidente",
    }
    tone = _classify_news_tone(item, display="ULTIM'ORA")
    assert tone == "serious"
    summary = _normalize_news_summary_for_embed(item["summary"], item=item, display="ULTIM'ORA")
    assert "🐹" not in summary and "🤹" not in summary
    assert summary.endswith(("🫥", "😔"))


def test_news_body_builder_preserves_full_body_and_no_emoji() -> None:
    item = {"title": "Tech", "summary": "ok", "source": "wired.it", "link": "https://example.com/tech"}
    body = _build_news_summary_body(
        "Prima frase utile. Seconda frase utile. Terza frase da togliere.", item=item, display="Tecnologia", tone="standard"
    )
    assert "Terza frase" in body
    assert all(emoji not in body for emoji in ("👀", "🐹", "🤹", "🫥", "😔"))


def test_news_compose_adds_tail_when_missing_from_ai_body() -> None:
    composed = _compose_news_embed_summary("Prima frase. Seconda frase.", "Qui la ruota gira veloce 👀")
    assert composed == "Prima frase. Seconda frase. Qui la ruota gira veloce 👀"


def test_highlight_key_terms_adds_bold_without_over_formatting() -> None:
    text = (
        "Thrash-Furia dall'oceano su Netflix è un mix catastrofico con squali assassini, "
        "diretta da Tommy Wirkola e rilanciata su YouTube."
    )
    highlighted = highlight_key_terms(text)
    assert "**Netflix**" in highlighted
    assert "**mix catastrofico**" in highlighted
    assert "**squali assassini**" in highlighted
    assert "**Tommy Wirkola**" in highlighted
    assert highlighted.count("**") <= 8


def test_news_fallback_pipeline_stays_structured_when_ai_body_missing() -> None:
    item = {
        "title": "Aggiornamento locale",
        "summary": "",
        "description": "",
        "content": "",
        "source": "ansa.it",
        "link": "https://example.com/local",
    }
    summary = _normalize_news_summary_for_embed("Dettagli in aggiornamento.", item=item, display="CRONACA")
    assert _sentence_count(summary) >= 2
    assert summary.endswith(("👀", "🐹", "🤹", "🫥", "😔"))


def test_news_tail_comments_are_unique_within_same_embed_serious_items() -> None:
    used: set[str] = set()
    items = [
        {"title": "Incidente grave in tangenziale con vittime", "summary": "Dinamica al vaglio.", "source": "ansa.it", "link": f"https://e/{idx}"}
        for idx in range(5)
    ]
    tails = []
    for idx, item in enumerate(items):
        summary = _build_news_item_summary(item, display="CRONACA", used_tail_comments=used, seed_key=f"s-{idx}")
        tails.append(summary.split(". ")[-1].strip())
    assert len(set(tails)) == len(tails)
    assert all(tail.endswith(("🫥", "😔")) for tail in tails)


def test_news_tail_comments_follow_tone_bucket_with_mixed_items() -> None:
    used: set[str] = set()
    serious = {"title": "Omicidio in centro, aperta indagine", "summary": "Gli investigatori stanno ricostruendo i fatti.", "source": "ansa.it", "link": "https://e/serious"}
    standard = {"title": "Nuovo smartphone pieghevole in arrivo", "summary": "Presentazione prevista a giugno.", "source": "wired.it", "link": "https://e/standard"}
    serious_summary = _build_news_item_summary(serious, display="CRONACA", used_tail_comments=used, seed_key="serious")
    standard_summary = _build_news_item_summary(standard, display="TECNOLOGIA", used_tail_comments=used, seed_key="standard")
    assert serious_summary.endswith(("🫥", "😔"))
    assert standard_summary.endswith(("👀", "🐹", "🤹"))
    assert serious_summary.split(". ")[-1] != standard_summary.split(". ")[-1]
