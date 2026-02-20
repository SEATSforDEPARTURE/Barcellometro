from app.plugins.commands_modular.barcellometro_attivita import _validate_hhmm


def test_validate_hhmm_accepts_valid_value() -> None:
    assert _validate_hhmm("20:30") is None


def test_validate_hhmm_rejects_invalid_values() -> None:
    assert _validate_hhmm("25:00") is not None
    assert _validate_hhmm("ab:cd") is not None
    assert _validate_hhmm("9:00") is not None
