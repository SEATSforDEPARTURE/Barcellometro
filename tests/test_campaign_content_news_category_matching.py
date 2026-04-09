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


def test_synthetic_category_bucket_is_trusted_for_editorial_slot() -> None:
    payload = {
        "configured_categories": ["cat1"],
        "categories": {
            "cronaca": [
                {
                    "title": "Filler 1",
                    "summary": "Sommario filler 1",
                    "source": "ansa.it",
                    "link": "https://example.com/filler-1",
                    "published_at": "2026-04-09T11:00:00+00:00",
                },
                {
                    "title": "Filler 2",
                    "summary": "Sommario filler 2 con più dettaglio.",
                    "source": "ansa.it",
                    "link": "https://example.com/filler-2",
                    "published_at": "2026-04-09T10:00:00+00:00",
                },
            ],
            "cat1": [
                {
                    "title": "Titolo custom",
                    "summary": "Contenuto senza keyword di categoria nota.",
                    "source": "ansa.it",
                    "link": "https://example.com/custom",
                }
            ]
        },
    }
    slots = select_final_news_slots(payload)
    assert "cat1" in _slots_by_category(slots)


def test_neutral_story_in_known_bucket_is_not_auto_rejected() -> None:
    payload = {
        "configured_categories": ["tecnologia"],
        "categories": {
            "cronaca": [
                {
                    "title": "Filler 1",
                    "summary": "Sommario filler 1",
                    "source": "ansa.it",
                    "link": "https://example.com/filler-3",
                    "published_at": "2026-04-09T11:00:00+00:00",
                },
                {
                    "title": "Filler 2",
                    "summary": "Sommario filler 2 con più dettaglio.",
                    "source": "ansa.it",
                    "link": "https://example.com/filler-4",
                    "published_at": "2026-04-09T10:00:00+00:00",
                },
            ],
            "tecnologia": [
                {
                    "title": "Aggiornamento del servizio online",
                    "summary": "Nuove funzioni e rollout graduale per gli utenti.",
                    "source": "wired.it",
                    "link": "https://example.com/neutral-tech",
                }
            ]
        },
    }
    slots = select_final_news_slots(payload)
    assert "tecnologia" in _slots_by_category(slots)


def test_category_slot_tries_next_item_when_first_is_already_used() -> None:
    payload = {
        "configured_categories": ["cronaca"],
        "categories": {
            "cronaca": [
                {
                    "title": "Cronaca A",
                    "summary": "Sommario A",
                    "source": "ansa.it",
                    "link": "https://example.com/cronaca-a",
                    "published_at": "2026-04-09T10:00:00+00:00",
                },
                {
                    "title": "Cronaca B",
                    "summary": "Sommario B più esteso per il campo in evidenza.",
                    "source": "ansa.it",
                    "link": "https://example.com/cronaca-b",
                    "published_at": "2026-04-09T09:00:00+00:00",
                },
                {
                    "title": "Cronaca C",
                    "summary": "Sommario C",
                    "source": "ansa.it",
                    "link": "https://example.com/cronaca-c",
                    "published_at": "2026-04-09T08:00:00+00:00",
                },
            ]
        },
    }
    slots = select_final_news_slots(payload)
    category_slot = _slots_by_category(slots).get("cronaca")
    assert category_slot is not None
    assert category_slot["item"]["title"] == "Cronaca C"
