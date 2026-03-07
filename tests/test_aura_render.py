from app.services.aura_render import AuraRenderPayload, AuraTrendInfo, build_aura_embeds


def _payload() -> AuraRenderPayload:
    return AuraRenderPayload(
        username="Mario",
        server_name="Barcellometro",
        channel_name="generale",
        period_line="Ultime 24 ore 01/01/2026 00:00 → 01/01/2026 23:59",
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


def test_first_embed_format_period_no_percent_and_no_extra_text() -> None:
    embeds = build_aura_embeds(
        profile_name="role1",
        aura_payload=_payload(),
        include_sections=["details.missions", "details.note.role1"],
        details_title_prefix="🗒️ DETTAGLI AURA",
        details_embeds_max=2,
        ledger_lines=["👍 **+5 P.A.** test"],
    )
    main = embeds[0]
    assert len(main.fields) == 0
    assert "**🕒 Ultime 24 ore 01/01/2026 00:00 → 01/01/2026 23:59**" in (main.description or "")
    assert "**✨ KARMA \"Barcellometro\"**" in (main.description or "")
    assert "PUNTI AURA TOTALI: **120**" in (main.description or "")
    assert "PUNTI AURA CANALE: **35**" in (main.description or "")
    assert "😇 70%" not in (main.description or "")
    assert "Questi punti" not in (main.description or "")
def test_build_aura_embeds_mod_placeholder_for_metrics() -> None:
    embeds = build_aura_embeds(
        profile_name="mod",
        aura_payload=_payload(),
        include_sections=["details.metrics_aggregated"],
        details_title_prefix="🗒️ DETTAGLI AURA",
        details_embeds_max=2,
        ledger_lines=["👍 **+5 P.A.** test"],
    )
    detail_text = "\n".join(field.value for emb in embeds[1:] for field in emb.fields)
    assert "Dettagli completi nel file allegato." in detail_text


def test_build_aura_embeds_missions_can_be_empty_for_today() -> None:
    payload = _payload()
    payload.metrics_json = '{"msg_count": 0, "unique_interactions": 0, "reply_received": 0, "quality_counter": 0, "invigorate_events": 0, "degrade_events": 0}'
    embeds = build_aura_embeds(
        profile_name="role1",
        aura_payload=payload,
        include_sections=["details.missions"],
        details_title_prefix="🗒️ DETTAGLI AURA",
        details_embeds_max=1,
        ledger_lines=["👍 **+5 P.A.** test"],
    )
    detail_values = "\n".join(field.value for field in embeds[1].fields)
    assert "Nessuna per oggi" in detail_values


def test_build_aura_embeds_uses_custom_archetypes_and_missions_config(monkeypatch) -> None:
    payload = _payload()

    def _fake_loader(path: str):
        if path.endswith("aura_archetypes.json") or path.endswith("aura_archetypes.example.json"):
            return {
                "archetypes": {
                    "agitatore": {"label": "Catalizzatore", "emoji": "⚡", "description": "spingi il ritmo"},
                    "pacificatore": {"label": "Mediatore", "emoji": "🕊️", "description": "abbassi i toni"},
                },
                "default_advice": ["Consiglio custom 1", "Consiglio custom 2"],
            }
        if path.endswith("aura_missions.json") or path.endswith("aura_missions.example.json"):
            return {
                "max_per_day": 2,
                "missions": [
                    {"text": "Missione custom A", "bonus_points": 11, "condition": "always", "enabled": True},
                    {"text": "Missione custom B", "bonus_points": 7, "condition": "always", "enabled": True},
                ],
            }
        return {}

    monkeypatch.setattr("app.services.aura_render.load_json_file", _fake_loader)

    embeds = build_aura_embeds(
        profile_name="role3",
        aura_payload=payload,
        include_sections=["details.profile", "details.missions", "details.advice"],
        details_title_prefix="🗒️ DETTAGLI AURA",
        details_embeds_max=2,
        ledger_lines=["👍 **+5 P.A.** test"],
    )
    detail_text = "\n".join(field.value for emb in embeds[1:] for field in emb.fields)
    assert "Catalizzatore" in detail_text
    assert "Missione custom A" in detail_text
    assert "Consiglio custom 1" in detail_text


def test_scores_section_can_skip_aggregate_lines() -> None:
    embeds = build_aura_embeds(
        profile_name="role1",
        aura_payload=_payload(),
        include_sections=["details.missions"],
        details_title_prefix="🗒️ DETTAGLI AURA",
        details_embeds_max=1,
        ledger_lines=["Nessun evento aura dettagliato registrato nel periodo."],
    )
    detail_text = "\n".join(field.value for field in embeds[1].fields)
    assert "Nessun evento aura dettagliato registrato nel periodo." in detail_text


def test_mod_points_timeline_section_present() -> None:
    payload = _payload()
    payload.points_timeline_lines = ["**[07/03 08:00](https://discord.com/channels/1/2/3) — 😇 +12 P.A.** - Per aver scritto il primo buongiorno del server."]
    embeds = build_aura_embeds(
        profile_name="mod",
        aura_payload=payload,
        include_sections=["details.points_timeline"],
        details_title_prefix="🗒️ DETTAGLI AURA",
        details_embeds_max=1,
        ledger_lines=["👍 **+1 P.A.** test"],
    )
    names = [f.name for f in embeds[1].fields]
    assert any("BREAKDOWN PUNTI" in n for n in names)


def test_scores_section_uses_single_bullet_and_keeps_bold_delta() -> None:
    embeds = build_aura_embeds(
        profile_name="role1",
        aura_payload=_payload(),
        include_sections=["details.missions"],
        details_title_prefix="🗒️ DETTAGLI AURA",
        details_embeds_max=1,
        ledger_lines=["👍 **+15 P.A.** per aver completato una missione giornaliera in #pollaio."],
    )
    detail_text = "\n".join(field.value for field in embeds[1].fields)
    assert "• 👍 **+15 P.A.** per aver completato una missione giornaliera in #pollaio." in detail_text
    assert "• •" not in detail_text
