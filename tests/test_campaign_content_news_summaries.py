import re

from app.services.campaign_content_formatter import (
    _build_news_summary_body,
    _normalize_news_summary_for_embed,
    format_source_label,
    highlight_key_terms,
)


_FINAL_EMOJI_RE = re.compile(r"\s+[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]\s*$")


def _strip_single_final_emoji(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.strip())
    return _FINAL_EMOJI_RE.sub("", normalized).strip()


def _sentence_count(text: str) -> int:
    normalized = _strip_single_final_emoji(text)
    return len([s for s in re.split(r"(?<=[.!?])\s+", normalized) if s.strip()])


def test_news_summary_is_single_sentence_with_one_final_emoji() -> None:
    item = {
        "title": "Mercati in tensione dopo il nuovo piano fiscale",
        "summary": "Il governo presenta il piano fiscale. Le opposizioni criticano tempi e coperture.",
        "source": "ansa.it",
        "link": "https://example.com/mercati",
    }
    summary = _normalize_news_summary_for_embed(item["summary"], item=item, display="IN EVIDENZA")
    assert _sentence_count(summary) == 1
    assert summary.endswith(("👀", "🤹", "📈", "⚡", "🎭", "😔", "🫥"))
    assert not summary.lstrip().startswith(("👀", "🤹", "📈", "⚡", "🎭", "😔", "🫥"))
    assert "Insomma" not in summary
    assert "Qui la ruota gira" not in summary


def test_news_summary_serious_uses_sober_final_emoji() -> None:
    item = {
        "title": "Incidente grave in autostrada, due vittime",
        "summary": "Scontro tra più mezzi con traffico bloccato per ore.",
        "source": "ansa.it",
        "link": "https://example.com/incidente",
    }
    summary = _normalize_news_summary_for_embed(item["summary"], item=item, display="ULTIM'ORA")
    assert _sentence_count(summary) == 1
    assert summary.endswith(("🫥", "😔"))


def test_news_body_builder_keeps_only_first_complete_sentence() -> None:
    item = {"title": "Tech", "summary": "ok", "source": "wired.it", "link": "https://example.com/tech"}
    body = _build_news_summary_body(
        "Prima frase utile. Seconda frase utile. Terza frase da togliere.", item=item, display="Tecnologia", tone="standard"
    )
    assert body == "Prima frase utile."


def test_highlight_key_terms_does_not_split_key_phrases() -> None:
    text = "Gli Stati Uniti rilanciano il dialogo con l'Iran."
    highlighted = highlight_key_terms(text)
    assert "**Gli Stati** Uniti" not in highlighted


def test_campaign_source_labels_include_rss_and_api_markers() -> None:
    assert format_source_label("ansa.it", "rss") == "Ansa RSS"
    assert format_source_label("repubblica.it", "rss") == "Repubblica RSS"
    assert format_source_label("xml2.corriereobjects.it", "rss") == "Corriere RSS"
    assert format_source_label("open-meteo", "api") == "Open-Meteo API"
    assert format_source_label("ohmanda", "api") == "Ohmanda API"
