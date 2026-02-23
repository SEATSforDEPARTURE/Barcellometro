from __future__ import annotations

from types import SimpleNamespace

from app.renderers.activity_daily_report_renderer import _format_italian_date, build_daily_activity_details_txt, build_daily_activity_embeds


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
    )


def _payloads() -> list[dict]:
    return [
        {
            "channel": SimpleNamespace(name="general", id=99),
            "details": _details(),
            "active_non_bot": 2,
            "members_with_access": 10,
            "inactive_non_bot": 8,
            "peak_hour": 21,
            "silence_hour": 5,
            "continuity_hours": 7,
            "is_voice": False,
            "voice_sessions_count": 0,
            "voice_total_seconds": 0,
            "voice_details": [],
            "active_lines": ["1) <@1> (Mario) (10 msg) | 💬 Ultimo: 20/02 10:00 🕒 1h fa | 🔥 Picco: 20/02 10:00 (4 msg)"],
            "inactive_lines": ["1) <@2> (Luigi) (0 msg) (mai partecipato dall'ingresso 🥀)"],
        }
    ]


def test_format_italian_date() -> None:
    assert _format_italian_date("2026-02-19T10:00:00+00:00") == "Giovedì, 19 Febbraio 2026"


def test_daily_renderer_embeds_include_silence_and_overview_sections() -> None:
    guild = _Guild()
    embeds = build_daily_activity_embeds(
        guild,
        "Test Server",
        _payloads(),
        server_summary={
            "active_non_bot": 3,
            "total_non_bot_members": 12,
            "inactive_non_bot": 9,
            "peak_hour": 22,
            "silence_hour": 4,
            "continuity_hours": 8,
            "label": "INTENSA",
            "score": 74,
            "trend_text": "Messaggi in crescita (+40% vs finestra precedente).",
            "window_end_local": "20:28",
            "global_active_rows": ["1) ..."],
            "global_inactive_rows": ["1) ..."],
        },
        reference_ts="2026-02-20T10:00:00+00:00",
    )

    assert "🗓️ Venerdì, 20 Febbraio 2026" in (embeds[0].description or "")
    first_names = [f.name for f in embeds[0].fields]
    assert "📈 TREND" in first_names
    stats_server = next(f.value for f in embeds[0].fields if f.name == "📌 STATISTICHE SERVER")
    assert "Ora di silenzio generale" in stats_server
    assert "Utenti attivi: **3/12 (25%)**" in stats_server
    channel_stats = next(f.value for f in embeds[1].fields if f.name == "📌 STATISTICHE CANALE")
    assert "Ora di silenzio" in channel_stats
    assert "Utenti attivi: **2/10 (20%)**" in channel_stats


def test_daily_renderer_txt_contains_required_headers_and_silence() -> None:
    guild = _Guild()
    txt = build_daily_activity_details_txt(
        guild,
        "Test Server",
        _payloads(),
        server_summary={
            "active_non_bot": 3,
            "total_non_bot_members": 12,
            "inactive_non_bot": 9,
            "peak_hour": 22,
            "silence_hour": 4,
            "continuity_hours": 8,
            "label": "INTENSA",
            "score": 74,
            "trend_text": "Messaggi in crescita (+40% vs finestra precedente).",
            "window_end_local": "20:28",
            "global_active_rows": ["1) <@1> ..."],
            "global_inactive_rows": ["1) <@2> ..."],
        },
        reference_ts="2026-02-20T10:00:00+00:00",
    )
    assert "RESOCONTO ATTIVITÀ SERVER —" in txt
    assert "Ora di silenzio generale" in txt
    assert "• Ora di silenzio:" in txt
