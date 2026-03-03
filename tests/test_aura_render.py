from app.services.aura_render import AuraRenderPayload, build_aura_embeds


def test_build_aura_embeds_respects_section_filter_and_page_limit() -> None:
    payload = AuraRenderPayload(
        period_label="01/01 00:00 → 01/01 23:59",
        karma_percent=72,
        metrics_json='{"msg_count": 10, "unique_interactions": 3, "reply_received": 4, "quality_counter": 2, "invigorate_events": 5, "degrade_events": 1}',
        ledger=[{"reason_code": "ondemand.aggregate", "total": 12}],
        archetype_metrics={"insights": ["Insight A", "Insight B"]},
    )

    embeds = build_aura_embeds(
        profile_name="base",
        aura_payload=payload,
        include_sections=["details.metrics_basic", "details.topics"],
        details_title_prefix="✨ Dettagli Aura",
        details_embeds_max=1,
    )

    assert len(embeds) == 2
    assert "RESOCONTO AURA" in (embeds[0].title or "")
    detail_values = "\n".join(field.value for field in embeds[1].fields)
    assert "Insight A" in detail_values
    assert "Volume" in detail_values
