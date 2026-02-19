from __future__ import annotations

import sys
import types

if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(Row=dict, Connection=object)

from app.renderers.activity_dm_renderer import build_activity_details_txt, build_activity_dm_embeds
from app.services.activity_insights import ActivityScore, ChannelActivityDetails, UserActivityEntry


class _Member:
    def __init__(self, display_name: str) -> None:
        self.display_name = display_name
        self.global_name = None
        self.name = display_name


class _State:
    def get_user(self, user_id: int):
        return None


class _Guild:
    def __init__(self) -> None:
        self._state = _State()

    def get_member(self, user_id: int):
        return _Member(f"User {user_id}")


def _entry(user_id: int, count: int, *, with_range_last: bool = True) -> UserActivityEntry:
    ts = "2026-01-20T10:58:00+00:00"
    msg_id = str(900000000000000000 + user_id)
    return UserActivityEntry(
        user_id=user_id,
        count_in_range=count,
        peak_count=max(0, count // 2),
        peak_hour_ts=ts,
        peak_message_id=msg_id,
        peak_day_date_local="20/01",
        peak_day_count=max(1, count // 3),
        last_ts_in_range=ts if with_range_last else None,
        last_message_id_in_range=msg_id if with_range_last else None,
        last_ts_channel=ts if with_range_last else None,
        last_message_id_channel=msg_id if with_range_last else None,
    )


def test_dm_layout_limits_and_formatting() -> None:
    top_users = [_entry(1000 + i, 100 - i, with_range_last=True) for i in range(20)]
    inactive = [_entry(2000 + i, 0, with_range_last=(i % 2 == 1)) for i in range(50)]
    advice = ["Consiglio molto lungo " + ("x" * 140) + f" #{i}" for i in range(20)]

    details = ChannelActivityDetails(
        score=ActivityScore(500, 75, 11, 18, 72, "🟢", "INTENSA", "In crescita marcata rispetto al periodo precedente."),
        top_active_users=top_users,
        inactive_users=inactive,
        advice_bullets=advice,
        stats_lines=["• Messaggi: **500**", "• Utenti attivi: **75/120**", "• Ora di picco: **11:00**", "• Continuità oraria: **18**"],
        range_spans_multiple_days=True,
        candidates_total=120,
    )

    embeds = build_activity_dm_embeds(_Guild(), "123456789", "987654321", "generale", "Ultimi 30 giorni", details, reference_ts="2026-01-21T12:00:00+00:00")

    combined = "\n".join(field.value for embed in embeds for field in embed.fields)
    assert "**<@1000>**" in combined
    assert "(**100 msg**)" in combined
    names = "\n".join(field.name for e in embeds for field in e.fields)
    assert "🏆 TOP 10 UTENTI PIÙ ATTIVI" in names
    assert "💤 TOP 10 UTENTI INATTIVI" in names
    assert "🥇" in combined and "🥈" in combined and "🥉" in combined and "4️⃣" in combined
    assert "\n  🔥 Picco:" in combined
    assert "(**0 msg**)" in combined
    assert "🥀" in combined
    assert "[20/01" in combined and "](https://discord.com/channels/" in combined
    active_field = next(field for e in embeds for field in e.fields if field.name == "🏆 TOP 10 UTENTI PIÙ ATTIVI")
    assert active_field.value.startswith("\n")
    assert "<@" in active_field.value
    inactive_field = next(field for e in embeds for field in e.fields if field.name == "💤 TOP 10 UTENTI INATTIVI")
    assert inactive_field.value.startswith("\n")
    assert "<@" not in inactive_field.value
    for block in [b for b in active_field.value.split("\n\n") if b.strip() and not b.startswith("… + altri")]:
        assert "\n" in block
    for embed in embeds:
        for field in embed.fields:
            assert len(field.value) <= 1024


def test_section_titles_not_numbered_when_chunked() -> None:
    top_users = [_entry(3000 + i, 100 - i, with_range_last=True) for i in range(20)]
    inactive = [_entry(4000 + i, 0, with_range_last=(i % 3 == 0)) for i in range(50)]
    details = ChannelActivityDetails(
        score=ActivityScore(500, 75, 11, 18, 72, "🟢", "INTENSA", "Trend"),
        top_active_users=top_users,
        inactive_users=inactive,
        advice_bullets=["ok"],
        stats_lines=["• Messaggi: **500**", "• Utenti attivi: **75/120**"],
        range_spans_multiple_days=True,
        candidates_total=120,
    )
    embeds = build_activity_dm_embeds(_Guild(), "123", "456", "g", "range", details, reference_ts="2026-01-21T12:00:00+00:00")
    field_names = [f.name for e in embeds for f in e.fields]
    assert "🏆 TOP 10 UTENTI PIÙ ATTIVI" in field_names
    assert "💤 TOP 10 UTENTI INATTIVI" in field_names
    assert not any("(" in name for name in field_names)
    assert "​" in field_names


def test_txt_is_numbered_and_shows_totals() -> None:
    details = ChannelActivityDetails(
        score=ActivityScore(120, 2, 11, 5, 62, "🟢", "INTENSA", "Trend"),
        top_active_users=[_entry(10, 9, with_range_last=True), _entry(11, 7, with_range_last=True)],
        inactive_users=[_entry(20, 0, with_range_last=False), _entry(21, 0, with_range_last=True)],
        advice_bullets=["ok"],
        stats_lines=["• Messaggi: **120**", "• Utenti attivi: **2/4**"],
        range_spans_multiple_days=True,
        candidates_total=4,
    )
    txt = build_activity_details_txt(
        _Guild(),
        "Guild",
        "123",
        "general",
        "456",
        "Ultimi 7 giorni",
        "2026-01-14T00:00:00+00:00",
        "2026-01-21T00:00:00+00:00",
        details,
        reference_ts="2026-01-21T12:00:00+00:00",
    )
    assert "SEZIONE A — TOP ATTIVI (2 attivi su 4 utenti totali)" in txt
    assert "SEZIONE B — INATTIVI NEL PERIODO (2 inattivi su 4 utenti totali)" in txt
    assert "\n1. <@10>" in txt
    assert "\n2. <@11>" in txt
    assert "\n1. <@20>" in txt
    assert "\n2. <@21>" in txt
