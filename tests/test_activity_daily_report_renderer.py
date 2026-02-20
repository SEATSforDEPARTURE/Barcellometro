from __future__ import annotations

from types import SimpleNamespace

from app.renderers.activity_daily_report_renderer import _format_italian_date, build_daily_activity_embeds


class _Guild:
    def __init__(self) -> None:
        self.id = 1
        self._members = {
            1: SimpleNamespace(display_name="Mario"),
            2: SimpleNamespace(display_name="Luigi"),
        }

    def get_member(self, user_id: int):
        return self._members.get(user_id)


def _details() -> SimpleNamespace:
    score = SimpleNamespace(
        messages_count=30,
        active_users_count=2,
        peak_hour_local=12,
        continuity_hours=7,
        score=72,
        emoji="🟢",
        label="INTENSA",
        trend_text="Messaggi in crescita (+96% vs finestra precedente).",
    )
    return SimpleNamespace(
        score=score,
        top_active_users=[],
        inactive_users=[],
        advice_bullets=["Coinvolgere utenti nuovi"],
        stats_lines=["• Messaggi: 30"],
    )


def test_format_italian_date() -> None:
    assert _format_italian_date("2026-02-19T10:00:00+00:00") == "Giovedì, 19 Febbraio 2026"


def test_daily_renderer_short_channel_embeds_and_overview_sections() -> None:
    guild = _Guild()
    payloads = [
        {
            "channel": SimpleNamespace(name="general", id=99),
            "details": _details(),
            "active_non_bot": 2,
            "members_with_access": 10,
            "is_voice": False,
            "voice_sessions_count": 0,
            "voice_total_seconds": 0,
            "voice_details": [],
        },
        {
            "channel": SimpleNamespace(name="pascolo", id=100),
            "details": _details(),
            "active_non_bot": 1,
            "members_with_access": 8,
            "is_voice": True,
            "voice_sessions_count": 2,
            "voice_total_seconds": 5400,
            "voice_details": ["- 10:00 → 10:30 (30m)"],
        },
    ]

    embeds = build_daily_activity_embeds(
        guild,
        "Test Server",
        payloads,
        server_summary={"active_non_bot": 3, "total_non_bot_members": 12},
        reference_ts="2026-02-19T10:00:00+00:00",
    )

    assert "🗣️ RESOCONTO ATTIVITÀ" in (embeds[0].title or "")
    assert "🗓️ Giovedì, 19 Febbraio 2026" in (embeds[0].description or "")
    first_names = [f.name for f in embeds[0].fields]
    assert "📈 TREND" in first_names
    assert "💡 CONSIGLI" in first_names
    stats_server = next(f.value for f in embeds[0].fields if f.name == "📌 STATISTICHE SERVER")
    assert "Utenti attivi: **3/12**" in stats_server

    for emb in embeds[1:]:
        names = [f.name for f in emb.fields]
        assert not any("TOP 3" in n for n in names)
        assert not any("CONSIGLI" in n for n in names)

    voice_stats = next(f.value for f in embeds[2].fields if f.name == "📌 STATISTICHE CANALE")
    assert "Chiamate:" in voice_stats
