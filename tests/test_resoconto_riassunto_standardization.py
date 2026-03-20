import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import discord
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("aiosqlite")

from app.plugins import commands as commands_module
from app.plugins.commands_modular import resoconto as resoconto_module
from app.plugins.commands_modular import riassunto as riassunto_module
from app.plugins.commands_modular.resoconto import register_resoconto
from app.plugins.commands_modular.riassunto import register_riassunto


class _FakeResponse:
    def __init__(self) -> None:
        self._done = False
        self.send_message = AsyncMock(side_effect=self._send_message)
        self.defer = AsyncMock(side_effect=self._defer)

    async def _send_message(self, *args, **kwargs):
        self._done = True

    async def _defer(self, *args, **kwargs):
        self._done = True

    def is_done(self) -> bool:
        return self._done


class _FakeInteraction:
    def __init__(self, *, qualified_name: str, guild_id: int = 1, channel_id: int = 2, user_id: int = 3) -> None:
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.user = SimpleNamespace(id=user_id)
        self.command = SimpleNamespace(qualified_name=qualified_name)
        self.data = {"name": qualified_name.split()[-1]}
        self.response = _FakeResponse()
        self.followup = SimpleNamespace(send=AsyncMock())
        self.channel = None


class _FakeTree:
    def __init__(self) -> None:
        self.commands: list[discord.app_commands.Command | discord.app_commands.Group] = []
        self.error_handler = None

    def add_command(self, command, guild=None) -> None:
        self.commands.append(command)

    def get_commands(self, guild=None):
        return list(self.commands)

    async def sync(self, guild=None):
        return list(self.commands)

    def error(self, func):
        self.error_handler = func
        return func


class _FakeBot:
    def __init__(self) -> None:
        self.tree = _FakeTree()
        self.listeners: list[tuple[str, object]] = []

    def add_listener(self, callback, name: str) -> None:
        self.listeners.append((name, callback))


def _get_command_callback(group: discord.app_commands.Group, name: str):
    for cmd in group.commands:
        if cmd.name == name:
            return cmd.callback
    raise AssertionError(f"Command {name} not found")


def _get_subgroup(group: discord.app_commands.Group, name: str):
    for cmd in group.commands:
        if isinstance(cmd, discord.app_commands.Group) and cmd.name == name:
            return cmd
    raise AssertionError(f"Subgroup {name} not found")


def test_resoconto_manual_paths_are_restored_at_top_level_and_kept_under_aura() -> None:
    ctx = SimpleNamespace(timezone=ZoneInfo("Europe/Rome"), config=SimpleNamespace(), footer=None)
    channel_group = discord.app_commands.Group(name="resocontocanale", description="x")
    server_group = discord.app_commands.Group(name="resocontoserver", description="x")

    register_resoconto(channel_group, server_group, ctx)

    channel_names = {cmd.name for cmd in channel_group.commands}
    server_names = {cmd.name for cmd in server_group.commands}
    assert {"oggi", "ieri", "ultimi", "range"}.issubset(channel_names)
    assert {"oggi", "ieri", "ultimi", "range"}.issubset(server_names)

    channel_aura = _get_subgroup(channel_group, "aura")
    server_aura = _get_subgroup(server_group, "aura")
    assert {"oggi", "ieri", "ultimi", "range"}.issubset({cmd.name for cmd in channel_aura.commands})
    assert {"oggi", "ieri", "ultimi", "range"}.issubset({cmd.name for cmd in server_aura.commands})


def test_resoconto_status_uses_standard_embed() -> None:
    async def _run() -> None:
        db = SimpleNamespace(
            get_channel_summary_auto_enabled=AsyncMock(return_value=True),
            list_channel_summary_schedules=AsyncMock(return_value=[]),
        )
        ctx = SimpleNamespace(
            database=db,
            timezone=ZoneInfo("Europe/Rome"),
            config=SimpleNamespace(),
            footer=None,
            channel_summary=object(),
            daily_activity_report=object(),
            entitlements=SimpleNamespace(),
        )
        group = discord.app_commands.Group(name="resocontocanale", description="x")
        server_group = discord.app_commands.Group(name="resocontoserver", description="x")
        old_permission = resoconto_module.check_permission
        resoconto_module.check_permission = AsyncMock(return_value=True)
        try:
            register_resoconto(group, server_group, ctx)
            callback = _get_command_callback(group, "status")
            interaction = _FakeInteraction(qualified_name="resocontocanale status")
            await callback(interaction)
        finally:
            resoconto_module.check_permission = old_permission

        kwargs = interaction.response.send_message.await_args.kwargs
        assert "embed" in kwargs
        assert kwargs["embed"].title
        assert kwargs["embed"].footer.text
        assert not interaction.response.send_message.await_args.args

    asyncio.run(_run())


def test_resocontoserver_status_uses_real_command_title() -> None:
    async def _run() -> None:
        db = SimpleNamespace(
            get_server_summary_auto_enabled=AsyncMock(return_value=True),
            get_server_summary_target_channel=AsyncMock(return_value="99"),
            list_server_summary_schedules=AsyncMock(return_value=[]),
        )
        ctx = SimpleNamespace(
            database=db,
            timezone=ZoneInfo("Europe/Rome"),
            config=SimpleNamespace(),
            footer=None,
            channel_summary=object(),
            daily_activity_report=object(),
            entitlements=SimpleNamespace(),
        )
        channel_group = discord.app_commands.Group(name="resocontocanale", description="x")
        server_group = discord.app_commands.Group(name="resocontoserver", description="x")
        old_permission = resoconto_module.check_permission
        resoconto_module.check_permission = AsyncMock(return_value=True)
        try:
            register_resoconto(channel_group, server_group, ctx)
            callback = _get_command_callback(server_group, "status")
            interaction = _FakeInteraction(qualified_name="resocontoserver status")
            await callback(interaction)
        finally:
            resoconto_module.check_permission = old_permission

        kwargs = interaction.response.send_message.await_args.kwargs
        embed = kwargs["embed"]
        assert embed.title == "📓 RESOCONTOSERVER"
        assert embed.description.startswith("**🛠️ STATUS**")
        assert "RESOCONTO" not in (embed.title or "").replace("RESOCONTOSERVER", "")

    asyncio.run(_run())


def test_riassunto_no_data_guardrail_uses_standard_embed() -> None:
    async def _run() -> None:
        db = SimpleNamespace(get_channel_coverage=AsyncMock(return_value=("2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00")))
        ctx = SimpleNamespace(
            database=db,
            footer=None,
            config=SimpleNamespace(name_policy_text_show_names_always=False),
            entitlements=SimpleNamespace(
                resolve_profile_with_role_id=AsyncMock(return_value=("role1", None)),
                get_command_profile_config=AsyncMock(return_value={"allowed": True, "messages": {}}),
                get_command_limit_seconds=AsyncMock(return_value=None),
            ),
            summary_service=SimpleNamespace(get_config=AsyncMock(return_value={"tiers": {"role1": {"label": "PLUS"}}})),
        )
        group = discord.app_commands.Group(name="riassunto", description="x")
        old_permission = riassunto_module.check_permission
        riassunto_module.check_permission = AsyncMock(return_value=True)
        try:
            register_riassunto(group, ctx)
            callback = _get_command_callback(group, "oggi")
            interaction = _FakeInteraction(qualified_name="riassunto oggi")
            await callback(interaction)
        finally:
            riassunto_module.check_permission = old_permission

        kwargs = interaction.followup.send.await_args.kwargs
        assert "embed" in kwargs
        assert kwargs["embed"].title
        assert kwargs["embed"].footer.text
        assert kwargs["ephemeral"] is True

    asyncio.run(_run())


def test_global_app_command_error_handler_uses_standard_embed(monkeypatch) -> None:
    bot = _FakeBot()
    ctx = SimpleNamespace(bot=bot, config=SimpleNamespace(guild_id="123"), footer=None)

    monkeypatch.setattr(commands_module, "CommandContext", SimpleNamespace(from_registry=lambda registry: ctx))
    monkeypatch.setattr(commands_module, "install_footer_auto_finalize", lambda footer: None)
    monkeypatch.setattr(commands_module, "register_admin", lambda *args, **kwargs: None)
    monkeypatch.setattr(commands_module, "register_roles", lambda *args, **kwargs: None)
    monkeypatch.setattr(commands_module, "register_stt", lambda *args, **kwargs: None)
    monkeypatch.setattr(commands_module, "register_translate", lambda *args, **kwargs: None)
    monkeypatch.setattr(commands_module, "register_audio_notes", lambda *args, **kwargs: None)
    monkeypatch.setattr(commands_module, "register_messaggi", lambda *args, **kwargs: None)
    monkeypatch.setattr(commands_module, "register_voice_ingest", lambda *args, **kwargs: None)
    monkeypatch.setattr(commands_module, "register_privacy", lambda *args, **kwargs: None)
    monkeypatch.setattr(commands_module, "register_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(commands_module, "register_barcello", lambda *args, **kwargs: None)
    monkeypatch.setattr(commands_module, "register_riassunto", lambda *args, **kwargs: None)
    monkeypatch.setattr(commands_module, "register_aura", lambda *args, **kwargs: None)
    monkeypatch.setattr(commands_module, "register_attivita", lambda *args, **kwargs: None)
    monkeypatch.setattr(commands_module, "register_inattivi", lambda *args, **kwargs: None)
    monkeypatch.setattr(commands_module, "register_moderazione_utenti", lambda *args, **kwargs: None)
    monkeypatch.setattr(commands_module, "register_resoconto", lambda *args, **kwargs: None)
    monkeypatch.setattr(commands_module, "register_ask", lambda *args, **kwargs: None)
    monkeypatch.setattr(commands_module, "register_triggers", lambda *args, **kwargs: discord.app_commands.Group(name="frasi", description="x"))

    commands_module.setup(SimpleNamespace())
    interaction = _FakeInteraction(qualified_name="riassunto oggi")
    asyncio.run(bot.tree.error_handler(interaction, Exception("invalid form body")))

    kwargs = interaction.response.send_message.await_args.kwargs
    assert "embed" in kwargs
    assert kwargs["embed"].footer.text
    assert kwargs["embed"].description and "DETAIL:" not in kwargs["embed"].description.upper()
    assert "• Ho avuto un problema a costruire l’embed" in (kwargs["embed"].description or "")


def test_critical_modules_no_longer_use_raw_slash_text_helpers() -> None:
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
