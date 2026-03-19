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


def _build_button_labels(view) -> list[str]:
    return [item.label for item in view.children]


def test_weather_has_required_buttons() -> None:
    view = PersistentCampaignLauncherView(
        _FakeService(),
        service_type="WEATHER",
        total_pages=4,
        page_map=[
            {"type": "overview", "label": "Overview Italia", "page": 0},
            {"type": "area", "key": "nord", "label": "🧊 NORD", "page": 1},
            {"type": "area", "key": "centro", "label": "🏛️ CENTRO", "page": 2},
            {"type": "area", "key": "sud_e_isole", "label": "🌋 SUD E ISOLE", "page": 3},
        ],
    )
    labels = _build_button_labels(view)
    assert labels == ["🧊 NORD", "🏛️ CENTRO", "🌋 SUD E ISOLE"]
    assert all(token not in labels for token in ["⏮️ INIZIO", "⬅️ INDIETRO", "➡️ AVANTI", "Overview Italia"])


def test_news_dynamic_buttons_and_disabled_state() -> None:
    view = PersistentCampaignLauncherView(
        _FakeService(),
        service_type="NEWS",
        total_pages=3,
        page_map=[
            {"type": "overview", "label": "Inizio", "page": 0},
            {"type": "category", "key": "cronaca", "label": "📰 CRONACA", "page": 1},
            {"type": "category", "key": "sport", "label": "⚽ SPORT", "page": 2},
        ],
    )
    labels = _build_button_labels(view)
    assert labels == ["📰 CRONACA", "⚽ SPORT"]
    assert all(item.disabled is False for item in view.children)


def test_horoscope_has_all_signs_without_public_nav_buttons() -> None:
    page_map = [{"type": "overview", "label": "Inizio", "page": 0}]
    signs = [
        "♈ ARIETE", "♉ TORO", "♊ GEMELLI", "♋ CANCRO", "♌ LEONE", "♍ VERGINE",
        "♎ BILANCIA", "♏ SCORPIONE", "♐ SAGITTARIO", "♑ CAPRICORNO", "♒ ACQUARIO", "♓ PESCI",
    ]
    for idx, sign in enumerate(signs, start=1):
        page_map.append({"type": "sign", "key": f"s{idx}", "label": sign, "page": idx})
    view = PersistentCampaignLauncherView(_FakeService(), service_type="HOROSCOPE", total_pages=13, page_map=page_map)
    labels = _build_button_labels(view)
    assert "⏮️ INIZIO" not in labels
    assert "⬅️ INDIETRO" not in labels
    assert "➡️ AVANTI" not in labels
    assert "Inizio" not in labels
    for sign in signs:
        assert sign in labels


def test_ephemeral_navigation_preferred_over_public_edit() -> None:
    async def _run() -> None:
        service = _FakeService()
        view = PersistentCampaignLauncherView(
            service,
            service_type="NEWS",
            total_pages=2,
            page_map=[{"type": "overview", "label": "Inizio", "page": 0}, {"type": "category", "key": "cronaca", "label": "📰 CRONACA", "page": 1}],
        )
        interaction = _FakeInteraction()
        first_dynamic_button = view.children[0]
        await first_dynamic_button.callback(interaction)
        service.open_personal_navigator.assert_awaited_once()
        service.edit_public_message.assert_not_called()

    asyncio.run(_run())


def test_personal_navigator_disables_current_section_only() -> None:
    embeds = [{"title": "overview"}, {"title": "cronaca"}, {"title": "sport"}]
    page_map = [
        {"type": "overview", "label": "Inizio", "page": 0},
        {"type": "category", "key": "cronaca", "label": "📰 CRONACA", "page": 1},
        {"type": "category", "key": "sport", "label": "⚽ SPORT", "page": 2},
    ]
    view = BaseCampaignNavigatorView(_FakeService(), embeds=embeds, page_map=page_map, service_type="NEWS", current_index=2, timeout=60)
    assert len(view.children) == 2
    assert view.children[0].disabled is False
    assert view.children[1].disabled is True


def test_launcher_button_handles_open_personal_navigator_failure_without_public_edit() -> None:
    async def _run() -> None:
        service = _FakeService()
        service.open_personal_navigator = AsyncMock(return_value=False)
        view = PersistentCampaignLauncherView(
            service,
            service_type="WEATHER",
            total_pages=4,
            page_map=[
                {"type": "overview", "label": "Overview Italia", "page": 0},
                {"type": "area", "key": "nord", "label": "🧊 NORD", "page": 1},
            ],
        )

        class _Resp:
            def __init__(self):
                self.send_message = AsyncMock()
            def is_done(self):
                return False

        interaction = SimpleNamespace(message=SimpleNamespace(id=999), response=_Resp(), followup=SimpleNamespace(send=AsyncMock()))
        button = view.children[0]
        await button.callback(interaction)

        service.open_personal_navigator.assert_awaited_once()
        service.edit_public_message.assert_not_called()
        interaction.response.send_message.assert_awaited_once()

    asyncio.run(_run())


def test_weather_ephemeral_click_edits_same_message() -> None:
    async def _run() -> None:
        embeds = [{"title": "Overview"}, {"title": "Nord"}, {"title": "Centro"}, {"title": "Sud"}]
        page_map = [
            {"type": "overview", "page": 0},
            {"type": "area", "key": "nord", "label": "🧊 NORD", "page": 1},
            {"type": "area", "key": "centro", "label": "🏛️ CENTRO", "page": 2},
            {"type": "area", "key": "sud_e_isole", "label": "🌋 SUD E ISOLE", "page": 3},
        ]
        view = BaseCampaignNavigatorView(_FakeService(), embeds=embeds, page_map=page_map, service_type="WEATHER", current_index=1, timeout=60)
        interaction = _FakeInteraction()
        await view.children[1].callback(interaction)
        interaction.response.edit_message.assert_awaited_once()
        interaction.response.send_message.assert_not_called()

    asyncio.run(_run())


def test_news_ephemeral_click_edits_same_message() -> None:
    async def _run() -> None:
        embeds = [{"title": "Overview"}, {"title": "Cronaca"}, {"title": "Sport"}]
        page_map = [
            {"type": "overview", "page": 0},
            {"type": "category", "key": "cronaca", "label": "📰 CRONACA", "page": 1},
            {"type": "category", "key": "sport", "label": "⚽ SPORT", "page": 2},
        ]
        view = BaseCampaignNavigatorView(_FakeService(), embeds=embeds, page_map=page_map, service_type="NEWS", current_index=1, timeout=60)
        interaction = _FakeInteraction()
        await view.children[1].callback(interaction)
        interaction.response.edit_message.assert_awaited_once()
        interaction.response.send_message.assert_not_called()

    asyncio.run(_run())


def test_horoscope_ephemeral_click_edits_same_message() -> None:
    async def _run() -> None:
        embeds = [{"title": "Overview"}, {"title": "Ariete"}, {"title": "Toro"}]
        page_map = [
            {"type": "overview", "page": 0},
            {"type": "sign", "key": "ariete", "label": "♈ ARIETE", "page": 1},
            {"type": "sign", "key": "toro", "label": "♉ TORO", "page": 2},
        ]
        view = BaseCampaignNavigatorView(_FakeService(), embeds=embeds, page_map=page_map, service_type="HOROSCOPE", current_index=1, timeout=60)
        interaction = _FakeInteraction()
        await view.children[1].callback(interaction)
        interaction.response.edit_message.assert_awaited_once()
        interaction.response.send_message.assert_not_called()

    asyncio.run(_run())
