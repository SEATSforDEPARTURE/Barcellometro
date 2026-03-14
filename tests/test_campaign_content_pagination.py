import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services.campaign_content_views import CampaignContentPaginationView, HoroscopePaginationView


class _FakeService:
    def __init__(self) -> None:
        self.persist_current_index = AsyncMock()
        self.load_message_record = AsyncMock(
            return_value={
                "embeds": [
                    {"title": "Overview"},
                    {"title": "Ariete"},
                    {"title": "Toro"},
                ]
            }
        )


class _FakeResponse:
    def __init__(self) -> None:
        self.send_message = AsyncMock()
        self.edit_message = AsyncMock()


class _FakeInteraction:
    def __init__(self) -> None:
        self.message = SimpleNamespace(id=999)
        self.response = _FakeResponse()


def test_news_weather_have_start_prev_next_navigation() -> None:
    view = CampaignContentPaginationView(_FakeService(), current_index=0, total_pages=3)
    labels = [item.label for item in view.children]
    assert "⏮️ INIZIO" in labels
    assert "⬅️ INDIETRO" in labels
    assert "➡️ AVANTI" in labels


def test_horoscope_has_overview_plus_all_sign_buttons_and_unique_custom_ids() -> None:
    view = HoroscopePaginationView(_FakeService())
    assert len(view.children) == 13

    labels = [item.label for item in view.children]
    assert labels[0] == "OVERVIEW"
    for sign in [
        "ARIETE",
        "TORO",
        "GEMELLI",
        "CANCRO",
        "LEONE",
        "VERGINE",
        "BILANCIA",
        "SCORPIONE",
        "SAGITTARIO",
        "CAPRICORNO",
        "ACQUARIO",
        "PESCI",
    ]:
        assert sign in labels

    custom_ids = [item.custom_id for item in view.children]
    assert len(custom_ids) == len(set(custom_ids))


def test_horoscope_sign_callback_navigates_to_expected_index() -> None:
    async def _run() -> None:
        service = _FakeService()
        view = HoroscopePaginationView(service)
        ariete_button = next(item for item in view.children if item.label == "ARIETE")
        interaction = _FakeInteraction()

        await ariete_button.callback(interaction)

        service.persist_current_index.assert_awaited_once_with("999", 1)
        interaction.response.edit_message.assert_awaited_once()

    asyncio.run(_run())
