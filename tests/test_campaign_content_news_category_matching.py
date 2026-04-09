from app.services.campaign_content_formatter import select_final_news_slots


def _slots_by_category(slots: list[dict]) -> dict[str, dict]:
    return {str(slot.get("category")): slot for slot in slots if slot.get("slot") == "category"}


def test_economy_story_is_not_selected_for_technology_slot() -> None:
    payload = {
        "configured_categories": ["tecnologia"],
        "categories": {
            "tecnologia": [
                {
                    "title": "FMI: inflazione e crescita sotto pressione",
                    "summary": "Mercati, debito e banche centrali nel nuovo outlook.",
                    "source": "wired.it",
                    "link": "https://example.com/fmi",
                    "category": "tecnologia",
                    "classified_categories": ["tecnologia"],
                }
            ]
        },
    }
    slots = select_final_news_slots(payload)
    assert "tecnologia" not in _slots_by_category(slots)


def test_politics_story_is_selected_for_politics_slot() -> None:
    payload = {
        "configured_categories": ["politica"],
        "categories": {
            "cronaca": [
                {
                    "title": "Incidente in tangenziale, code per ore",
                    "summary": "Intervento dei soccorsi e deviazioni.",
                    "source": "ansa.it",
                    "link": "https://example.com/filler-1",
                    "published_at": "2026-04-09T09:00:00+00:00",
                },
                {
                    "title": "Viabilità in ripresa dopo il maltempo",
                    "summary": "Persistono rallentamenti su alcune tratte.",
                    "source": "ansa.it",
                    "link": "https://example.com/filler-2",
                    "published_at": "2026-04-09T08:00:00+00:00",
                },
            ],
            "politica": [
                {
                    "title": "Il premier riferisce in Parlamento sul nuovo decreto",
                    "summary": "Intervento in Senato, confronto con le opposizioni.",
                    "source": "ansa.it",
                    "link": "https://example.com/politica",
                    "category": "politica",
                    "classified_categories": ["politica"],
                }
            ]
        },
    }
    slots = select_final_news_slots(payload)
    assert "politica" in _slots_by_category(slots)


def test_selection_uses_only_requested_category_bucket() -> None:
    payload = {
        "configured_categories": ["tecnologia"],
        "categories": {
            "tecnologia": [],
            "politica": [
                {
                    "title": "Governo e opposizione in Aula",
                    "summary": "Discussione parlamentare.",
                    "source": "ansa.it",
                    "link": "https://example.com/politica2",
                    "category": "politica",
                    "classified_categories": ["politica"],
                }
            ],
        },
    }
    slots = select_final_news_slots(payload)
    assert "tecnologia" not in _slots_by_category(slots)
