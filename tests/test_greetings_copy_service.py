from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.greetings_copy_service import (
    SUPPORTED_GREETINGS_EVENT_TYPES,
    GreetingsCopyService,
    format_greetings_event_label,
)


class _FakeDatabase:
    def __init__(self, *, occurrence_number: int = 1) -> None:
        self._occurrence_number = occurrence_number
        self.count_calls: list[tuple[str, str, str]] = []

    async def count_member_flow_events_for_user(self, guild_id: str, user_id: str, event_type_key: str) -> int:
        self.count_calls.append((guild_id, user_id, event_type_key))
        return self._occurrence_number


def _service(*, tmp_path=None, occurrence_number: int = 1, payload: dict | None = None) -> GreetingsCopyService:
    database = _FakeDatabase(occurrence_number=occurrence_number)
    config_path = None
    if tmp_path is not None and payload is not None:
        config_path = tmp_path / "greetings_trigger.test.json"
        config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    service = GreetingsCopyService(database, config_path=config_path)
    service._test_database = database  # type: ignore[attr-defined]
    return service


def test_format_greetings_event_label_covers_supported_keys() -> None:
    assert format_greetings_event_label("join", 1) == "🤝 __**PRIMA ENTRATA**__"
    assert format_greetings_event_label("leave", 1) == "👋 __**PRIMA USCITA**__"
    assert format_greetings_event_label("leave", 2) == "👋 __**RIUSCITA**__"
    assert format_greetings_event_label("kick", 1) == "👢 __**PRIMA ESPULSIONE**__"
    assert format_greetings_event_label("ban", 1) == "⛔ __**PRIMA INTERDIZIONE PERENNE**__"
    assert format_greetings_event_label("tempban", 1) == "⌛ __**PRIMA INTERDIZIONE TEMPORANEA**__"
    assert format_greetings_event_label("grace", 1) == "🕊️ __**PRIMA GRAZIA**__"
    assert format_greetings_event_label("inactive_kick", 1) == "👢 __**PRIMA ESPULSIONE**__"
    assert format_greetings_event_label("inactive_tempban", 1) == "⌛ __**PRIMA INTERDIZIONE TEMPORANEA**__"
    assert format_greetings_event_label("inactive_grace", 1) == "🕊️ __**PRIMA GRAZIA**__"
    assert "KICK" not in format_greetings_event_label("kick", 3)


def test_render_event_copy_uses_second_occurrence_for_ordinals() -> None:
    service = _service(occurrence_number=2)

    result = asyncio.run(
        service.render_event_copy(
            guild=SimpleNamespace(id=1, name="Barcellometro"),
            user=SimpleNamespace(id=42, name="new_user", display_name="New User", mention="<@42>"),
            event_type_key="leave",
            barcello_status={"color": "giallo", "score": 72},
            now=datetime(2026, 3, 21, 10, 0, tzinfo=timezone.utc),
        )
    )

    assert result.occurrence_number == 2
    assert result.event_label == "👋 __**RIUSCITA**__"
    assert service._test_database.count_calls == [("1", "42", "leave")]  # type: ignore[attr-defined]


def test_render_event_copy_counts_by_user_and_event_type_key_only() -> None:
    service = _service(occurrence_number=4)

    result = asyncio.run(
        service.render_event_copy(
            guild=SimpleNamespace(id=1, name="Barcellometro"),
            user=SimpleNamespace(id=99, name="new_user", display_name="New User", mention="<@99>"),
            event_type_key="kick",
            barcello_status={"color": "verde", "score": 84},
            now=datetime(2026, 3, 21, 10, 0, tzinfo=timezone.utc),
        )
    )

    assert result.occurrence_number == 4
    assert service._test_database.count_calls == [("1", "99", "kick")]  # type: ignore[attr-defined]


def test_first_join_narrative_is_welcome_and_uses_user_mention() -> None:
    service = _service()

    result = asyncio.run(
        service.render_event_copy(
            guild=SimpleNamespace(id=1, name="Barcellometro"),
            user=SimpleNamespace(id=42, name="new_user", display_name="New User", mention="<@42>"),
            event_type_key="join",
            barcello_status={"color": "verde", "score": 84},
            now=datetime(2026, 3, 21, 9, 0, tzinfo=timezone.utc),
        )
    )

    lowered = result.narrative.lower()
    assert "<@42>" in result.narrative
    assert "benvenut" in lowered
    assert "rientrat" not in lowered
    assert "torna" not in lowered


def test_second_join_narrative_can_use_reentry_language_and_uses_user_mention() -> None:
    service = _service(occurrence_number=2)

    result = asyncio.run(
        service.render_event_copy(
            guild=SimpleNamespace(id=1, name="Barcellometro"),
            user=SimpleNamespace(id=42, name="new_user", display_name="New User", mention="<@42>"),
            event_type_key="join",
            barcello_status={"color": "verde", "score": 84},
            now=datetime(2026, 3, 21, 9, 0, tzinfo=timezone.utc),
        )
    )

    lowered = result.narrative.lower()
    assert "<@42>" in result.narrative
    assert "torna" in lowered or "rientra" in lowered


def test_grace_manual_and_inactive_have_distinct_copy() -> None:
    service = _service()
    guild = SimpleNamespace(id=1, name="Barcellometro")
    user = SimpleNamespace(id=42, name="new_user", display_name="New User", mention="<@42>")

    grace = asyncio.run(
        service.render_event_copy(
            guild=guild,
            user=user,
            event_type_key="grace",
            duration_seconds=7 * 86400,
            barcello_status={"color": "verde", "score": 88},
            now=datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc),
        )
    )
    inactive_grace = asyncio.run(
        service.render_event_copy(
            guild=guild,
            user=user,
            event_type_key="inactive_grace",
            duration_seconds=7 * 86400,
            metadata={"inactivity_text": "30 giorni"},
            barcello_status={"color": "verde", "score": 88},
            now=datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc),
        )
    )

    assert grace.event_label == "🕊️ __**PRIMA GRAZIA**__"
    assert inactive_grace.event_label == "🕊️ __**PRIMA GRAZIA**__"
    assert "inattività" not in grace.narrative.lower()
    assert "inattività" in inactive_grace.narrative.lower()


def test_inactive_labels_stay_distinct_between_kick_and_tempban() -> None:
    assert format_greetings_event_label("inactive_kick", 1) != format_greetings_event_label("inactive_tempban", 1)


def test_render_event_copy_uses_mood_time_barcello_and_count_override(tmp_path) -> None:
    payload = {
        "mood_default": "teso",
        "time_buckets": {
            "morning": {"start": 6, "end": 12},
            "afternoon": {"start": 12, "end": 24},
        },
        "count_tiers": [
            {"min_occurrence": 1, "label": "t1"},
            {"min_occurrence": 2, "label": "t2"},
        ],
        "templates": {"kick": ["fallback {mood} {time_bucket} {barcello_color} {count_tier}"]},
        "moods": {
            "teso": {
                "time": {
                    "morning": {
                        "barcello": {
                            "rosso": {
                                "count": {
                                    "t2": {
                                        "templates": {
                                            "kick": [
                                                "override {mood} {time_bucket} {barcello_color} {count_tier} {barcello_alert} {barcello_score}"
                                            ]
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
    }
    service = _service(tmp_path=tmp_path, occurrence_number=2, payload=payload)

    result = asyncio.run(
        service.render_event_copy(
            guild=SimpleNamespace(id=1, name="Barcellometro"),
            user=SimpleNamespace(id=42, name="new_user", display_name="New User", mention="<@42>"),
            event_type_key="kick",
            barcello_status={"color": "rosso", "score": 41},
            now=datetime(2026, 3, 21, 8, 0, tzinfo=timezone.utc),
        )
    )

    assert result.mood == "teso"
    assert result.time_bucket == "morning"
    assert result.count_tier == "t2"
    assert result.barcello_state == "rosso"
    assert "override **teso** **morning** **rosso** **t2** **🔴 ALLERTA ROSSA** **41**" in result.narrative


def test_render_moderation_preview_renders_context_placeholders() -> None:
    service = _service()
    rendered, context = asyncio.run(
        service.render_moderation_preview(
            template="{occurrence_ordinal} {event_label_text} {mood} {time_bucket} {barcello_alert} {barcello_score_text}",
            event_type_key="tempban",
            user=SimpleNamespace(id=42, name="new_user", display_name="New User", mention="<@42>"),
            guild=SimpleNamespace(id=1, name="Barcellometro"),
            moderator=SimpleNamespace(id=7, name="Mod", display_name="Moderator", mention="<@7>"),
            duration_seconds=7 * 86400,
            occurrence_number=2,
            mood="teso",
            time_bucket="night",
            count_tier="t2",
            barcello_color="rosso",
            barcello_score=41,
        )
    )

    assert rendered == "**SECONDA** **INTERDIZIONE TEMPORANEA** **teso** **night** **🔴 ALLERTA ROSSA** **41/100**"
    assert context["moderator"] == "Moderator"


def test_render_event_copy_does_not_read_legacy_greetings_templates_from_database() -> None:
    class _NoLegacyTemplateDB(_FakeDatabase):
        async def get_moderation_templates(self, guild_id: str) -> dict[str, str]:  # pragma: no cover - must stay unused
            raise AssertionError("legacy greetings templates must not be read")

    service = GreetingsCopyService(_NoLegacyTemplateDB())

    result = asyncio.run(
        service.render_event_copy(
            guild=SimpleNamespace(id=1, name="Barcellometro"),
            user=SimpleNamespace(id=42, name="new_user", display_name="New User", mention="<@42>"),
            event_type_key="kick",
            barcello_status={"color": "verde", "score": 84},
            now=datetime(2026, 3, 21, 10, 0, tzinfo=timezone.utc),
        )
    )

    assert "<@42>" in result.narrative


def test_render_canonical_event_copy_reads_occurrence_and_inactivity_from_canonical_event() -> None:
    service = _service(occurrence_number=9)

    result = asyncio.run(
        service.render_canonical_event_copy(
            guild=SimpleNamespace(id=1, name="Barcellometro"),
            user=SimpleNamespace(id=42, name="new_user", display_name="New User", mention="<@42>"),
            canonical_event={
                "event_type_key": "inactive_tempban",
                "reason": "Assenza prolungata",
                "duration_seconds": 7 * 86400,
                "visible_in_greetings": True,
                "metadata": {
                    "inactivity_text": "30 giorni",
                    "occurrence_number": 3,
                },
            },
            barcello_status={"color": "rosso", "score": 41},
            now=datetime(2026, 3, 21, 8, 0, tzinfo=timezone.utc),
        )
    )

    assert result.occurrence_number == 3
    assert result.event_label == "⌛ __**ALTRA INTERDIZIONE TEMPORANEA**__"
    assert "30 giorni" in result.narrative


@pytest.mark.parametrize(
    ("event_type_key", "duration_seconds", "metadata"),
    [
        ("kick", None, None),
        ("ban", None, None),
        ("tempban", 7 * 86400, None),
        ("grace", 7 * 86400, None),
        ("inactive_kick", None, {"inactivity_text": "30 giorni"}),
        ("inactive_grace", 7 * 86400, {"inactivity_text": "30 giorni"}),
    ],
)
def test_render_event_copy_sets_moderation_note_for_supported_moderation_events(
    event_type_key: str,
    duration_seconds: int | None,
    metadata: dict | None,
) -> None:
    service = _service()

    result = asyncio.run(
        service.render_event_copy(
            guild=SimpleNamespace(id=1, name="Barcellometro"),
            user=SimpleNamespace(id=42, name="new_user", display_name="New User", mention="<@42>"),
            event_type_key=event_type_key,
            reason="Motivo test",
            duration_seconds=duration_seconds,
            metadata=metadata or {},
            barcello_status={"color": "rosso", "score": 41},
            now=datetime(2026, 3, 21, 8, 0, tzinfo=timezone.utc),
        )
    )

    assert result.moderation_note == "Motivo test"
    assert "Motivo test" not in result.narrative


def test_render_event_copy_inactive_tempban_hides_moderation_note_even_with_reason() -> None:
    service = _service()
    result = asyncio.run(
        service.render_event_copy(
            guild=SimpleNamespace(id=1, name="Barcellometro"),
            user=SimpleNamespace(id=42, name="new_user", display_name="New User", mention="<@42>"),
            event_type_key="inactive_tempban",
            reason="Motivo test",
            duration_seconds=7 * 86400,
            metadata={"inactivity_text": "30 giorni"},
            barcello_status={"color": "rosso", "score": 41},
            now=datetime(2026, 3, 21, 8, 0, tzinfo=timezone.utc),
        )
    )
    assert result.moderation_note is None
    assert "inattività" in result.narrative.lower()


def test_render_event_copy_skips_reason_block_when_reason_is_missing() -> None:
    service = _service()

    result = asyncio.run(
        service.render_event_copy(
            guild=SimpleNamespace(id=1, name="Barcellometro"),
            user=SimpleNamespace(id=42, name="new_user", display_name="New User", mention="<@42>"),
            event_type_key="kick",
            reason="   ",
            barcello_status={"color": "verde", "score": 84},
            now=datetime(2026, 3, 21, 10, 0, tzinfo=timezone.utc),
        )
    )

    assert result.moderation_note is None


def test_render_canonical_event_copy_prefers_metadata_greetings_reason_for_final_block() -> None:
    service = _service()

    result = asyncio.run(
        service.render_canonical_event_copy(
            guild=SimpleNamespace(id=1, name="Barcellometro"),
            user=SimpleNamespace(id=42, name="new_user", display_name="New User", mention="<@42>"),
            canonical_event={
                "event_type_key": "kick",
                "reason": "Motivo tecnico interno",
                "visible_in_greetings": True,
                "metadata": {
                    "occurrence_number": 1,
                    "greetings_reason": "Spam creativo",
                },
            },
            barcello_status={"color": "rosso", "score": 41},
            now=datetime(2026, 3, 21, 8, 0, tzinfo=timezone.utc),
        )
    )

    assert result.moderation_note == "Spam creativo"
    assert "Spam creativo" not in result.narrative
    assert "Motivo tecnico interno" not in result.narrative


def test_default_narrative_does_not_auto_duplicate_event_emoji() -> None:
    service = _service()

    result = asyncio.run(
        service.render_event_copy(
            guild=SimpleNamespace(id=1, name="Barcellometro"),
            user=SimpleNamespace(id=42, name="new_user", display_name="New User", mention="<@42>"),
            event_type_key="leave",
            barcello_status={"color": "giallo", "score": 72},
            now=datetime(2026, 3, 21, 10, 0, tzinfo=timezone.utc),
        )
    )

    assert "👋" not in result.narrative


def test_narrative_respects_fixed_slot_flow_and_markdown_emphasis() -> None:
    service = _service(occurrence_number=3)
    result = asyncio.run(
        service.render_event_copy(
            guild=SimpleNamespace(id=1, name="Barcellometro"),
            user=SimpleNamespace(id=42, name="new_user", display_name="New User", mention="<@42>"),
            event_type_key="ban",
            now=datetime(2026, 3, 21, 10, 0, tzinfo=timezone.utc),
        )
    )
    assert result.narrative.startswith("***<@42>***")
    assert not result.narrative.startswith(("🤝", "👋", "👢", "⛔", "⌛", "🕊️"))
    assert "***è stato bannato***" in result.narrative
    assert ". *" in result.narrative


def test_leave_includes_barcello_reference_only_for_leave() -> None:
    service = _service(occurrence_number=2)
    leave = asyncio.run(
        service.render_event_copy(
            guild=SimpleNamespace(id=1, name="Barcellometro"),
            user=SimpleNamespace(id=42, name="new_user", display_name="New User", mention="<@42>"),
            event_type_key="leave",
            barcello_status={"color": "giallo", "score": 58},
            now=datetime(2026, 3, 21, 10, 0, tzinfo=timezone.utc),
        )
    )
    ban = asyncio.run(
        service.render_event_copy(
            guild=SimpleNamespace(id=1, name="Barcellometro"),
            user=SimpleNamespace(id=42, name="new_user", display_name="New User", mention="<@42>"),
            event_type_key="ban",
            barcello_status={"color": "giallo", "score": 58},
            now=datetime(2026, 3, 21, 10, 0, tzinfo=timezone.utc),
        )
    )
    assert "ALLERTA GIALLA" in leave.narrative
    assert "ALLERTA GIALLA" not in ban.narrative


def test_example_config_loads_and_documents_core_placeholders() -> None:
    service = GreetingsCopyService(_FakeDatabase(), config_path="settings/greetings_trigger.example.json")
    cfg = service._load_cfg()  # type: ignore[attr-defined]

    placeholders = cfg["docs"]["placeholders"]
    for key in (
        "mention",
        "guild_name",
        "reason",
        "duration",
        "occurrence_ordinal",
        "barcello_alert",
        "barcello_score_text",
    ):
        assert key in placeholders


def test_example_config_has_fallbacks_for_every_supported_event() -> None:
    payload = json.loads(Path("settings/greetings_trigger.example.json").read_text(encoding="utf-8"))

    fallbacks = payload["defaults"]["fallbacks"]
    assert set(fallbacks) == SUPPORTED_GREETINGS_EVENT_TYPES
    for event_type_key in SUPPORTED_GREETINGS_EVENT_TYPES:
        template_group = fallbacks[event_type_key]
        assert isinstance(template_group, dict)
        assert any(template_group.get(name) for name in ("default", "first_occurrence", "repeat"))


def test_example_config_join_has_explicit_first_and_repeat_copy() -> None:
    payload = json.loads(Path("settings/greetings_trigger.example.json").read_text(encoding="utf-8"))

    join_templates = payload["event_templates"]["join"]
    assert join_templates["first_occurrence"]["opening"] == "{mention}"
    assert join_templates["repeat"]["opening"] == "{mention}"
    assert join_templates["first_occurrence"] != join_templates["repeat"]


def test_example_config_documents_json_as_single_editorial_source() -> None:
    payload = json.loads(Path("settings/greetings_trigger.example.json").read_text(encoding="utf-8"))

    purpose_lines = payload["docs"]["purpose"]
    assert any("Fonte ufficiale" in line for line in purpose_lines)
    assert any("struttura fissa" in line for line in purpose_lines)
    assert any("emoji + __**MAIUSCOLO**__" in line for line in purpose_lines)
    assert payload["docs"]["narrative_order"][0] == "opening"
    assert "solo leave" in payload["docs"]["narrative_order"][4]


def test_defaults_fallback_is_used_when_main_templates_are_missing(tmp_path) -> None:
    payload = {
        "templates": {"kick": []},
        "defaults": {
            "fallbacks": {
                "kick": {
                    "default": ["fallback kick {mention}"],
                },
            }
        },
    }
    service = _service(tmp_path=tmp_path, occurrence_number=2, payload=payload)

    result = asyncio.run(
        service.render_event_copy(
            guild=SimpleNamespace(id=1, name="Barcellometro"),
            user=SimpleNamespace(id=42, name="new_user", display_name="New User", mention="<@42>"),
            event_type_key="kick",
            barcello_status={"color": "verde", "score": 84},
            now=datetime(2026, 3, 21, 9, 0, tzinfo=timezone.utc),
        )
    )

    assert "fallback kick **<@42>**" in result.narrative


def test_render_moderation_preview_bolds_primary_dynamic_placeholders_without_breaking_mentions() -> None:
    service = _service()
    rendered, _ = asyncio.run(
        service.render_moderation_preview(
            template=(
                "{mention} / {display_name} / {username} / {guild_name} / {reason} / {duration} / "
                "{expires_at} / {barcello_state} / {barcello_score} / {mood} / {time_bucket}"
            ),
            event_type_key="tempban",
            user=SimpleNamespace(id=42, name="new_user", display_name="New User", mention="<@42>"),
            guild=SimpleNamespace(id=1, name="Barcellometro"),
            moderator=SimpleNamespace(id=7, name="Mod", display_name="Moderator", mention="<@7>"),
            reason="spam creativo",
            duration_seconds=7 * 86400,
            expires_at=datetime(2026, 3, 28, 8, 0, tzinfo=timezone.utc),
            occurrence_number=2,
            mood="teso",
            time_bucket="night",
            count_tier="t2",
            barcello_color="rosso",
            barcello_score=41,
        )
    )

    assert rendered == (
        "**<@42>** / **New User** / **new_user** / **Barcellometro** / **spam creativo** / **7g** / "
        "**28/03/2026 08:00 UTC** / **rosso** / **41** / **teso** / **night**"
    )


def test_render_moderation_preview_bolds_reason_suffix_but_keeps_prefix_outside_markdown() -> None:
    service = _service()
    rendered, _ = asyncio.run(
        service.render_moderation_preview(
            template="Motivo{reason_suffix}",
            event_type_key="kick",
            user=SimpleNamespace(id=42, name="new_user", display_name="New User", mention="<@42>"),
            guild=SimpleNamespace(id=1, name="Barcellometro"),
            moderator=SimpleNamespace(id=7, name="Mod", display_name="Moderator", mention="<@7>"),
            reason="spam creativo",
            occurrence_number=1,
            mood="teso",
            time_bucket="night",
            count_tier="t1",
            barcello_color="rosso",
            barcello_score=41,
        )
    )

    assert rendered == "Motivo: **spam creativo**"
