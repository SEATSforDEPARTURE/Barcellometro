from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.greetings_copy_service import GreetingsCopyService, format_greetings_event_label


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
    assert format_greetings_event_label("join", 1) == "**✨ PRIMO INGRESSO**"
    assert format_greetings_event_label("leave", 1) == "**👋 PRIMA USCITA**"
    assert format_greetings_event_label("leave", 2) == "**👋 SECONDA USCITA**"
    assert format_greetings_event_label("kick", 1) == "**🥾 PRIMO ALLONTANAMENTO**"
    assert format_greetings_event_label("ban", 1) == "**🔨 PRIMO BAN**"
    assert format_greetings_event_label("tempban", 1) == "**⏳ PRIMO BAN TEMPORANEO**"
    assert format_greetings_event_label("grace", 1) == "**🛟 PRIMO PERIODO DI GRAZIA**"
    assert format_greetings_event_label("inactive_kick", 1) == "**💤 PRIMO ALLONTANAMENTO PER INATTIVITÀ**"
    assert format_greetings_event_label("inactive_tempban", 1) == "**💤 PRIMO BAN TEMPORANEO PER INATTIVITÀ**"
    assert format_greetings_event_label("inactive_grace", 1) == "**🛟 PRIMO PERIODO DI GRAZIA PER INATTIVITÀ**"
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
    assert result.event_label == "**👋 SECONDA USCITA**"
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

    assert grace.event_label == "**🛟 PRIMO PERIODO DI GRAZIA**"
    assert inactive_grace.event_label == "**🛟 PRIMO PERIODO DI GRAZIA PER INATTIVITÀ**"
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
    assert result.narrative == "override teso morning rosso t2 🔴 ALLERTA ROSSA 41"


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

    assert rendered == "SECONDO BAN TEMPORANEO teso night 🔴 ALLERTA ROSSA 41/100"
    assert context["moderator"] == "Moderator"


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
    assert result.event_label == "**💤 TERZO BAN TEMPORANEO PER INATTIVITÀ**"
    assert "30 giorni" in result.narrative


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
