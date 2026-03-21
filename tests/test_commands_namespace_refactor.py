from pathlib import Path


def test_root_namespaces_include_mod_greetings_and_inactivity() -> None:
    source = Path("app/plugins/commands.py").read_text()

    assert 'app_commands.Group(name="admin"' in source
    assert 'app_commands.Group(name="mod"' in source
    assert 'app_commands.Group(name="greetings"' in source
    assert 'app_commands.Group(name="inactivity"' in source
    assert 'app_commands.Group(name="moderazione"' not in source
    assert 'app_commands.Group(name="inattivi"' not in source


def test_mod_greetings_and_inactivity_register_independently() -> None:
    source = Path("app/plugins/commands.py").read_text()

    assert 'register_inattivi(inactivity_group, ctx)' in source
    assert 'register_greetings(greetings_group, ctx)' in source
    assert 'register_moderazione_utenti(mod_group, ctx)' in source


def test_admin_group_is_the_registered_root_namespace() -> None:
    source = Path("app/plugins/commands.py").read_text()

    assert 'admin_group = app_commands.Group(name="admin", description="Barcellometro control commands")' in source
    assert 'root_commands: list[app_commands.Command | app_commands.Group] = [' in source
    assert '        admin_group,' in source


def test_barcello_restores_top_level_registration_alongside_admin_group() -> None:
    commands_source = Path("app/plugins/commands.py").read_text()
    barcello_source = Path("app/plugins/commands_modular/barcello.py").read_text()

    assert "register_barcello(admin_group, bot.tree, guild_obj, ctx)" in commands_source
    assert '@app_commands.command(name="barcello", description="Mostra lo stato del barcello (in DM)")' in barcello_source
    assert '@app_commands.rename(window_minutes="minuti")' in barcello_source
    assert 'permission_name="barcello"' in barcello_source
    assert 'command_path="barcello"' in barcello_source
    assert "send_dm_or_followup(" in barcello_source
    assert "_build_barcello_dm_report(public_embed=public_embed, details_embed=details_embed)" in barcello_source
    assert 'tree.add_command(barcello_command, guild=guild)' in barcello_source


def test_campaign_and_trigger_outputs_use_visual_top_levels() -> None:
    triggers_source = Path("app/plugins/commands_modular/triggers.py").read_text()
    messaggi_source = Path("app/plugins/commands_modular/messaggi.py").read_text()
    command_embeds_source = Path("app/shared/discord/command_embeds.py").read_text()

    assert 'visual_top_level=subcommand_path.split()[0] if subcommand_path.strip() else None' in triggers_source
    assert 'visual_top_level="campagne"' in messaggi_source
    assert "normalize_display_command_context" in command_embeds_source
