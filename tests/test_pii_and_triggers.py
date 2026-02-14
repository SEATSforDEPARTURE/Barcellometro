from app.services.triggers import is_out_of_scope_question, is_sensitive_question
from app.utils.pii import contains_pii, redact_pii


def test_redact_pii_email_phone() -> None:
    text, had = redact_pii("Scrivimi a mario@example.com o al +39 333 1234567")
    assert had is True
    assert "[REDACTED_EMAIL]" in text
    assert "[REDACTED_PHONE]" in text


def test_contains_pii() -> None:
    assert contains_pii("IT60X0542811101000000123456")


def test_qna_scope_and_sensitive_heuristics() -> None:
    assert is_out_of_scope_question("cosa dicono nel canale privato?")
    assert is_sensitive_question("qual è il numero di telefono?")
