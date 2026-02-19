from __future__ import annotations

import sys
import types

if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(Row=dict, Connection=object)

from app.renderers.activity_dm_renderer import build_activity_dm_embeds
from app.services.activity_insights import ActivityScore, ChannelActivityDetails, UserActivityEntry


class _Member:
    def __init__(self, *, display_name: str | None = None, global_name: str | None = None, name: str | None = None) -> None:
        self.display_name = display_name
        self.global_name = global_name
        self.name = name


class _User:
    def __init__(self, *, global_name: str | None = None, name: str | None = None) -> None:
        self.global_name = global_name
        self.name = name


class _State:
    def __init__(self, cached: dict[int, _User]) -> None:
        self._cached = cached

    def get_user(self, user_id: int):
        return self._cached.get(user_id)


class _Guild:
    def __init__(self) -> None:
        self._members = {1: _Member(display_name="Nick Uno"), 2: _Member(global_name="Global Due", name="due")}
        self._state = _State({3: _User(global_name="Cached Tre", name="tre")})

    def get_member(self, user_id: int):
        return self._members.get(user_id)


def _entry(uid: int, count: int, last: bool = True) -> UserActivityEntry:
    return UserActivityEntry(
        user_id=uid,
        count_in_range=count,
        peak_count=1,
        peak_hour_ts="2026-01-20T10:58:00+00:00",
        peak_message_id="123456789012345678",
        peak_day_date_local="20/01",
        peak_day_count=2,
        last_ts_in_range="2026-01-20T10:58:00+00:00",
        last_message_id_in_range="123456789012345678",
        last_ts_channel="2026-01-20T10:58:00+00:00" if last else None,
        last_message_id_channel="123456789012345678" if last else None,
    )


def test_active_mentions_and_inactive_plain_names() -> None:
    details = ChannelActivityDetails(
        score=ActivityScore(10, 4, 10, 3, 55, "🟡", "MEDIOCRE", "Stabile"),
        top_active_users=[_entry(1, 5)],
        inactive_users=[_entry(2, 0), _entry(3, 0), _entry(9999, 0, last=False)],
        advice_bullets=["ok"],
        stats_lines=["• Messaggi: **10**", "• Utenti attivi: **4/7**"],
        range_spans_multiple_days=True,
        candidates_total=7,
    )

    embeds = build_activity_dm_embeds(_Guild(), "111", "222", "canale", "Oggi", details, reference_ts="2026-01-21T12:00:00+00:00")
    text = "\n".join(field.value for embed in embeds for field in embed.fields)
    assert "**<@1>**" in text
    inactive_field = next(field for embed in embeds for field in embed.fields if field.name == "💤 TOP 10 UTENTI INATTIVI")
    assert "<@" not in inactive_field.value
    assert "Global Due" in inactive_field.value
    assert "Cached Tre" in inactive_field.value
    assert "ID 9999" in inactive_field.value
    assert "Utenti attivi: **4/7**" in text
