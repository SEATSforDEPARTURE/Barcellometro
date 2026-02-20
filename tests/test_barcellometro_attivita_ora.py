from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "app/plugins/commands_modular/barcellometro_attivita_logic.py"
spec = importlib.util.spec_from_file_location("barcellometro_attivita_logic", MODULE_PATH)
logic = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(logic)


def test_validate_hhmm_accepts_valid_value() -> None:
    assert logic.validate_hhmm("20:30") is None


def test_validate_hhmm_rejects_invalid_values() -> None:
    assert logic.validate_hhmm("25:00") is not None
    assert logic.validate_hhmm("ab:cd") is not None
    assert logic.validate_hhmm("9:00") is not None
