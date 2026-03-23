from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.validate_commands import validate_command_tree


def test_command_validator_has_no_errors() -> None:
    result = validate_command_tree()

    assert [command.path for command in result.commands]
    assert result.errors == []


def test_command_validator_tracks_expected_alias_exceptions() -> None:
    result = validate_command_tree()

    expected = {
        "riassunto.oggi",
        "riassunto.ieri",
        "riassunto.ultimi",
        "riassunto.range",
        "resocontocanale.oggi",
        "resocontoserver.oggi",
    }
    assert expected.issubset(result.exceptions)
    assert any(command.path == "campaigns.prompt.schedule_add" for command in result.commands)
    assert any(command.path == "commandguard.role_list" for command in result.commands)
    assert any(command.path == "users.users.kick" for command in result.commands)
    assert all(not command.path.startswith("admin.") for command in result.commands)


def test_command_validator_tracks_embed_namespace_topology() -> None:
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
        "embed.author.on",
        "embed.author.off",
        "embed.author.status",
        "embed.author.template_global_set",
        "embed.author.template_global_show",
        "embed.author.template_global_reset",
        "embed.author.template_service_set",
        "embed.author.template_service_show",
        "embed.author.template_service_reset",
    }


def test_command_validator_tracks_expected_canonical_namespaces() -> None:
    result = validate_command_tree()

    command_paths = {command.path for command in result.commands}
    assert {
        "status",
        "campaigns.custom.run",
        "campaigns.prompt.schedule_show",
        "commandguard.role_list",
        "qna.bonus_show",
        "triggers.phrases.entry_list",
        "privacy.status",
        "greetings.backfill.run",
        "inactivity.run",
        "users.users.unban",
    }.issubset(command_paths)


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


def test_command_validator_has_no_legacy_tracking_fields() -> None:
    result = validate_command_tree()

    assert all(issue.code != "legacy_root" for issue in result.warnings)
