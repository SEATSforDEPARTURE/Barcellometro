import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services.campaign_content_views import BaseCampaignNavigatorView, PersistentCampaignLauncherView


class _FakeService:
    def __init__(self) -> None:
        self.open_personal_navigator = AsyncMock(return_value=True)
        self.edit_public_message = AsyncMock(return_value=True)


class _FakeResponse:
    def __init__(self) -> None:
        self.send_message = AsyncMock()
        self.edit_message = AsyncMock()


class _FakeInteraction:
    def __init__(self) -> None:
        self.message = SimpleNamespace(id=999)
        self.response = _FakeResponse()


def test_weather_has_required_buttons() -> None:
    view = PersistentCampaignLauncherView(
        _FakeService(),
        service_type="WEATHER",
        total_pages=4,
        page_map=[
            {"type": "overview", "label": "⏮️ INIZIO", "page": 0},
            {"type": "area", "key": "nord", "label": "🧊 NORD", "page": 1},
            {"type": "area", "key": "centro", "label": "🏛️ CENTRO", "page": 2},
            {"type": "area", "key": "sud_e_isole", "label": "🌋 SUD E ISOLE", "page": 3},
        ],
    )
    labels = [item.label for item in view.children]
    assert labels[:3] == ["⏮️ INIZIO", "⬅️ INDIETRO", "➡️ AVANTI"]
    assert "🧊 NORD" in labels and "🏛️ CENTRO" in labels and "🌋 SUD E ISOLE" in labels


def test_news_dynamic_buttons_and_disabled_state() -> None:
    view = PersistentCampaignLauncherView(
        _FakeService(),
        service_type="NEWS",
        total_pages=3,
        page_map=[
            {"type": "overview", "label": "⏮️ INIZIO", "page": 0},
            {"type": "category", "key": "cronaca", "label": "📰 CRONACA", "page": 1},
            {"type": "category", "key": "sport", "label": "⚽ SPORT", "page": 2},
        ],
    )
    labels = [item.label for item in view.children]
    assert "📰 CRONACA" in labels
    assert "⚽ SPORT" in labels
    assert view.children[0].disabled is True
    assert view.children[1].disabled is True
    assert view.children[2].disabled is False


def test_horoscope_has_start_prev_next_and_all_signs() -> None:
    page_map = [{"type": "overview", "label": "⏮️ INIZIO", "page": 0}]
    signs = [
        "♈ ARIETE", "♉ TORO", "♊ GEMELLI", "♋ CANCRO", "♌ LEONE", "♍ VERGINE",
        "♎ BILANCIA", "♏ SCORPIONE", "♐ SAGITTARIO", "♑ CAPRICORNO", "♒ ACQUARIO", "♓ PESCI",
    ]
    for idx, sign in enumerate(signs, start=1):
        page_map.append({"type": "sign", "key": f"s{idx}", "label": sign, "page": idx})
    view = PersistentCampaignLauncherView(_FakeService(), service_type="HOROSCOPE", total_pages=13, page_map=page_map)
    labels = [item.label for item in view.children]
    assert labels[:3] == ["⏮️ INIZIO", "⬅️ INDIETRO", "➡️ AVANTI"]
    for sign in signs:
        assert sign in labels


def test_ephemeral_navigation_preferred_over_public_edit() -> None:
    async def _run() -> None:
        service = _FakeService()
        view = PersistentCampaignLauncherView(
            service,
            service_type="NEWS",
            total_pages=2,
            page_map=[{"type": "overview", "label": "⏮️ INIZIO", "page": 0}, {"type": "category", "key": "cronaca", "label": "📰 CRONACA", "page": 1}],
        )
        interaction = _FakeInteraction()
        next_button = view.children[2]
        await next_button.callback(interaction)
        service.open_personal_navigator.assert_awaited_once()
        service.edit_public_message.assert_not_called()

    asyncio.run(_run())


def test_personal_navigator_disables_edges() -> None:
    embeds = [{"title": "p0"}, {"title": "p1"}, {"title": "p2"}]
    page_map = [{"type": "overview", "label": "⏮️ INIZIO", "page": 0}, {"type": "category", "key": "a", "label": "📌 A", "page": 1}]
    view = BaseCampaignNavigatorView(_FakeService(), embeds=embeds, page_map=page_map, current_index=0, timeout=60)
    assert view.children[0].disabled is True
    assert view.children[1].disabled is True
    assert view.children[2].disabled is False
