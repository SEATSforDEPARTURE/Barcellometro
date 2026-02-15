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
