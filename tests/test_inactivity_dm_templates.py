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
