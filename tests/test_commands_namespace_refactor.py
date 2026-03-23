from pathlib import Path


def test_commands_setup_declares_canonical_english_roots() -> None:
    source = Path("app/plugins/commands.py").read_text()

    for root in [
        "database",
        "ai",
        "commandguard",
        "audio",
        "campaigns",
        "qna",
        "triggers",
        "embed",
        "privacy",
        "users",
        "greetings",
        "inactivity",
        "channelsummary",
        "serversummary",
        "dmsummary",
        "aurasummary",
        "barcellosummary",
    ]:
        assert f'app_commands.Group(name="{root}"' in source

    for legacy_root in ["admin", "mod", "campagne", "frasi", "roles"]:
        assert f'app_commands.Group(name="{legacy_root}"' not in source


def test_commands_setup_registers_canonical_namespaces_with_matching_top_levels() -> None:
    source = Path("app/plugins/commands.py").read_text()

    assert 'register_roles(commandguard_group, ctx, top_level="commandguard", visual_top_level="commandguard")' in source
    assert 'register_messaggi(campaigns_group, ctx, top_level="campaigns", visual_top_level="campaigns")' in source
    assert 'register_privacy(privacy_group, ctx, top_level="privacy", visual_top_level="privacy")' in source
    assert 'register_inattivi(inactivity_group, ctx, top_level="inactivity", visual_top_level="inactivity")' in source
    assert 'register_greetings(greetings_group, ctx, top_level="greetings", visual_top_level="greetings")' in source
    assert 'register_moderazione_utenti(users_group, ctx, top_level="users", visual_top_level="users")' in source
    assert 'register_resoconto(channelsummary_group, serversummary_group, ctx, channel_root="channelsummary", server_root="serversummary")' in source


def test_commands_setup_keeps_only_explicit_italian_alias_roots() -> None:
    source = Path("app/plugins/commands.py").read_text()

    assert 'riassunto_alias_group = app_commands.Group(name="riassunto"' in source
    assert 'aura_alias_group = app_commands.Group(name="aura"' in source
    assert 'resocontocanale_alias_group = app_commands.Group(name="resocontocanale"' in source
    assert 'resocontoserver_alias_group = app_commands.Group(name="resocontoserver"' in source
    assert 'attivita_group = app_commands.Group(name="attivita"' in source
    assert 'register_ask(bot.tree, guild_obj, ctx, command_name="domanda", root_top_level="qna", visual_top_level="domanda")' in source
    assert 'domanda_group = app_commands.Group(' not in source


def test_command_setup_root_order_matches_the_new_contract() -> None:
    source = Path("app/plugins/commands.py").read_text()

    expected_order = [
        'database_group,',
        'ai_group,',
        'commandguard_group,',
        'audio_group,',
        'campaigns_group,',
        'qna_group,',
        'triggers_group,',
        'embed_group,',
        'privacy_group,',
        'users_group,',
        'greetings_group,',
        'inactivity_group,',
        'channelsummary_group,',
        'serversummary_group,',
        'dmsummary_group,',
        'aurasummary_group,',
        'barcellosummary_group,',
        'riassunto_alias_group,',
        'aura_alias_group,',
        'resocontocanale_alias_group,',
        'resocontoserver_alias_group,',
        'attivita_group,',
    ]

    start = source.index('root_commands: list[app_commands.Command | app_commands.Group] = [')
    root_block = source[start: source.index(']\n\n    def add_tree_command', start)]
    current_index = -1
    for token in expected_order:
        new_index = root_block.index(token)
        assert new_index > current_index
        current_index = new_index


def test_campaigns_and_triggers_modules_emit_canonical_top_levels_with_localized_aliases_only_user_facing() -> None:
    triggers_source = Path("app/plugins/commands_modular/triggers.py").read_text()
    campaigns_source = Path("app/plugins/commands_modular/messaggi.py").read_text()
    roles_source = Path("app/plugins/commands_modular/roles.py").read_text()

    assert 'top_level=triggers_root if subcommand_path.split()[0] == triggers_root else subcommand_path.split()[0]' in triggers_source
    assert 'visual_top_level=subcommand_path.split()[0] if subcommand_path.strip() else triggers_root' in triggers_source
    assert 'def register_messaggi(campagne_group: app_commands.Group, ctx: CommandContext, *, top_level: str = "campaigns", visual_top_level: str = "campaigns")' in campaigns_source
    assert 'top_level="commandguard"' in roles_source
    assert 'visual_top_level="commandguard"' in roles_source
    assert 'visual_top_level="roles"' not in roles_source
