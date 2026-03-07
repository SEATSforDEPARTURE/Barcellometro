from app.services.aura_render import AuraRenderPayload, AuraTrendInfo, build_aura_embeds


def _payload() -> AuraRenderPayload:
    return AuraRenderPayload(
        username="Mario",
        server_name="Barcellometro",
        channel_name="generale",
        period_row="01/01/2026 00:00 → 01/01/2026 23:59",
        period_label="Ultime 24 ore",
        karma_server_percent=72,
        karma_channel_percent=61,
        server_points_total=120,
        channel_points_month=35,
        metrics_json='{"msg_count": 10, "unique_interactions": 3, "reply_received": 4, "quality_counter": 2, "invigorate_events": 5, "degrade_events": 1}',
        channel_metrics_json='{"msg_count": 3, "unique_interactions": 2, "reply_received": 1, "quality_counter": 1, "invigorate_events": 1, "degrade_events": 0}',
        ledger=[{"reason_code": "ondemand.aggregate", "total": 12}],
        archetype_metrics={"scores": {"climate_impact": 56}},
        trend=AuraTrendInfo(
            server_direction="improving",
            server_comment="Trend positivo.",
            channel_direction="stable",
            channel_comment="Trend stabile.",
            server_delta=2,
            channel_delta=0,
        ),
    )


def test_build_aura_embeds_role1_sections_and_pagination() -> None:
    embeds = build_aura_embeds(
        profile_name="role1",
        aura_payload=_payload(),
        include_sections=["details.missions", "details.note.role1"],
        details_title_prefix="🗒️ DETTAGLI AURA",
        details_embeds_max=2,
    )

    assert len(embeds) >= 2
    assert "RESOCONTO AURA" in (embeds[0].title or "")
    detail_title = embeds[1].title or ""
    assert "PLUS" in detail_title
    values = "\n".join(field.value for field in embeds[1].fields)
    assert "MISSIONI" in "\n".join(field.name for field in embeds[1].fields)
    assert "abbonati" in values.lower()


def test_build_aura_embeds_mod_includes_aggregated_metrics() -> None:
    embeds = build_aura_embeds(
        profile_name="mod",
        aura_payload=_payload(),
        include_sections=["details.missions", "details.profile", "details.advice", "details.metrics_aggregated"],
        details_title_prefix="🗒️ DETTAGLI AURA",
        details_embeds_max=3,
    )

    assert len(embeds) >= 2
    detail_text = "\n".join(field.value for emb in embeds[1:] for field in emb.fields)
    assert "volume messaggi" in detail_text
    assert "trend precedente vs attuale" in detail_text


def test_build_aura_embeds_missions_can_be_empty_for_today() -> None:
    payload = _payload()
    payload.metrics_json = '{"msg_count": 0, "unique_interactions": 0, "reply_received": 0, "quality_counter": 0, "invigorate_events": 0, "degrade_events": 0}'
    embeds = build_aura_embeds(
        profile_name="role1",
        aura_payload=payload,
        include_sections=["details.missions"],
        details_title_prefix="🗒️ DETTAGLI AURA",
        details_embeds_max=1,
    )
    detail_values = "\n".join(field.value for field in embeds[1].fields)
    assert "Nessuna per oggi" in detail_values
