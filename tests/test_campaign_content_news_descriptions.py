import re
import sys
import types

from tests._sqlite_stub import ensure_sqlite_stub

ensure_sqlite_stub()

if "openai" not in sys.modules:
    sys.modules["openai"] = types.SimpleNamespace(AsyncOpenAI=object)
if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace()

from app.services.campaign_content_formatter import build_news_embeds
from app.services.campaign_content_service import CampaignContentService


def _sentence_count(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()])


def test_news_overview_intro_does_not_start_with_emoji_and_keeps_prompt_line() -> None:
    embeds = build_news_embeds(
        {},
        {
            "generated_at": "2026-04-09T20:30:00+02:00",
            "categories": {"cronaca": [{"title": "Titolo", "summary": "Testo notizia", "source": "ansa", "link": "https://x"}]},
        },
    )
    description = embeds[0].description or ""
    normalized = description.lstrip("*")
    assert normalized.startswith("Buonasera")
    assert "📰" in description
    assert "**Che ci racconta il mondo oggi?**" in description


def test_ultimora_and_in_evidenza_share_summary_pipeline_without_bot_opening_and_max_two_sentences() -> None:
    payload = {
        "categories": {
            "cronaca": [
                {
                    "title": "Vertice urgente",
                    "summary": "Il governo annuncia una riunione urgente per misure immediate su sicurezza e trasporti.",
                    "source": "ansa.it",
                    "link": "https://example.com/a",
                    "published_at": "2026-04-09T10:00:00+00:00",
                }
            ],
            "politica": [
                {
                    "title": "Dibattito in aula",
                    "summary": "Opposizione e maggioranza si scontrano in aula durante la discussione della riforma.",
                    "source": "ansa.it",
                    "link": "https://example.com/b",
                    "published_at": "2026-04-09T09:00:00+00:00",
                }
            ],
        }
    }
    embeds = build_news_embeds({}, payload)
    ultimora_value = embeds[0].fields[0].value or ""
    evidenza_value = embeds[0].fields[1].value or ""

    for value in (ultimora_value, evidenza_value):
        summary_line = value.split("\n")[1]
        assert not summary_line.removeprefix("• ").lstrip().startswith(("👀", "😵‍💫", "🤖", "😔", "🫥"))
        assert not summary_line.lower().startswith(("• qui la faccenda", "• in pratica", "• attenzione"))
        assert _sentence_count(summary_line.removeprefix("• ")) <= 2


def test_news_ai_validation_rejects_opening_emoji_or_bot_comment_and_fallback_respects_opening_rules() -> None:
    service = CampaignContentService(database=object(), bot=object(), ai_service=None)  # type: ignore[arg-type]

    accepted, reason, _ = service._is_acceptable_news_ai_summary(  # type: ignore[attr-defined]
        "👀 La notizia conferma nuovi sviluppi. Il quadro resta aperto.",
        source_title="Sviluppi in corso",
        source_summary="Aggiornamenti live.",
    )
    assert accepted is False
    assert reason == "starts_with_emoji"

    accepted_comment, reason_comment, _ = service._is_acceptable_news_ai_summary(  # type: ignore[attr-defined]
        "Qui la faccenda si scalda: nuovi sviluppi in arrivo.",
        source_title="Sviluppi in corso",
        source_summary="Aggiornamenti live.",
    )
    assert accepted_comment is False
    assert reason_comment == "starts_with_bot_comment"

    fallback = service._build_news_summary_fallback(  # type: ignore[attr-defined]
        title="Aggiornamento traffico cittadino",
        cleaned_summary="Code in aumento sulle principali arterie urbane. Disagi nelle ore di punta.",
    )
    assert not fallback.lstrip().startswith(("👀", "😔", "🫥"))
    assert "qui la faccenda" not in fallback.lower()
    assert any(emoji in fallback for emoji in ("👀", "🫥"))
    assert _sentence_count(fallback) <= 2
