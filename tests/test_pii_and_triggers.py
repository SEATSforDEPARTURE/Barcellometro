from datetime import datetime, timedelta
import sys
import types
from unittest.mock import Mock
from zoneinfo import ZoneInfo

if "discord" not in sys.modules:
    discord_stub = types.ModuleType("discord")
    discord_stub.Interaction = object
    discord_stub.Message = object
    discord_stub.Guild = object
    discord_stub.Member = object
    discord_stub.Client = object
    sys.modules["discord"] = discord_stub

if "aiosqlite" not in sys.modules:
    aiosqlite_stub = types.ModuleType("aiosqlite")
    aiosqlite_stub.Connection = object
    aiosqlite_stub.connect = object
    sys.modules["aiosqlite"] = aiosqlite_stub

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.AsyncOpenAI = object
    sys.modules["openai"] = openai_stub

from app.services.triggers import TriggerEngineService, is_out_of_scope_question, is_sensitive_question
from app.utils.pii import contains_pii, redact_pii


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


def test_qna_scope_and_sensitive_heuristics() -> None:
    assert is_out_of_scope_question("cosa dicono nel canale privato?")
    assert is_sensitive_question("qual è il numero di telefono?")


def test_infer_time_range_days_ago_is_single_day_window() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    start_dt, end_dt, label = service.infer_time_range("Cosa ha detto 2 giorni fa?")
    assert label == "2 giorni fa"
    assert end_dt - start_dt == timedelta(days=1)


def test_infer_time_range_altro_ieri_is_single_day_window() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    start_dt, end_dt, label = service.infer_time_range("Cosa ha detto l'altro ieri?")
    assert label == "l'altro ieri"
    assert end_dt - start_dt == timedelta(days=1)


def test_infer_time_range_hours_ago_window() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    start_dt, end_dt, label = service.infer_time_range("Cosa ha detto 3 ore fa?")
    assert label == "3 ore fa"
    assert end_dt - start_dt == timedelta(hours=3)




def test_infer_time_range_ieri_uses_full_previous_local_day() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    start_dt, end_dt, label = service.infer_time_range("Cosa ha detto ieri?")
    assert label == "ieri"

    rome = ZoneInfo("Europe/Rome")
    now_local = datetime.now(rome)
    today_start_local = datetime.combine(now_local.date(), datetime.min.time(), tzinfo=rome)
    expected_start = (today_start_local - timedelta(days=1)).astimezone(start_dt.tzinfo)
    expected_end = today_start_local.astimezone(end_dt.tzinfo)

    assert start_dt == expected_start
    assert end_dt == expected_end

def test_infer_time_range_mese_scorso_boundaries() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    start_dt, end_dt, label = service.infer_time_range("Cosa è successo mese scorso?")
    assert label == "mese scorso"

    rome = ZoneInfo("Europe/Rome")
    now_local = datetime.now(rome)
    current_month_start_local = datetime.combine(now_local.date().replace(day=1), datetime.min.time(), tzinfo=rome)
    prev_month_last_day = current_month_start_local - timedelta(days=1)
    prev_month_start_local = current_month_start_local.replace(year=prev_month_last_day.year, month=prev_month_last_day.month)

    assert start_dt == prev_month_start_local.astimezone(start_dt.tzinfo)
    assert end_dt == current_month_start_local.astimezone(end_dt.tzinfo)


def test_decorate_proof_links_formats_discord_jump_urls() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    answer = "- Punto [prova](https://discord.com/channels/1/2/3)"
    evidence = [
        {
            "jump_url": "https://discord.com/channels/1/2/3",
            "created_at_iso": "2026-02-14T19:00:00+00:00",
        }
    ]

    decorated = service._decorate_proof_links(answer, evidence)
    assert "[🧾 14/02 20:00](https://discord.com/channels/1/2/3)" in decorated


def test_decorate_proof_links_keeps_unknown_links() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    answer = "- Punto [prova](https://discord.com/channels/1/2/999)"
    evidence = [
        {
            "jump_url": "https://discord.com/channels/1/2/3",
            "created_at_iso": "2026-02-14T19:00:00+00:00",
        }
    ]

    decorated = service._decorate_proof_links(answer, evidence)
    assert decorated == answer


def test_decorate_proof_links_fixes_spaced_markdown_parentheses() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    answer = "Fonte: [🧾 14/02 14:26] (https://discord.com/channels/1/2/3)"
    evidence = [{"jump_url": "https://discord.com/channels/1/2/3", "created_at_iso": "2026-02-14T13:26:00+00:00"}]

    decorated = service._decorate_proof_links(answer, evidence)
    assert "[🧾 14/02 14:26](https://discord.com/channels/1/2/3)" in decorated


def test_decorate_proof_links_rewrites_naked_proof_url() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    answer = "prova (https://discord.com/channels/1/2/3)"
    evidence = [{"jump_url": "https://discord.com/channels/1/2/3", "created_at_iso": "2026-02-14T13:26:00+00:00"}]

    decorated = service._decorate_proof_links(answer, evidence)
    assert decorated == "[🧾 14/02 14:26](https://discord.com/channels/1/2/3)"


def test_decorate_proof_links_removes_broken_spacing_patterns() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    answer = "Test [🧾 14/02 14:26] ( https://discord.com/channels/1/2/3 )"
    evidence = [{"jump_url": "https://discord.com/channels/1/2/3", "created_at_iso": "2026-02-14T13:26:00+00:00"}]

    decorated = service._decorate_proof_links(answer, evidence)
    assert "] (http" not in decorated
    assert "]\n(http" not in decorated
    assert "[🧾 14/02 14:26](https://discord.com/channels/1/2/3)" in decorated


def test_decorate_proof_links_removes_newlines_and_spaces_inside_link_url() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    answer = "Fonte: [🧾 14/02 14:26](https://discord.com/channels/1/\n2/3 )"
    evidence = [{"jump_url": "https://discord.com/channels/1/2/3", "created_at_iso": "2026-02-14T13:26:00+00:00"}]

    decorated = service._decorate_proof_links(answer, evidence)
    assert "\n" not in decorated.split("(", 1)[1].split(")", 1)[0]
    assert "[🧾 14/02 14:26](https://discord.com/channels/1/2/3)" in decorated


def test_extract_target_speaker_raw() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    assert service._extract_target_speaker("è vero che Dany Sun ☀️ ha detto che potevo sfogarmi?") == "Dany Sun"


def test_bulletize_answer_filters_evidence_by_target_author() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
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

    out = service._bulletize_answer("è vero che Daniela ha detto che potevo sfogarmi?", answer, evidence)
    assert "https://discord.com/channels/1/2/4" in out
    assert "https://discord.com/channels/1/2/3" not in out


def test_bulletize_answer_returns_no_direct_evidence_when_target_missing() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    answer = "• Ha detto che potevi sfogarti."
    evidence = [
        {
            "message_id": "1",
            "channel_id": "2",
            "author_id": "10",
            "author_name": "Marco",
            "created_at_iso": "2026-02-14T13:00:00+00:00",
            "content": "messaggio non correlato a questa domanda",
            "jump_url": "https://discord.com/channels/1/2/3",
        }
    ]

    out = service._bulletize_answer("cosa ha detto Daniela?", answer, evidence)
    assert out == "Non ho trovato prove dirette di un messaggio di Daniela nel periodo richiesto."


def test_filter_evidence_by_target_matches_decorated_name() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    evidence = [
        {
            "author_name": "Dany Sun ☀️",
            "author_id": "11",
            "jump_url": "https://discord.com/channels/1/2/4",
            "created_at_iso": "2026-02-14T14:00:00+00:00",
            "content": "ti ho detto che potevi sfogarti quando eri giù",
        }
    ]

    filtered = service._filter_evidence_by_target(evidence, "Dany")
    assert len(filtered) == 1


def test_bulletize_answer_no_target_evidence_has_no_links() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    answer = "• Dicevano della live senza censura alle 20"
    evidence = [
        {
            "message_id": "1",
            "channel_id": "2",
            "author_id": "10",
            "author_name": "Marco",
            "created_at_iso": "2026-02-14T13:00:00+00:00",
            "content": "stasera live senza censura alle 20, si può sfogare tutto",
            "jump_url": "https://discord.com/channels/1/2/3",
        }
    ]

    out = service._bulletize_answer("è vero che Daniela ha detto live senza censura alle 20?", answer, evidence)
    assert out == "Non ho trovato prove dirette di un messaggio di Daniela nel periodo richiesto."
    assert "https://discord.com/channels/1/2/3" not in out


def test_render_barcello_transition_uses_first_today_template_and_new_placeholders() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    templates = {
        "GIALLO_FIRST_TODAY": "Prima volta oggi in {new}: #{state_count_today}",
        "ROSSO->GIALLO": "fallback {new}",
    }

    out = service._render_barcello_transition(
        "ROSSO",
        "GIALLO",
        70,
        50,
        templates=templates,
        first_today_for_new=True,
        extra_placeholders={"state_count_today": "1"},
    )
    assert out == "Prima volta oggi in GIALLO: #1"


def test_render_barcello_transition_falls_back_to_english_transition_key() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    templates = {"GREEN->YELLOW": "{old}->{new} {state_count_today} {last_in_state_human} {last_in_state_dt}"}

    out = service._render_barcello_transition(
        "VERDE",
        "GIALLO",
        10,
        20,
        templates=templates,
        extra_placeholders={
            "state_count_today": "2",
            "last_in_state_human": "3 ore",
            "last_in_state_dt": "16/02/2026 19:15",
        },
    )
    assert out == "VERDE->GIALLO 2 3 ore 16/02/2026 19:15"


def test_format_barcello_last_seen_helpers() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    now = datetime(2026, 2, 16, 19, 15, tzinfo=ZoneInfo("UTC"))

    assert service._format_barcello_last_seen_human(None, now) == "mai"
    assert service._format_barcello_last_seen_dt(None) == "mai"

    last_seen = "2026-02-16T18:15:00+00:00"
    assert service._format_barcello_last_seen_human(last_seen, now) == "60 minuti"
    assert service._format_barcello_last_seen_dt(last_seen) == "16/02/2026 19:15"
