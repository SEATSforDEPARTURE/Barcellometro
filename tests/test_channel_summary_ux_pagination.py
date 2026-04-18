import asyncio

import discord

from app.renderers.channel_summary import (
    MessageMeta,
    QuoteRenderItem,
    _rolling_period_to_italian,
    build_channel_summary_period_prefix,
    build_channel_summary_embeds,
    build_channel_summary_insufficient_data_embed,
)
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
    aura_embed = discord.Embed(title="📓 __**RESOCONTO CANALE · AURA**__")
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


def test_channel_summary_standalone_riassunto_has_period_prefix_and_no_pagination() -> None:
    async def _run() -> None:
        embeds = _build_fixture_embeds()
        summary_embed = embeds[1]
        period_prefix = build_channel_summary_period_prefix("**🗓️ Oggi. Venerdì, 3 Aprile 2026**", trailing_period=False)
        summary_embed.description = f"**{period_prefix}** è successo..."

        await finalize_embeds_author([summary_embed], None, default_service_name="channel_summary")

        assert summary_embed.author.name == "servizio CHANNEL SUMMARY"
        assert "Pag." not in (summary_embed.author.name or "")
        assert (summary_embed.description or "").startswith("**Oggi.")
        assert "è successo..." in (summary_embed.description or "")
        assert "Andiamo a leggere cosa è successo" not in (summary_embed.description or "")

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
    assert "**Oggi. Venerdì, 3 Aprile 2026**" in description
    assert "**giallo**" in description
    assert "**altalenante e alcuni attriti distribuiti nel periodo**" in description
    assert description.count("il barcello") == 1
    assert description.count("clima") == 1
    assert "Nella giornata" not in description
    assert "Nel periodo selezionato" not in description
    assert "il barcello è rimasto" not in description

    assert get_footer_meta(first_embed) is not None
    assert get_embed_images_meta(first_embed) is not None


def test_channel_summary_titles_match_requested_naming() -> None:
    embeds = _build_fixture_embeds()
    assert embeds[0].title == "📓 __**RESOCONTO CANALE · PANORAMICA**__"
    assert embeds[1].title == "📓 __**RESOCONTO CANALE · RIASSUNTO**__"
    assert embeds[2].title == "📓 __**RESOCONTO CANALE · AURA**__"


def test_rolling_period_uses_correct_italian_grammar() -> None:
    assert _rolling_period_to_italian("Ultimo minuto") == "Nell'ultimo minuto"
    assert _rolling_period_to_italian("Ultimi 40 minuti") == "Negli ultimi 40 minuti"
    assert _rolling_period_to_italian("Ultima ora") == "Nell'ultima ora"
    assert _rolling_period_to_italian("Ultime 2 ore") == "Nelle ultime 2 ore"
    assert _rolling_period_to_italian("Ultimo giorno") == "Nell'ultimo giorno"
    assert _rolling_period_to_italian("Ultimi 4 giorni") == "Negli ultimi 4 giorni"
    assert _rolling_period_to_italian("Ultima settimana") == "Nell'ultima settimana"
    assert _rolling_period_to_italian("Ultime 3 settimane") == "Nelle ultime 3 settimane"


def test_channel_summary_description_for_ultimi_and_range_respects_markdown_pattern() -> None:
    bar = BarcelloResult(score=80, color="verde", trend={"delta": 1})
    summary = SummaryResult(themes=[], moments=[], quotes=[], dynamics=[], degrade=[], invigorate=[], advice=[], metrics={}, ai_status={})

    ultimi_embed = build_channel_summary_embeds(
        guild_id=1,
        channel_id=2,
        channel_name="generale",
        barcello_status=bar,
        barcello_line="il barcello è stato verde, con un clima complessivamente disteso",
        summary_result=summary,
        message_index={},
        advice_bullets=[],
        proverbio="",
        window_header="**🗓️ Ultime 2 ore\n03/04/2026 21:26 → 03/04/2026 23:26**",
        moment_primary={},
        dynamic_primary={},
        dynamic_names={},
        quote_render_items=[],
    )[0]
    assert ultimi_embed.description == "***Nelle ultime 2 ore** (03/04/2026 21:26 → 03/04/2026 23:26) il barcello è stato **verde**, con un clima **disteso**.*"

    range_embed = build_channel_summary_embeds(
        guild_id=1,
        channel_id=2,
        channel_name="generale",
        barcello_status=bar,
        barcello_line="con un clima altalenante",
        summary_result=summary,
        message_index={},
        advice_bullets=[],
        proverbio="",
        window_header="**🗓️ 30/03/2026 00:00 → 03/04/2026 23:59**",
        moment_primary={},
        dynamic_primary={},
        dynamic_names={},
        quote_render_items=[],
    )[0]
    description = range_embed.description or ""
    assert description.startswith("*") and description.endswith("*")
    assert "**Periodo selezionato** (30/03/2026 00:00 → 03/04/2026 23:59)" in description
    assert "**verde**" in description and "**altalenante**" in description
    assert description.count("il barcello è stato") == 1


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
