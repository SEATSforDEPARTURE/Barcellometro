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
        "resocontocanale.oggi",
        "resocontoserver.oggi",
        "dmchannelsummary.barcello.last",
        "users.unban.oggi",
        "users.untempban.oggi",
        "users.ungrace.oggi",
    }
    assert expected.issubset(result.exceptions)
    assert any(command.path == "campaigns.prompt.schedule_add" for command in result.commands)
    assert any(command.path == "commandguard.role_list" for command in result.commands)
    assert any(command.path == "users.kick" for command in result.commands)
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
        "embed.images.on",
        "embed.images.off",
        "embed.images.status",
        "embed.images.template_global_set",
        "embed.images.template_global_show",
        "embed.images.template_global_reset",
        "embed.images.template_service_set",
        "embed.images.template_service_show",
        "embed.images.template_service_reset",
        "embed.description.on",
        "embed.description.off",
        "embed.description.status",
        "embed.description.template_service_set",
        "embed.description.template_service_show",
        "embed.description.template_service_reset",
    }


def test_command_validator_tracks_expected_canonical_namespaces() -> None:
    result = validate_command_tree()

    command_paths = {command.path for command in result.commands}
    assert {
        "status.show",
        "campaigns.custom.run",
        "campaigns.prompt.schedule_show",
        "commandguard.role_list",
        "qna.bonus_show",
        "triggers.phrases.entry_list",
        "privacy.status",
        "database.backfill.run",
        "database.retention.limits_show",
        "greetings.backfill.run",
        "ai.model_reset",
        "inactivity.run",
        "users.unban.user",
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
        "greetings.user_card.off",
        "greetings.user_card.on",
        "greetings.user_card.status",
    }


def test_command_validator_has_no_legacy_tracking_fields() -> None:
    result = validate_command_tree()

    assert all(issue.code != "legacy_root" for issue in result.warnings)


def test_dm_summary_contract_roots_and_children_are_exact() -> None:
    source = Path("app/plugins/commands.py").read_text(encoding="utf-8")
    barcello_source = Path("app/plugins/commands_modular/barcello.py").read_text(encoding="utf-8")
    riassunto_source = Path("app/plugins/commands_modular/riassunto.py").read_text(encoding="utf-8")
    aura_source = Path("app/plugins/commands_modular/aura.py").read_text(encoding="utf-8")
    attivita_source = Path("app/plugins/commands_modular/attivita.py").read_text(encoding="utf-8")

    assert 'app_commands.Group(name="dmchannelsummary"' in source
    assert 'app_commands.Group(name="dmserversummary"' in source

    for token in ['name="on"', 'name="off"', 'name="status"']:
        assert token in riassunto_source
        assert token in barcello_source
    for token in ['"today" if is_english else "oggi"', '"yesterday" if is_english else "ieri"', '"last" if is_english else "ultimi"', '"range" if is_english else "intervallo"']:
        assert token in riassunto_source
    for token in ['name="on"', 'name="off"', 'name="status"']:
        assert token in aura_source
    for token in ['"today" if is_english else "oggi"', '"yesterday" if is_english else "ieri"', '"last" if is_english else "ultimi"']:
        assert token in aura_source
        assert token in attivita_source
    assert '"range" if is_english else "intervallo"' in aura_source
    assert 'command_names = {' in attivita_source

    assert '@barcello_alias_group.command(name="oggi"' in barcello_source
    assert '@barcello_alias_group.command(name="intervallo"' in barcello_source
    assert '"range" if is_english else "intervallo"' in riassunto_source
    assert '"range" if is_english else "intervallo"' in aura_source
