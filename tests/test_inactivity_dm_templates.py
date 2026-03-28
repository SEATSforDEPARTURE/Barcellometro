from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.inactivity_dm_templates import build_inactivity_dm_template_payload


def test_inactivity_template_payload_includes_utc_and_italian_time_variants() -> None:
    member = SimpleNamespace(id=42, mention="<@42>", name="user-42", display_name="Display 42")
    guild = SimpleNamespace(id=1, name="Barcellometro")
    now = datetime(2026, 3, 28, 16, 0, tzinfo=timezone.utc)
    expires_at = datetime(2026, 4, 4, 16, 0, tzinfo=timezone.utc)

    payload = build_inactivity_dm_template_payload(
        member=member,
        guild=guild,
        event_type="grace",
        days_inactive=39,
        policy={"window_days": 30, "min_messages": 1},
        cfg={"grace_days_after_reminder": 7, "ban_days": 7, "invite_url": "https://discord.gg/example"},
        now=now,
        expires_at=expires_at,
    )

    assert payload["now_utc"] == "2026-03-28 16:00 UTC"
    assert payload["now_it"] == "28/03/2026 17:00"
    assert payload["expires_at_utc"] == "2026-04-04 16:00 UTC"
    assert payload["expires_at_it"] == "04/04/2026 18:00"


def test_inactivity_payload_includes_reason_and_invite_line_aliases() -> None:
    member = SimpleNamespace(id=77, mention="<@77>", name="user-77", display_name="Display 77")
    guild = SimpleNamespace(id=9, name="Test Guild")

    payload = build_inactivity_dm_template_payload(
        member=member,
        guild=guild,
        event_type="tempban",
        days_inactive=80,
        policy={"window_days": 30, "min_messages": 1},
        cfg={"grace_days_after_reminder": 5, "ban_days": 3, "invite_url": "https://discord.gg/rejoin"},
        reason="Inattività prolungata",
        reasoning="inactivity_grace_expired_tempban",
        duration_seconds=259200,
        event_state="grace_expired",
        event_cause="inactivity",
    )

    assert payload["reason"] == "Inattività prolungata"
    assert payload["reason_text"] == "Inattività prolungata"
    assert payload["reason_line"] == "Reason: ***Inattività prolungata***. "
    assert payload["invite_url"] == "https://discord.gg/rejoin"
    assert payload["invite_line"] == "Invite: ***https://discord.gg/rejoin***"
    assert payload["rejoin_link"] == "https://discord.gg/rejoin"
    assert payload["duration_seconds"] == 259200
    assert payload["event_type"] == "tempban"
    assert payload["event_state"] == "grace_expired"
    assert payload["event_cause"] == "inactivity"
