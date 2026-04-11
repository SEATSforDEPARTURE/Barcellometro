from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.shared.discord.embed_body import format_standard_field_name


@pytest.fixture
def renderer_module(import_fresh):
    return import_fresh("app.renderers.activity_report_renderer")


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
    return SimpleNamespace(score=score, top_active_users=[], inactive_users=[], advice_bullets=["Coinvolgere utenti nuovi"])


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


def test_format_italian_date(renderer_module) -> None:
    assert renderer_module._format_italian_date("2026-02-19T10:00:00+00:00") == "Giovedì, 19 Febbraio 2026"


def test_daily_renderer_embeds_include_silence_overview_channels_and_ordered_fields(renderer_module) -> None:
    guild = _Guild()
    embeds = renderer_module.build_daily_activity_embeds(
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
        period_label="oggi",
        window_start_dt=datetime(2026, 2, 20, 0, 0),
        window_end_dt=datetime(2026, 2, 20, 10, 0),
    )

    assert embeds[0].title == "🗣️ __**RESOCONTO SERVER · PANORAMICA**__"
    assert embeds[1].title == "🗣️ __**RESOCONTO SERVER · DETTAGLI CANALE**__"
    assert "general" not in embeds[1].title
    assert "#" not in embeds[1].title

    first_names = [f.name for f in embeds[0].fields]
    assert format_standard_field_name("PERIODO", emoji="🕒") not in first_names
    assert format_standard_field_name("TREND", emoji="📈") in first_names
    assert format_standard_field_name("STATISTICHE SERVER", emoji="📌") in first_names
    assert "📈 **TREND**" not in (embeds[0].description or "")
    assert "in crescita" not in (embeds[0].description or "").lower()
    assert "in calo" not in (embeds[0].description or "").lower()
    assert "stabile rispetto" not in (embeds[0].description or "").lower()
    assert "Messaggi in **crescita** (**+40%** vs finestra precedente)." in next(
        f.value for f in embeds[0].fields if f.name == format_standard_field_name("TREND", emoji="📈")
    )
    stats_server = next(f.value for f in embeds[0].fields if f.name == format_standard_field_name("STATISTICHE SERVER", emoji="📌"))
    assert "Ora di silenzio generale" in stats_server
    assert "Utenti attivi: **3/12 (25%)**" in stats_server
    channel_stats = next(f.value for f in embeds[1].fields if f.name == format_standard_field_name("STATISTICHE CANALE", emoji="📌"))
    assert "Ora di silenzio" in channel_stats
    assert "Utenti attivi: **2/10 (20%)**" in channel_stats
    channel_field_names = [f.name for f in embeds[1].fields]
    assert format_standard_field_name("TREND", emoji="📈") in channel_field_names
    assert format_standard_field_name("STATISTICHE CANALE", emoji="📌") in channel_field_names
    channel_desc = embeds[1].description or ""
    assert "in crescita" not in channel_desc.lower()
    assert "in calo" not in channel_desc.lower()
    assert "stabile rispetto" not in channel_desc.lower()
    trend_field_channel = next(f.value for f in embeds[1].fields if f.name == format_standard_field_name("TREND", emoji="📈"))
    assert "**" in trend_field_channel
    assert "Messaggi in **crescita** (**+96%** vs finestra precedente)." in trend_field_channel


def test_daily_renderer_txt_contains_required_headers_and_silence(renderer_module) -> None:
    guild = _Guild()
    txt = renderer_module.build_daily_activity_details_txt(
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
        period_label="ieri",
        window_start_dt=datetime(2026, 2, 19, 0, 0),
        window_end_dt=datetime(2026, 2, 20, 0, 0),
    )
    assert "RESOCONTO SERVER —" in txt
    assert "Periodo: 🗓️ Ieri. Giovedì, 19 Febbraio 2026" in txt
    assert "Ora di silenzio generale" in txt
    assert "• Ora di silenzio:" in txt


def test_daily_renderer_embeds_use_ultimi_window_header(renderer_module) -> None:
    embeds = renderer_module.build_daily_activity_embeds(
        _Guild(),
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
        period_label="ultimi",
        window_start_dt=datetime(2026, 3, 15, 19, 19),
        window_end_dt=datetime(2026, 3, 16, 15, 19),
    )

    description = embeds[0].description or ""
    assert "**Nelle ultime 20 ore**" in description
    assert "15/03/2026 19:19 → 16/03/2026 15:19" in description


def test_daily_renderer_embeds_use_range_window_header(renderer_module) -> None:
    embeds = renderer_module.build_daily_activity_embeds(
        _Guild(),
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
        period_label="range",
        window_start_dt=datetime(2026, 3, 10, 0, 0),
        window_end_dt=datetime(2026, 3, 12, 1, 0),
    )

    description = embeds[0].description or ""
    assert "**Periodo selezionato**" in description
    assert "10/03/2026 00:00 → 12/03/2026 01:00" in description


def test_daily_renderer_removes_stato_attivita_field_and_uses_narrative_italic_description(renderer_module) -> None:
    embeds = renderer_module.build_daily_activity_embeds(
        _Guild(),
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
        },
        period_label="ieri",
        window_start_dt=datetime(2026, 4, 10, 0, 0),
        window_end_dt=datetime(2026, 4, 11, 0, 0),
    )

    overview = embeds[0]
    overview_names = [field.name for field in overview.fields]
    assert format_standard_field_name("STATO ATTIVITÀ", emoji="🟢") not in overview_names
    assert overview.description and overview.description.startswith("*") and overview.description.endswith("*")
    assert "**Ieri. Venerdì, 10 Aprile 2026**" in overview.description
    assert "attività **intensa**" in overview.description
    assert "in crescita" not in overview.description.lower()

    channel = embeds[1]
    channel_names = [field.name for field in channel.fields]
    assert format_standard_field_name("STATO ATTIVITÀ", emoji="🟢") not in channel_names
    assert channel.description and channel.description.startswith("*") and channel.description.endswith("*")
    assert "**Ieri. Venerdì, 10 Aprile 2026**" in channel.description
    assert "#general ha mostrato un'attività **intensa**" in channel.description
    assert "in crescita" not in channel.description.lower()
