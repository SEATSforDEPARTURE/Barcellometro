from pathlib import Path


def test_resoconto_restores_top_level_manual_commands() -> None:
    source = Path("app/plugins/commands_modular/resoconto.py").read_text()

    for pattern in [
        '@resocontocanale_group.command(name="oggi"',
        '@resocontocanale_group.command(name="ieri"',
        '@resocontocanale_group.command(name="ultimi"',
        '@resocontocanale_group.command(name="range"',
        '@resocontoserver_group.command(name="oggi"',
        '@resocontoserver_group.command(name="ieri"',
        '@resocontoserver_group.command(name="ultimi"',
        '@resocontoserver_group.command(name="range"',
        'canale_aura_group = app_commands.Group(name="aura"',
        'server_aura_group = app_commands.Group(name="aura"',
    ]:
        assert pattern in source


def test_critical_modules_use_standard_response_renderer() -> None:
    targets = {
        "app/plugins/commands_modular/resoconto.py": [
            "send_standard_response(",
            "_send_resoconto_response(",
        ],
        "app/plugins/commands_modular/riassunto.py": [
            "send_standard_response(",
            "async def send_ephemeral",
        ],
        "app/plugins/commands.py": [
            "send_standard_response(",
            "subcommand_path=subcommand_path",
        ],
    }

    for path, required in targets.items():
        text = Path(path).read_text()
        for item in required:
            assert item in text


def test_critical_modules_no_longer_send_raw_string_slash_responses() -> None:
    critical_files = [
        Path("app/plugins/commands_modular/resoconto.py"),
        Path("app/plugins/commands_modular/riassunto.py"),
        Path("app/plugins/commands.py"),
        Path("app/plugins/commands_modular/translate.py"),
        Path("app/plugins/commands_modular/stt.py"),
    ]
    forbidden = [
        'interaction.response.send_message("',
        'interaction.followup.send("',
    ]
    for path in critical_files:
        text = path.read_text()
        for needle in forbidden:
            assert needle not in text, f"Unexpected raw response in {path}: {needle}"
