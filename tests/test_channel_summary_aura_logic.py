from datetime import datetime
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services.channel_summary_service import ChannelSummaryService


class _FakeAuraDb:
    async def fetch_aura_channel_ledger_report(self, guild_id, channel_id, start_ts, end_ts):
        return {
            "totals": {"users_count": 3, "positive": 120, "negative": -20},
            "by_reason": [
                {"reason_code": "missions.completed", "total": 80},
                {"reason_code": "spam", "total": -10},
            ],
        }

    async def fetch_aura_channel_top_users(self, guild_id, channel_id, start_ts, end_ts, limit=10):
        return [
            {"user_id": "101", "total": 70},
            {"user_id": "202", "total": 50},
        ]

    async def fetch_aura_channel_users_with_history_before(self, guild_id, channel_id, prev_start_ts, current_top_ids):
        return {"101"}

    async def has_aura_channel_history_before(self, guild_id, channel_id, prev_start_ts):
        return True

    async def fetch_aura_channel_mission_stats(self, guild_id, channel_id, start_ts, end_ts):
        return {
            "assigned_role1": 2,
            "assigned_role2": 2,
            "completed_role1": 1,
            "completed_role2": 1,
            "eligible_role1": 3,
            "eligible_role2": 3,
        }

    async def fetch_aura_channel_avg_user_karma_score(self, guild_id, channel_id, start_ts, end_ts):
        if "2026-02" in start_ts:
            return {"avg_score": 0.15, "participants_count": 2}
        return {"avg_score": 0.4, "participants_count": 2}


def _service() -> ChannelSummaryService:
    return ChannelSummaryService(
        database=_FakeAuraDb(),
        bot=SimpleNamespace(),
        summary_service=SimpleNamespace(
            get_config=AsyncMock(return_value={"tiers": {"role1": {"label": "PLUS"}, "role2": {"label": "PRO"}}})
        ),
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


def test_generate_channel_aura_embed_matches_shared_full_report_builder() -> None:
    async def _run() -> None:
        service = _service()
        start_local = datetime(2026, 3, 1, 0, 0)
        end_local = datetime(2026, 3, 1, 23, 59)

        standalone_embed = await service.generate_channel_aura_embed(
            guild_id="1",
            channel_id="2",
            start_local=start_local,
            end_local=end_local,
        )
        full_report_third_embed = await service.build_channel_summary_aura_embed(
            guild_id="1",
            channel_id="2",
            start_local=start_local,
            end_local=end_local,
        )

        assert standalone_embed is not None
        assert full_report_third_embed is not None
        assert standalone_embed.title == full_report_third_embed.title
        assert standalone_embed.description == full_report_third_embed.description
        assert [field.name for field in standalone_embed.fields] == [field.name for field in full_report_third_embed.fields]
        assert [field.value for field in standalone_embed.fields] == [field.value for field in full_report_third_embed.fields]
        assert standalone_embed.footer.text == full_report_third_embed.footer.text

    asyncio.run(_run())


def test_channel_summary_aura_karma_uses_average_of_eligible_participants() -> None:
    async def _run() -> None:
        service = _service()
        embed = await service.build_channel_summary_aura_embed(
            guild_id="1",
            channel_id="2",
            start_local=datetime(2026, 3, 1, 0, 0),
            end_local=datetime(2026, 3, 1, 23, 59),
        )
        assert embed is not None
        karma_field = next(field for field in embed.fields if "KARMA" in field.name.upper())
        trend_field = next(field for field in embed.fields if "TREND" in field.name.upper())
        assert "angelico" in karma_field.value
        assert "migliorato" in trend_field.value
        assert "partecipanti Aura" in trend_field.value

    asyncio.run(_run())


def test_channel_summary_aura_karma_falls_back_when_no_eligible_participants() -> None:
    class _NoEligibleDb(_FakeAuraDb):
        async def fetch_aura_channel_avg_user_karma_score(self, guild_id, channel_id, start_ts, end_ts):
            return {"avg_score": None, "participants_count": 0}

    async def _run() -> None:
        service = ChannelSummaryService(
            database=_NoEligibleDb(),
            bot=SimpleNamespace(),
            summary_service=SimpleNamespace(get_config=AsyncMock(return_value={})),
            barcello_service=SimpleNamespace(),
        )
        embed = await service.build_channel_summary_aura_embed(
            guild_id="1",
            channel_id="2",
            start_local=datetime(2026, 3, 1, 0, 0),
            end_local=datetime(2026, 3, 1, 23, 59),
        )
        assert embed is not None
        karma_field = next(field for field in embed.fields if "KARMA" in field.name.upper())
        assert "Dati ancora troppo scarsi" in karma_field.value

    asyncio.run(_run())
