import asyncio

import discord

from app.renderers.channel_summary import MessageMeta, QuoteRenderItem, build_channel_summary_embeds, build_channel_summary_insufficient_data_embed
from app.services.author import attach_author_meta
from app.services.barcello_service import BarcelloResult
from app.services.content_summary_service import SummaryItem, SummaryResult
from app.services.embed_images import get_embed_images_meta
from app.services.footer import get_footer_meta
from app.shared.discord.author_pipeline import finalize_embeds_author


def _build_fixture_embeds() -> list[discord.Embed]:
    bar = BarcelloResult(score=64, color="giallo", trend={"delta": -1})
    m1 = SummaryItem(ts="2026-04-03T09:00:00+00:00", text="Mario avvia il confronto", author_id="1", message_ids=["10"])
    dyn = SummaryItem(ts="2026-04-03T10:00:00+00:00", text="Luigi chiarisce un punto", author_id="2", message_ids=["11"])
    summary = SummaryResult(
        themes=["moderazione"],
        moments=[m1],
        quotes=[],
        dynamics=[dyn],
        degrade=[],
        invigorate=[],
        advice=["Tenere il focus sui fatti."],
        metrics={},
        ai_status={},
    )
    index = {
        "10": MessageMeta(message_id="10", ts="2026-04-03T09:00:00+00:00", author_id="1"),
        "11": MessageMeta(message_id="11", ts="2026-04-03T10:00:00+00:00", author_id="2"),
    }
    aura_embed = discord.Embed(title="✨ AURA")
    attach_author_meta(aura_embed, service_name="channel_summary", canonical_top_level_command="channelsummary")

    return build_channel_summary_embeds(
        guild_id=1,
        channel_id=2,
        channel_name="generale",
        barcello_status=bar,
        barcello_line="con un clima complessivamente altalenante e alcuni attriti distribuiti nel periodo",
        summary_result=summary,
        message_index=index,
        advice_bullets=["Favorire risposte costruttive"],
        proverbio="Chi ben comincia è a metà dell'opera.",
        window_header="**🗓️ Oggi. Venerdì, 3 Aprile 2026**",
        moment_primary={id(m1): "10"},
        dynamic_primary={id(dyn): "11"},
        dynamic_names={id(dyn): ["Luigi"]},
        quote_render_items=[QuoteRenderItem(message_id="10", ts="2026-04-03T09:00:00+00:00", quote_text="Messaggio", author_display="Mario")],
        aura_embed=aura_embed,
    )


def test_channel_summary_author_pagination_is_global_across_split_batches() -> None:
    async def _run() -> None:
        embeds = _build_fixture_embeds()
        assert len(embeds) == 3

        await finalize_embeds_author(embeds, None, default_service_name="channel_summary")

        first_batch = embeds[:2]
        second_batch = [embeds[2]]
        assert first_batch[0].author.name == "servizio CHANNEL SUMMARY · (Pag. 1/3)"
        assert first_batch[1].author.name == "servizio CHANNEL SUMMARY · (Pag. 2/3)"
        assert second_batch[0].author.name == "servizio CHANNEL SUMMARY · (Pag. 3/3)"

    asyncio.run(_run())


def test_channel_summary_aura_embed_is_included_in_global_author_pagination() -> None:
    async def _run() -> None:
        embeds = _build_fixture_embeds()
        await finalize_embeds_author(embeds, None, default_service_name="channel_summary")
        assert embeds[2].author.name == "servizio CHANNEL SUMMARY · (Pag. 3/3)"

    asyncio.run(_run())


def test_channel_summary_first_embed_uses_narrative_description_without_period_or_alert_fields() -> None:
    first_embed = _build_fixture_embeds()[0]
    field_names = [f.name for f in first_embed.fields]

    assert not any("PERIODO" in name for name in field_names)
    assert not any("ALLERTA" in name for name in field_names)
    assert any("PUNTI SALUTE" in name for name in field_names)
    assert any("TREND" in name for name in field_names)

    description = first_embed.description or ""
    assert description.startswith("*") and description.endswith("*")
    assert "Oggi. Venerdì, 3 Aprile 2026" in description
    assert "**giallo**" in description
    assert "altalenante" in description

    assert get_footer_meta(first_embed) is not None
    assert get_embed_images_meta(first_embed) is not None


def test_channel_summary_insufficient_data_embed_uses_narrative_description_only() -> None:
    embed = build_channel_summary_insufficient_data_embed(
        channel_name="generale",
        window_header="**🗓️ Oggi. Venerdì, 3 Aprile 2026**",
    )

    field_names = [f.name for f in embed.fields]
    assert not any("PERIODO" in name for name in field_names)
    assert not any("STATO" in name for name in field_names)

    description = embed.description or ""
    assert description.startswith("*") and description.endswith("*")
    assert "Oggi. Venerdì, 3 Aprile 2026" in description
    assert "dati insufficienti" in description.lower()

    assert get_footer_meta(embed) is not None
    assert get_embed_images_meta(embed) is not None
