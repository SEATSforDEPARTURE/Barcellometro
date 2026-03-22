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
    assert any(
        command.path == "campagne.prompt.schedule_add" for command in result.commands
    )
    assert any(
        command.path == "greetings.backfill.on"
        and command.description == "Enable greetings timeline backfill."
        for command in result.commands
    )
    assert any(
        command.path == "greetings.backfill.off"
        and command.description == "Disable greetings timeline backfill."
        for command in result.commands
    )
    assert any(
        command.path == "greetings.backfill.status"
        and command.description == "Show greetings timeline backfill status."
        for command in result.commands
    )
    assert any(
        command.path == "greetings.backfill.run"
        and command.description == "Run greetings timeline backfill now."
        for command in result.commands
    )
    assert all(
        command.path
        not in {
            "greetings.template_set",
            "greetings.template_show",
            "greetings.template_reset",
        }
        for command in result.commands
    )
    assert "preview" not in {
        command.path.split(".")[-1]
        for command in result.commands
        if command.path.startswith("greetings.")
    }
    assert any(
        command.path == "mod.users.kick"
        and command.description == "Remove a user from the server."
        for command in result.commands
    )
    assert any(
        command.path == "mod.users.kick_list"
        and command.description == "List recent user removals."
        for command in result.commands
    )
    assert any(
        command.path == "mod.users.unban"
        and command.description == "Revoke an active ban for a user."
        for command in result.commands
    )


def test_command_validator_uses_admin_as_canonical_root() -> None:
    result = validate_command_tree()

    admin_paths = [
        command.path for command in result.commands if command.root == "admin"
    ]
    assert admin_paths
    assert "admin.status" in admin_paths
    assert set(command.root for command in result.commands if command.root == "admin")


def test_command_validator_tracks_embed_footer_topology() -> None:
    result = validate_command_tree()

    embed_paths = {command.path for command in result.commands if command.root == "embed"}
    assert embed_paths == {
        "embed.footer.on",
        "embed.footer.off",
        "embed.footer.status",
        "embed.footer.template_global_set",
        "embed.footer.template_global_show",
        "embed.footer.template_global_reset",
        "embed.footer.template_service_set",
        "embed.footer.template_service_show",
        "embed.footer.template_service_reset",
    }
    assert all(not command.path.startswith("admin.footer.") for command in result.commands)


def test_command_validator_tracks_top_level_legacy_barcello() -> None:
    result = validate_command_tree()

    assert any(command.path == "barcello" for command in result.commands)
    assert any(command.path == "admin.barcello.run" for command in result.commands)


def test_command_validator_has_no_legacy_tracking_fields() -> None:
    result = validate_command_tree()

    assert all(issue.code != "legacy_root" for issue in result.warnings)


def test_command_validator_tracks_exact_greetings_topology() -> None:
    result = validate_command_tree()

    greetings_paths = {
        command.path for command in result.commands if command.root == "greetings"
    }
    assert greetings_paths == {
        "greetings.backfill.on",
        "greetings.backfill.off",
        "greetings.backfill.status",
        "greetings.backfill.run",
        "greetings.notify_reset",
        "greetings.notify_set",
        "greetings.notify_show",
        "greetings.off",
        "greetings.on",
        "greetings.status",
        "greetings.user_card_reset",
        "greetings.user_card_set",
        "greetings.user_card_show",
    }
