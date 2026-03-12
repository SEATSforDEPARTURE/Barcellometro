from app.services.aura_archetypes import build_dynamic_archetype_reason
from app.services.aura_render import AuraRenderPayload, AuraTrendInfo, _build_missions, _build_profile_lines, _load_archetype_definitions, build_aura_embeds, render_karma_bar


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
        archetype_metrics={"scores": {"scintilla": 41, "pacificatore": 33, "collante": 26}},
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
                    "scintilla": {"label": "Catalizzatore", "emoji": "⚡", "profile_reason_template": "hai acceso il periodo"},
                    "pacificatore": {"label": "Mediatore", "emoji": "🕊️", "profile_reason_template": "hai calmato il periodo"},
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


def test_render_karma_bar_moves_marker_and_changes_color() -> None:
    negative = render_karma_bar(5)
    neutral = render_karma_bar(50)
    positive = render_karma_bar(95)

    assert "🔴" in negative
    assert negative.index("🔴") < neutral.index("🟡")
    assert "🟡" in neutral
    assert positive.endswith("😇")
    assert "🟢" in positive
    assert positive.index("🟢") > neutral.index("🟡")


def test_build_missions_orders_pending_before_completed_and_expired() -> None:
    assigned = [
        {"mission_id": "m_done", "status": "completed", "reward_points": 15, "meta": {"label": "Completata"}},
        {"mission_id": "m_open", "status": "assigned", "reward_points": 9, "meta": {"label": "Da fare"}},
        {"mission_id": "m_exp", "status": "expired", "reward_points": 5, "meta": {"label": "Scaduta"}},
    ]

    lines = _build_missions({"msg_count": 10}, {"scores": {}}, assigned)

    assert lines[0].startswith("⬜ Da fare")
    assert "✅ Completata" in lines[1]
    assert lines[2].startswith("⌛ Scaduta")


def test_load_archetype_definitions_returns_12_defaults() -> None:
    defs = _load_archetype_definitions()
    assert len(defs) >= 12
    for key in [
        "scintilla",
        "pacificatore",
        "agitatore",
        "collante",
        "mediatore",
        "esploratore_sociale",
        "costante",
        "lampo",
        "silenzioso",
        "ascoltatore",
        "selettivo",
        "dominante",
    ]:
        assert key in defs


def test_profile_lines_show_prominent_archetypes_with_emoji_percent_name_reason() -> None:
    lines = _build_profile_lines(
        {
            "scores": {"scintilla": 41, "pacificatore": 33, "collante": 26, "agitatore": 1},
            "metrics": {"first_message_of_day": 5, "unique_interactions": 9, "active_days": 15},
        },
        fallback_metrics={},
    )
    assert len(lines) == 3
    assert "✨ 41% Scintilla" in lines[0]
    assert "—" in lines[0]
    assert "🌿 33% Pacificatore" in lines[1]


def test_profile_lines_fallback_with_legacy_payload() -> None:
    lines = _build_profile_lines({"scores": {}}, fallback_metrics={"invigorate_events": 4, "degrade_events": 1})
    assert any("Agitatore" in line for line in lines)
    assert any("Pacificatore" in line for line in lines)


def test_build_aura_embeds_profile_section_uses_new_title() -> None:
    embeds = build_aura_embeds(
        profile_name="role2",
        aura_payload=_payload(),
        include_sections=["details.profile"],
        details_title_prefix="🗒️ DETTAGLI AURA",
        details_embeds_max=2,
        ledger_lines=["👍 **+5 P.A.** test"],
    )
    detail_text = "\n".join(field.name for emb in embeds[1:] for field in emb.fields)
    assert "TOP CARATTERISTICHE PROFILO PERSONALE" in detail_text


def test_build_aura_embeds_respects_profile_visibility_section() -> None:
    embeds = build_aura_embeds(
        profile_name="role1",
        aura_payload=_payload(),
        include_sections=["details.missions"],
        details_title_prefix="🗒️ DETTAGLI AURA",
        details_embeds_max=2,
        ledger_lines=["👍 **+5 P.A.** test"],
    )
    detail_text = "\n".join(field.name for emb in embeds[1:] for field in emb.fields)
    assert "TOP CARATTERISTICHE PROFILO PERSONALE" not in detail_text


def test_dynamic_reason_dominante_uses_high_monopoly_metrics() -> None:
    reason = build_dynamic_archetype_reason(
        "dominante",
        metrics={"msg_count": 80, "unique_interactions": 8, "channel_diversity": 2},
        scores={"dominante": 53},
        config={"profile_reason_template": "fallback dominante"},
    )
    assert "pochi spazi" in reason


def test_dynamic_reason_collante_uses_unique_and_channels() -> None:
    reason = build_dynamic_archetype_reason(
        "collante",
        metrics={"msg_count": 40, "unique_interactions": 12, "channel_diversity": 5, "replies_sent": 14},
        scores={"collante": 28},
        config={"profile_reason_template": "fallback collante"},
    )
    assert "più canali" in reason


def test_dynamic_reason_costante_uses_active_days_and_consistency() -> None:
    reason = build_dynamic_archetype_reason(
        "costante",
        metrics={"msg_count": 24, "active_days": 16, "daily_regularity": 0.72},
        scores={"costante": 31},
        config={"profile_reason_template": "fallback costante"},
    )
    assert "presenza costante e regolare" in reason


def test_dynamic_reason_silenzioso_uses_low_volume_non_zero_presence() -> None:
    reason = build_dynamic_archetype_reason(
        "silenzioso",
        metrics={"msg_count": 6, "active_days": 4, "unique_interactions": 4, "replies_sent": 1},
        scores={"silenzioso": 22},
        config={"profile_reason_template": "fallback silenzioso"},
    )
    assert "presenza discreta" in reason


def test_dynamic_reason_falls_back_to_template_when_metrics_are_insufficient() -> None:
    reason = build_dynamic_archetype_reason(
        "mediatore",
        metrics={"msg_count": 0},
        scores={"mediatore": 12},
        config={"profile_reason_template": "template statico"},
    )
    assert reason == "template statico"


def test_channel_aura_embed_top10_format_and_sections() -> None:
    from app.services.aura_render import ChannelAuraEmbedData, ChannelAuraMissionTrend, ChannelAuraTopUserItem, build_channel_aura_embed

    embed = build_channel_aura_embed(
        data=ChannelAuraEmbedData(
            positive_points=120,
            negative_points=-15,
            users_count=4,
            top_users=[ChannelAuraTopUserItem(user_id="42", score=1046, trend_emoji="⬆️", trend_comment="in crescita rispetto al periodo precedente", rank=1)],
            positive_reasons=[("per aver completato una missione giornaliera", 35)],
            negative_reasons=[("per bassa diversità nelle interazioni", -5)],
            missions=ChannelAuraMissionTrend(assigned_count=8, completed_count=6, trend_emoji="↔️", trend_comment="stabile rispetto al periodo precedente"),
            advice_lines=["Coinvolgete più persone nel canale."],
        )
    )

    fields = {f.name: f.value for f in embed.fields}
    assert "🏆 TOP 10 PUNTI AURA" in fields
    assert "**+1046 P.A.**" in fields["🏆 TOP 10 PUNTI AURA"]
    assert "<@42>" in fields["🏆 TOP 10 PUNTI AURA"]
    assert "🕹️ PUNTEGGI" in fields
    assert "**+35 P.A.**" in fields["🕹️ PUNTEGGI"]


def test_channel_aura_advice_is_deterministic() -> None:
    from app.services.aura_render import build_channel_aura_advice

    advice = build_channel_aura_advice(
        positive_points=0,
        negative_points=-60,
        users_count=1,
        mission_completed=0,
        top_positive_reason=None,
    )

    assert advice[0].startswith("Coinvolgete più persone")
    assert any("missioni" in line for line in advice)
