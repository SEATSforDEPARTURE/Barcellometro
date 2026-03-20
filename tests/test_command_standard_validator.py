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


def test_command_validator_uses_admin_as_canonical_root() -> None:
    result = validate_command_tree()

    admin_paths = [command.path for command in result.commands if command.root == "admin"]
    assert admin_paths
    assert "admin.status" in admin_paths
    assert not any(command.root == "bm" for command in result.commands)


def test_command_validator_tracks_bm_aliases_as_legacy_only() -> None:
    result = validate_command_tree()

    legacy_messages = [issue.message for issue in result.legacy_aliases]
    assert any("bm." in message for message in legacy_messages)
