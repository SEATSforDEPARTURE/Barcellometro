import asyncio
import sys
import types

from tests._sqlite_stub import ensure_sqlite_stub

ensure_sqlite_stub()

if "openai" not in sys.modules:
    sys.modules["openai"] = types.SimpleNamespace(AsyncOpenAI=object)
if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace()

from app.services.campaign_content_fetchers import sanitize_news_feed_text
from app.services.campaign_content_service import CampaignContentService


def test_sanitize_news_feed_text_removes_junk_lines() -> None:
    dirty = "- Titolo &amp; dettaglio. continua a leggere su test. Fonte: redazione"
    cleaned = sanitize_news_feed_text(dirty)
    assert cleaned == "Titolo & dettaglio."


def test_news_ai_output_validation_rejects_meta_and_near_copy() -> None:
    service = CampaignContentService(database=object(), bot=object(), ai_service=None)  # type: ignore[arg-type]
    accepted_meta, reason_meta, _ = service._is_acceptable_news_ai_summary(  # type: ignore[attr-defined]
        "Ecco una possibile versione in italiano: questa notizia parla di un evento.",
        source_title="Evento importante",
        source_summary="Evento importante con aggiornamenti.",
    )
    assert accepted_meta is False
    assert reason_meta == "meta_output"
    accepted_copy, reason_copy, _ = service._is_acceptable_news_ai_summary(  # type: ignore[attr-defined]
        "Evento importante con aggiornamenti.",
        source_title="Evento importante",
        source_summary="Evento importante con aggiornamenti.",
    )
    assert accepted_copy is False
    assert reason_copy in {"too_similar_to_source", "feed_copy_overlap"}


def test_news_ai_output_validation_accepts_good_summary() -> None:
    service = CampaignContentService(database=object(), bot=object(), ai_service=None)  # type: ignore[arg-type]
    accepted, reason, cleaned = service._is_acceptable_news_ai_summary(  # type: ignore[attr-defined]
        "La notizia conferma nuovi sviluppi nelle prossime ore. Il quadro resta in aggiornamento.",
        source_title="Sviluppi in corso",
        source_summary="Aggiornamenti live e dettagli in evoluzione.",
    )
    assert accepted is True
    assert reason == "accepted"
    assert "notizia" in cleaned.lower()


def test_news_summary_fallback_limits_to_two_sentences() -> None:
    service = CampaignContentService(database=object(), bot=object(), ai_service=None)  # type: ignore[arg-type]
    summary = service._build_news_summary_fallback(  # type: ignore[attr-defined]
        title="Titolo di prova",
        cleaned_summary="Prima frase utile. Seconda frase utile. Terza frase da ignorare.",
    )
    assert "Prima frase utile." in summary
    assert "Seconda frase utile." in summary
    assert "Terza frase da ignorare." not in summary


def test_news_extras_are_normalized_to_italian_when_input_is_english() -> None:
    service = CampaignContentService(database=object(), bot=object(), ai_service=None)  # type: ignore[arg-type]

    async def _run() -> None:
        extras = await service._normalize_news_extras_payload(  # type: ignore[attr-defined]
            {
                "barzelletta": "This is an english joke about a hamster newsroom.",
                "aforisma": "Be yourself; everyone else is already taken. — Oscar Wilde",
                "canzone": "Heroes — David Bowie\nLive chart selection.",
                "meme": "When you open five tabs and call it focus.",
            }
        )
        assert " the " not in f" {extras['barzelletta'].lower()} "
        assert " the " not in f" {extras['aforisma'].lower()} "
        assert extras["canzone"].startswith("Heroes — David Bowie")
        assert "italiano" in extras["canzone"].lower()
        assert " the " not in f" {extras['meme'].lower()} "

    asyncio.run(_run())
