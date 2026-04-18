from datetime import datetime
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from app.services import channel_summary_service as channel_summary_module
from app.services.channel_summary_service import ChannelSummaryService
from app.services.author import attach_author_meta
from app.shared.discord.author_pipeline import finalize_embeds_author


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
        assert [field.name for field in standalone_embed.fields] == [field.name for field in full_report_third_embed.fields]
        assert [field.value for field in standalone_embed.fields] == [field.value for field in full_report_third_embed.fields]
        assert standalone_embed.footer.text == full_report_third_embed.footer.text

    asyncio.run(_run())


def test_generate_channel_aura_embed_uses_channel_summary_author_without_pagination() -> None:
    async def _run() -> None:
        service = _service()
        embed = await service.generate_channel_aura_embed(
            guild_id="1",
            channel_id="2",
            start_local=datetime(2026, 4, 16, 0, 0),
            end_local=datetime(2026, 4, 16, 23, 59),
            period_label="oggi",
        )
        assert embed is not None
        await finalize_embeds_author([embed], None, default_service_name="channel_summary")

        assert embed.author.name == "servizio CHANNEL SUMMARY"
        assert "Pag." not in (embed.author.name or "")
        assert "DM SERVER SUMMARY" not in (embed.author.name or "")
        assert embed.description is not None and embed.description.startswith("**Oggi. ")
        assert "sono stati assegnati 120 PUNTI AURA" in (embed.description or "")
        assert "Nel periodo di riferimento" not in (embed.description or "")
        assert "PUNTI AURA" in (embed.description or "")

    asyncio.run(_run())


def test_full_report_channel_aura_embed_keeps_multipage_description_style() -> None:
    async def _run() -> None:
        service = _service()
        embed = await service.build_channel_summary_aura_embed(
            guild_id="1",
            channel_id="2",
            start_local=datetime(2026, 4, 16, 0, 0),
            end_local=datetime(2026, 4, 16, 23, 59),
            window_header="**🗓️ Oggi. Giovedì, 16 Aprile 2026**",
        )
        assert embed is not None
        assert (embed.description or "").startswith("*Oggi. ")
        assert "Nel periodo di riferimento" in (embed.description or "")

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


def test_generate_and_send_for_channel_aura_only_skips_summary_pipeline() -> None:
    async def _run() -> None:
        class _FakeChannel(channel_summary_module.discord.abc.Messageable):
            async def _get_channel(self):
                return self

            async def send(self, *args, **kwargs):  # noqa: ANN002, ANN003
                return None

        channel = _FakeChannel()
        channel.send = AsyncMock()
        bot = SimpleNamespace(get_channel=lambda _cid: channel)
        database = SimpleNamespace(mark_daily_report_sent=AsyncMock())
        summary_service = SimpleNamespace(build_summary=AsyncMock(), get_config=AsyncMock(return_value={}))
        service = ChannelSummaryService(
            database=database,
            bot=bot,
            summary_service=summary_service,
            barcello_service=SimpleNamespace(),
        )
        service.build_channel_summary_aura_embed = AsyncMock(return_value=SimpleNamespace())
        old_attach_footer_meta = channel_summary_module.attach_footer_meta
        old_finalize = channel_summary_module.finalize_embeds_author
        channel_summary_module.attach_footer_meta = lambda *_args, **_kwargs: None
        channel_summary_module.finalize_embeds_author = AsyncMock()

        try:
            sent = await service.generate_and_send_for_channel(
                guild_id="1",
                channel_id="2",
                embed_section="aura",
                manual=False,
            )
        finally:
            channel_summary_module.attach_footer_meta = old_attach_footer_meta
            channel_summary_module.finalize_embeds_author = old_finalize

        assert sent is True
        summary_service.build_summary.assert_not_called()
        channel.send.assert_awaited_once()
        payload = channel.send.await_args.kwargs["embeds"]
        assert len(payload) == 1

    asyncio.run(_run())


def test_generate_and_send_for_channel_aura_only_uses_channel_summary_author_without_pagination() -> None:
    async def _run() -> None:
        class _FakeChannel(channel_summary_module.discord.abc.Messageable):
            async def _get_channel(self):
                return self

            async def send(self, *args, **kwargs):  # noqa: ANN002, ANN003
                return None

        channel = _FakeChannel()
        channel.send = AsyncMock()
        bot = SimpleNamespace(get_channel=lambda _cid: channel)
        database = SimpleNamespace(mark_daily_report_sent=AsyncMock())
        summary_service = SimpleNamespace(build_summary=AsyncMock(), get_config=AsyncMock(return_value={}))
        service = ChannelSummaryService(
            database=database,
            bot=bot,
            summary_service=summary_service,
            barcello_service=SimpleNamespace(),
        )
        aura_embed = discord.Embed(title="📓 __**RESOCONTO CANALE · AURA**__", description="*Test aura.*")
        attach_author_meta(aura_embed, service_name="aura", canonical_top_level_command="dmserversummary")
        service.build_channel_summary_aura_embed = AsyncMock(return_value=aura_embed)

        sent = await service.generate_and_send_for_channel(
            guild_id="1",
            channel_id="2",
            embed_section="aura",
            manual=False,
        )

        assert sent is True
        payload = channel.send.await_args.kwargs["embeds"]
        assert len(payload) == 1
        assert payload[0].author.name == "servizio CHANNEL SUMMARY"
        assert "Pag." not in (payload[0].author.name or "")
        assert "DM SERVER SUMMARY" not in (payload[0].author.name or "")

    asyncio.run(_run())
