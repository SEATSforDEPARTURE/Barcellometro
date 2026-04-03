from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services.channel_summary_service import ChannelSummaryService


def _service() -> ChannelSummaryService:
    return ChannelSummaryService(
        database=SimpleNamespace(),
        bot=SimpleNamespace(),
        summary_service=SimpleNamespace(get_config=AsyncMock(return_value={})),
        barcello_service=SimpleNamespace(),
    )


def test_rank_trend_uses_first_time_wording_only_with_history() -> None:
    service = _service()
    emoji, comment, movement = service._rank_trend(None, 3, has_historical_presence=False, history_available=True)
    assert emoji == "🆕"
    assert movement == "new_first_time"
    assert comment == "prima volta in classifica"


def test_rank_trend_falls_back_to_new_period_when_history_is_not_available() -> None:
    service = _service()
    emoji, comment, movement = service._rank_trend(None, 3, has_historical_presence=False, history_available=False)
    assert emoji == "🆕"
    assert movement == "new_period"
    assert comment == "nuovo ingresso nel periodo"
