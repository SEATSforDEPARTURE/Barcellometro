from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.validate_commands import validate_command_tree


def test_command_validator_has_no_errors() -> None:
    result = validate_command_tree()

    assert [command.path for command in result.commands]
    assert result.errors == []


def test_command_validator_tracks_expected_exceptions() -> None:
    result = validate_command_tree()

    assert "domanda" in result.exceptions
    assert "riassunto.oggi" in result.exceptions
    assert any(command.path == "campagne.prompt.schedule_add" for command in result.commands)
