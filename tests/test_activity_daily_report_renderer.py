from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.renderers.activity_daily_report_renderer import build_daily_activity_embeds
from app.services.activity_insights import ActivityScore, ChannelActivityDetails, UserActivityEntry


class _Guild:
    def __init__(self) -> None:
        self.id = 1
        self._members = {
            1: SimpleNamespace(display_name="Mario"),
            2: SimpleNamespace(display_name="Luigi"),
            3: SimpleNamespace(display_name="Peach"),
            4: SimpleNamespace(display_name="Toad"),
        }

    def get_member(self, user_id: int):
        return self._members.get(user_id)


def _user(user_id: int, count: int, last_ts: str | None) -> UserActivityEntry:
    return UserActivityEntry(
        user_id=user_id,
        count_in_range=count,
        peak_count=max(1, count // 2),
        peak_hour_ts="2026-01-01T10:00:00+00:00",
        peak_message_id=None,
        peak_day_date_local=None,
        peak_day_count=0,
        last_ts_in_range=last_ts,
        last_message_id_in_range=None,
        last_ts_channel=last_ts,
        last_message_id_channel=None,
    )


def test_daily_renderer_top3_and_discord_timestamps() -> None:
    guild = _Guild()
    ts = datetime.now(timezone.utc).isoformat()
    details = ChannelActivityDetails(
        score=ActivityScore(30, 10, 12, 7, 72, "🟢", "INTENSA", "Messaggi in crescita (+96% vs finestra precedente)."),
        top_active_users=[_user(1, 50, ts), _user(2, 40, ts), _user(3, 20, ts), _user(4, 10, ts)],
        inactive_users=[_user(4, 0, ts), _user(3, 0, ts), _user(2, 0, None), _user(1, 0, None)],
        advice_bullets=["Coinvolgere utenti nuovi"],
        stats_lines=["• Messaggi: 30"],
        range_spans_multiple_days=False,
        candidates_total=12,
    )
    channel = SimpleNamespace(name="general", id=99)

    embeds = build_daily_activity_embeds(guild, "Test Server", [(channel, details)], reference_ts=ts)

    assert "🗣️ RESOCONTO ATTIVITÀ" in (embeds[0].title or "")
    channel_embed = embeds[1]
    field_names = [f.name for f in channel_embed.fields]
    assert any("🏆 TOP 3" in name for name in field_names)
    assert not any("TOP 10" in name for name in field_names)
    top_field = next(f for f in channel_embed.fields if "TOP 3" in f.name)
    assert "<t:" in top_field.value
    assert ":R>" in top_field.value
    assert "… + altri" in top_field.value
