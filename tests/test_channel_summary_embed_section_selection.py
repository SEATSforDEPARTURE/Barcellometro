import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from app.services import channel_summary_service as channel_summary_module
from app.services.channel_summary_service import (
    ChannelSummaryService,
    normalize_channel_summary_embed_section_input,
    parse_channel_summary_embed_sections,
)
from app.services.author import attach_author_meta
from app.shared.discord.author_pipeline import finalize_embeds_author


def _fake_channel_with_capture():
    class _FakeChannel(channel_summary_module.discord.abc.Messageable):
        async def _get_channel(self):
            return self

        async def send(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return None

    channel = _FakeChannel()
    channel.send = AsyncMock()
    return channel


def _barcello_result() -> SimpleNamespace:
    return SimpleNamespace(score=65, color="giallo", trend="flat", metrics={"negativity_hits": 1, "positive_hits": 2})


def test_embed_section_parser_supports_csv_canonical_order_and_dedup() -> None:
    parsed, invalid = parse_channel_summary_embed_sections("riassunto, panoramica,riassunto,aura", strict=True)
    assert invalid == ()
    assert parsed == ("panoramica", "riassunto", "aura")

    normalized, invalid_normalized = normalize_channel_summary_embed_section_input("riassunto,riassunto,aura", strict=True)
    assert invalid_normalized == ()
    assert normalized == "riassunto,aura"


def test_embed_section_parser_rejects_unknown_values() -> None:
    parsed, invalid = parse_channel_summary_embed_sections("foo,aura", strict=True)
    assert parsed is None
    assert invalid == ("foo",)


def test_generate_and_send_for_channel_panoramica_aura_skips_summary_ai_and_respects_canonical_send_order() -> None:
    async def _run() -> None:
        channel = _fake_channel_with_capture()
        service = ChannelSummaryService(
            database=SimpleNamespace(mark_daily_report_sent=AsyncMock()),
            bot=SimpleNamespace(get_channel=lambda _cid: channel),
            summary_service=SimpleNamespace(build_summary=AsyncMock(), get_config=AsyncMock(return_value={})),
            barcello_service=SimpleNamespace(compute_channel_range=AsyncMock(return_value=_barcello_result())),
        )
        service._compute_previous_equivalent_barcello = AsyncMock(return_value=_barcello_result())
        service.build_channel_summary_aura_embed = AsyncMock(return_value=discord.Embed(title="AURA"))

        sent = await service.generate_and_send_for_channel(
            guild_id="1",
            channel_id="2",
            embed_section="aura,panoramica",
            manual=False,
        )

        assert sent is True
        service._summary.build_summary.assert_not_called()
        payload = channel.send.await_args.kwargs["embeds"]
        assert [embed.title for embed in payload] == ["📓 __**RESOCONTO CANALE · PANORAMICA**__", "AURA"]

    asyncio.run(_run())


def test_generate_and_send_for_channel_riassunto_flows_through_ai_pipeline() -> None:
    async def _run() -> None:
        channel = _fake_channel_with_capture()
        summary_stub = SimpleNamespace(
            build_summary=AsyncMock(
                return_value=SimpleNamespace(
                    themes=[],
                    moments=[],
                    quotes=[],
                    dynamics=[],
                    advice=[],
                    proverbio="",
                    who_interacted_today=[],
                    vibe_line="",
                    ai_status={"used_ai_output": True, "used_display_model": "gpt"},
                )
            ),
            get_config=AsyncMock(return_value={}),
        )
        db = SimpleNamespace(
            mark_daily_report_sent=AsyncMock(),
            fetch_messages_in_range=AsyncMock(return_value=[{"ts": "2026-04-01T00:00:00+00:00", "author_id": "10", "content": "ciao", "message_id": "m1"}]),
            fetch_message_by_id=AsyncMock(return_value=None),
        )
        service = ChannelSummaryService(
            database=db,
            bot=SimpleNamespace(get_channel=lambda _cid: channel),
            summary_service=summary_stub,
            barcello_service=SimpleNamespace(compute_channel_range=AsyncMock(return_value=_barcello_result())),
        )
        service._compute_previous_equivalent_barcello = AsyncMock(return_value=_barcello_result())
        service._build_who_interacted_candidates = AsyncMock(return_value=([], []))
        service._channel_summary_data_is_sufficient = lambda **_kwargs: (True, {"messages": 1, "users": 1, "usable_messages": 1})
        service.build_channel_summary_aura_embed = AsyncMock(return_value=discord.Embed(title="AURA"))

        sent = await service.generate_and_send_for_channel(
            guild_id="1",
            channel_id="2",
            embed_section="riassunto,aura",
            manual=False,
        )

        assert sent is True
        summary_stub.build_summary.assert_awaited_once()

    asyncio.run(_run())


def test_author_pagination_changes_for_single_vs_multi_sections() -> None:
    async def _run() -> None:
        single = [discord.Embed(title="one")]
        attach_author_meta(single[0], service_name="channel_summary", canonical_top_level_command="channelsummary")
        await finalize_embeds_author(single, None, default_service_name="channel_summary")
        assert single[0].author.name == "servizio CHANNEL SUMMARY"

        two = [discord.Embed(title="one"), discord.Embed(title="two")]
        for embed in two:
            attach_author_meta(embed, service_name="channel_summary", canonical_top_level_command="channelsummary")
        await finalize_embeds_author(two, None, default_service_name="channel_summary")
        assert two[0].author.name.endswith("(Pag. 1/2)")
        assert two[1].author.name.endswith("(Pag. 2/2)")

        three = [discord.Embed(title="one"), discord.Embed(title="two"), discord.Embed(title="three")]
        for embed in three:
            attach_author_meta(embed, service_name="channel_summary", canonical_top_level_command="channelsummary")
        await finalize_embeds_author(three, None, default_service_name="channel_summary")
        assert three[0].author.name.endswith("(Pag. 1/3)")
        assert three[1].author.name.endswith("(Pag. 2/3)")
        assert three[2].author.name.endswith("(Pag. 3/3)")

    asyncio.run(_run())
