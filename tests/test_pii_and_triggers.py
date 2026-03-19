from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from app.shared.safety.pii import contains_pii, redact_pii


@pytest.fixture
def triggers_module(import_fresh):
    return import_fresh("app.services.triggers")


def _service(triggers_module):
    return triggers_module.TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())


def test_redact_pii_email_phone() -> None:
    text, had = redact_pii("Scrivimi a mario@example.com o al +39 333 1234567")
    assert had is True
    assert "[REDACTED_EMAIL]" in text
    assert "[REDACTED_PHONE]" in text


def test_contains_pii() -> None:
    assert contains_pii("IT60X0542811101000000123456")


def test_discord_mentions_are_not_pii() -> None:
    assert contains_pii("ciao <@123456789012345678>") is False
    assert contains_pii("<#123456789012345678>") is False


def test_valid_credit_card_detected_and_redacted() -> None:
    card = "4111 1111 1111 1111"
    assert contains_pii(f"La carta è {card}") is True
    redacted, had = redact_pii(f"La carta è {card}")
    assert had is True
    assert "[REDACTED_CARD]" in redacted


def test_qna_scope_and_sensitive_heuristics(triggers_module) -> None:
    assert triggers_module.is_out_of_scope_question("cosa dicono nel canale privato?")
    assert triggers_module.is_sensitive_question("qual è il numero di telefono?")


def test_infer_time_range_days_ago_is_single_day_window(triggers_module) -> None:
    start_dt, end_dt, label = _service(triggers_module).infer_time_range("Cosa ha detto 2 giorni fa?")
    assert label == "2 giorni fa"
    assert end_dt - start_dt == timedelta(days=1)


def test_infer_time_range_altro_ieri_is_single_day_window(triggers_module) -> None:
    start_dt, end_dt, label = _service(triggers_module).infer_time_range("Cosa ha detto l'altro ieri?")
    assert label == "l'altro ieri"
    assert end_dt - start_dt == timedelta(days=1)


def test_infer_time_range_hours_ago_window(triggers_module) -> None:
    start_dt, end_dt, label = _service(triggers_module).infer_time_range("Cosa ha detto 3 ore fa?")
    assert label == "3 ore fa"
    assert end_dt - start_dt == timedelta(hours=3)


def test_infer_time_range_ieri_uses_full_previous_local_day(triggers_module) -> None:
    start_dt, end_dt, label = _service(triggers_module).infer_time_range("Cosa ha detto ieri?")
    assert label == "ieri"

    rome = ZoneInfo("Europe/Rome")
    now_local = datetime.now(rome)
    today_start_local = datetime.combine(now_local.date(), datetime.min.time(), tzinfo=rome)
    expected_start = (today_start_local - timedelta(days=1)).astimezone(start_dt.tzinfo)
    expected_end = today_start_local.astimezone(end_dt.tzinfo)

    assert start_dt == expected_start
    assert end_dt == expected_end


def test_infer_time_range_mese_scorso_boundaries(triggers_module) -> None:
    start_dt, end_dt, label = _service(triggers_module).infer_time_range("Cosa è successo mese scorso?")
    assert label == "mese scorso"

    rome = ZoneInfo("Europe/Rome")
    now_local = datetime.now(rome)
    current_month_start_local = datetime.combine(now_local.date().replace(day=1), datetime.min.time(), tzinfo=rome)
    prev_month_last_day = current_month_start_local - timedelta(days=1)
    prev_month_start_local = current_month_start_local.replace(year=prev_month_last_day.year, month=prev_month_last_day.month)

    assert start_dt == prev_month_start_local.astimezone(start_dt.tzinfo)
    assert end_dt == current_month_start_local.astimezone(end_dt.tzinfo)


def test_decorate_proof_links_formats_discord_jump_urls(triggers_module) -> None:
    answer = "- Punto [prova](https://discord.com/channels/1/2/3)"
    evidence = [{"jump_url": "https://discord.com/channels/1/2/3", "created_at_iso": "2026-02-14T19:00:00+00:00"}]

    decorated = _service(triggers_module)._decorate_proof_links(answer, evidence)
    assert "[🧾 14/02 20:00](https://discord.com/channels/1/2/3)" in decorated


def test_decorate_proof_links_keeps_unknown_links(triggers_module) -> None:
    answer = "- Punto [prova](https://discord.com/channels/1/2/999)"
    evidence = [{"jump_url": "https://discord.com/channels/1/2/3", "created_at_iso": "2026-02-14T19:00:00+00:00"}]

    decorated = _service(triggers_module)._decorate_proof_links(answer, evidence)
    assert decorated == answer


def test_decorate_proof_links_fixes_spaced_markdown_parentheses(triggers_module) -> None:
    answer = "Fonte: [🧾 14/02 14:26] (https://discord.com/channels/1/2/3)"
    evidence = [{"jump_url": "https://discord.com/channels/1/2/3", "created_at_iso": "2026-02-14T13:26:00+00:00", "content": "confermato", "author_name": "Luca", "author_id": "1"}]

    decorated = _service(triggers_module)._decorate_proof_links(answer, evidence)
    assert "[🧾 14/02 14:26](https://discord.com/channels/1/2/3)" in decorated


def test_decorate_proof_links_rewrites_naked_proof_url(triggers_module) -> None:
    answer = "prova (https://discord.com/channels/1/2/3)"
    evidence = [{"jump_url": "https://discord.com/channels/1/2/3", "created_at_iso": "2026-02-14T13:26:00+00:00", "content": "confermato", "author_name": "Luca", "author_id": "1"}]

    decorated = _service(triggers_module)._decorate_proof_links(answer, evidence)
    assert decorated == "[🧾 14/02 14:26](https://discord.com/channels/1/2/3)"


def test_decorate_proof_links_removes_broken_spacing_patterns(triggers_module) -> None:
    answer = "Test [🧾 14/02 14:26] ( https://discord.com/channels/1/2/3 )"
    evidence = [{"jump_url": "https://discord.com/channels/1/2/3", "created_at_iso": "2026-02-14T13:26:00+00:00", "content": "confermato", "author_name": "Luca", "author_id": "1"}]

    decorated = _service(triggers_module)._decorate_proof_links(answer, evidence)
    assert "] (http" not in decorated
    assert "]\n(http" not in decorated
    assert "[🧾 14/02 14:26](https://discord.com/channels/1/2/3)" in decorated


def test_decorate_proof_links_removes_newlines_and_spaces_inside_link_url(triggers_module) -> None:
    answer = "Fonte: [🧾 14/02 14:26](https://discord.com/channels/1/\n2/3 )"
    evidence = [{"jump_url": "https://discord.com/channels/1/2/3", "created_at_iso": "2026-02-14T13:26:00+00:00", "content": "confermato", "author_name": "Luca", "author_id": "1"}]

    decorated = _service(triggers_module)._decorate_proof_links(answer, evidence)
    assert "\n" not in decorated.split("(", 1)[1].split(")", 1)[0]
    assert "[🧾 14/02 14:26](https://discord.com/channels/1/2/3)" in decorated


def test_extract_target_speaker_raw(triggers_module) -> None:
    assert _service(triggers_module)._extract_target_speaker("è vero che Dany Sun ☀️ ha detto che potevo sfogarmi?") == "Dany Sun"


def test_bulletize_answer_filters_evidence_by_target_author(triggers_module) -> None:
    answer = "• Ha detto che potevi sfogarti quando eri giù."
    evidence = [
        {
            "message_id": "1",
            "channel_id": "2",
            "author_id": "10",
            "author_name": "Daniele",
            "created_at_iso": "2026-02-14T13:00:00+00:00",
            "content": "non c'entra niente",
            "jump_url": "https://discord.com/channels/1/2/3",
        },
        {
            "message_id": "2",
            "channel_id": "2",
            "author_id": "11",
            "author_name": "Daniela 🌸",
            "created_at_iso": "2026-02-14T14:00:00+00:00",
            "content": "ti ho detto che potevi sfogarti quando eri giù",
            "jump_url": "https://discord.com/channels/1/2/4",
        },
    ]

    out = _service(triggers_module)._bulletize_answer("è vero che Daniela ha detto che potevo sfogarmi?", answer, evidence)
    assert "https://discord.com/channels/1/2/4" in out
    assert "https://discord.com/channels/1/2/3" not in out
