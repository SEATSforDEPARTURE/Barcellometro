import asyncio
import sys
import types
from unittest.mock import AsyncMock

from tests._sqlite_stub import ensure_sqlite_stub

ensure_sqlite_stub()

if "openai" not in sys.modules:
    sys.modules["openai"] = types.SimpleNamespace(AsyncOpenAI=object)
if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace()

from app.services.campaign_content_formatter import build_news_embeds, select_final_news_slots
from app.services.campaign_content_service import CampaignContentService


def test_selection_pipeline_limits_to_final_slots_for_ai_calls() -> None:
    class _Ai:
        def __init__(self) -> None:
            self.ask_for_task = AsyncMock(return_value="La notizia aggiorna il quadro corrente. Sintesi finale 👀.")

        def is_enabled(self):
            return True

        def get_model_config(self, _task):
            return "gpt-4o-mini"

        def get_model_display_name(self, _task):
            return "gpt-4o-mini"

    categories: dict[str, list[dict[str, str]]] = {}
    for idx in range(10):
        category = f"cat{idx}"
        categories[category] = [
            {
                "title": f"Titolo {idx}-{news_idx}",
                "summary": "Sintesi notizia utile.",
                "source": "ansa.it",
                "category": category,
                "link": f"https://example.com/{idx}/{news_idx}",
                "published_at": f"2026-04-09T{(news_idx % 23):02d}:00:00+00:00",
            }
            for news_idx in range(5)
        ]

    async def _run() -> None:
        ai = _Ai()
        service = CampaignContentService(database=object(), bot=object(), ai_service=ai)  # type: ignore[arg-type]
        payload = {"configured_categories": list(categories.keys()), "categories": categories}
        selected = select_final_news_slots(payload)
        assert len(selected) == 5
        await service._rewrite_news_payload(payload)  # type: ignore[attr-defined]
        assert ai.ask_for_task.await_count == 5

    asyncio.run(_run())


def test_global_dedupe_uses_next_valid_item_and_normalizes_urls() -> None:
    payload = {
        "configured_categories": ["cronaca", "sport"],
        "categories": {
            "cronaca": [
                {
                    "title": "Titolo condiviso",
                    "summary": "S1",
                    "source": "ansa",
                    "link": "https://example.com/shared/",
                    "published_at": "2026-04-09T10:00:00+00:00",
                },
            ],
            "sport": [
                {
                    "title": "Titolo condiviso",
                    "summary": "S2",
                    "source": "gazzetta",
                    "link": "https://example.com/shared",
                    "published_at": "2026-04-09T09:00:00+00:00",
                },
                {
                    "title": "Sport esclusivo",
                    "summary": "S3",
                    "source": "gazzetta",
                    "link": "https://example.com/sport",
                    "published_at": "2026-04-09T08:00:00+00:00",
                },
            ],
        },
    }
    embeds = build_news_embeds({}, payload)
    values = [field.value for field in embeds[0].fields]
    assert sum("Titolo condiviso" in value for value in values) == 1
    assert any("Sport esclusivo" in value for value in values)


def test_global_dedupe_falls_back_to_title_plus_source_when_url_missing() -> None:
    payload = {
        "configured_categories": ["cronaca", "politica"],
        "categories": {
            "cronaca": [
                {"title": "Titolo senza link", "summary": "S1", "source": "ansa.it", "published_at": "2026-04-09T10:00:00+00:00"},
            ],
            "politica": [
                {"title": "Titolo senza link", "summary": "S2", "source": "ansa.it", "published_at": "2026-04-09T09:00:00+00:00"},
                {"title": "Politica esclusiva", "summary": "S3", "source": "ansa.it", "published_at": "2026-04-09T08:00:00+00:00"},
            ],
        },
    }
    embeds = build_news_embeds({}, payload)
    values = [field.value for field in embeds[0].fields]
    assert sum("Titolo senza link" in value for value in values) == 1
    assert any("Politica esclusiva" in value for value in values)
