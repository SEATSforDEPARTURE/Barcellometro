from __future__ import annotations

from app.renderers.activity_dm_renderer import build_activity_dm_embeds
from app.services.activity_insights import ActivityScore, ChannelActivityDetails, UserActivityEntry


def _entry(user_id: int, count: int, *, with_range_last: bool = True) -> UserActivityEntry:
    ts = "2026-01-20T10:58:00+00:00"
    msg_id = str(900000000000000000 + user_id)
    return UserActivityEntry(
        user_id=user_id,
        count_in_range=count,
        peak_count=max(0, count // 2),
        peak_hour_ts=ts,
        last_ts_in_range=ts if with_range_last else None,
        last_message_id_in_range=msg_id if with_range_last else None,
        last_ts_channel=ts,
        last_message_id_channel=msg_id,
    )


def test_build_activity_dm_embeds_respects_field_limits() -> None:
    top_users = [_entry(1000 + i, 100 - i, with_range_last=True) for i in range(20)]
    inactive = [_entry(2000 + i, 0 if i % 2 == 0 else 1, with_range_last=(i % 2 == 1)) for i in range(50)]
    advice = [
        "Consiglio molto lungo " + ("x" * 140) + f" #{i}"
        for i in range(20)
    ]

    details = ChannelActivityDetails(
        score=ActivityScore(
            messages_count=500,
            active_users_count=75,
            peak_hour_local=11,
            continuity_hours=18,
            score=72,
            emoji="🟢",
            label="INTENSA",
            trend_text="In crescita marcata rispetto al periodo precedente.",
        ),
        top_active_users=top_users,
        inactive_users=inactive,
        advice_bullets=advice,
        stats_lines=[
            "• Messaggi: **500**",
            "• Utenti attivi: **75**",
            "• Ora di picco: **11:00**",
            "• Continuità oraria: **18**",
        ],
    )

    embeds = build_activity_dm_embeds(
        "123456789",
        "987654321",
        "generale",
        "Ultimi 30 giorni",
        details,
        reference_ts="2026-01-21T12:00:00+00:00",
    )

    assert len(embeds) <= 5
    for embed in embeds:
        for field in embed.fields:
            assert len(field.value) <= 1024
