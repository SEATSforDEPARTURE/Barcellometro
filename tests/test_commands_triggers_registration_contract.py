from __future__ import annotations

import asyncio
from types import SimpleNamespace

import discord
import pytest


class _FakeTree:
    def __init__(self) -> None:
        self._commands: list[discord.app_commands.Command | discord.app_commands.Group] = []
        self._error_handler = None
        self._global_remote_commands = []
        self._guild_remote_commands = []

    def add_command(self, command, *, guild=None) -> None:  # noqa: ANN001
        self._commands.append(command)

    def get_commands(self, *, guild=None):  # noqa: ANN001
        return list(self._commands)

    async def sync(self, *, guild=None):  # noqa: ANN001
        return list(self._commands)

    async def fetch_commands(self, *, guild=None):  # noqa: ANN001
        if guild is None:
            return list(self._global_remote_commands)
        return list(self._guild_remote_commands)

    def error(self, handler):
        self._error_handler = handler
        return handler


class _FakeBot:
    def __init__(self) -> None:
        self.tree = _FakeTree()
        self.listeners: list[tuple[str, object]] = []
        self.application_id = 999
        self.http = SimpleNamespace(
            delete_global_command=self._delete_global_command,
            delete_guild_command=self._delete_guild_command,
        )
        self.deleted_global_ids: list[int] = []
        self.deleted_guild_ids: list[tuple[int, int]] = []

    def add_listener(self, callback, name: str) -> None:  # noqa: ANN001
        self.listeners.append((name, callback))

    async def _delete_global_command(self, application_id: int, command_id: int) -> None:
        self.deleted_global_ids.append(command_id)

    async def _delete_guild_command(self, application_id: int, guild_id: int, command_id: int) -> None:
        self.deleted_guild_ids.append((guild_id, command_id))


def _stub_register_barcello(
    triggers_group: discord.app_commands.Group,
    dmchannelsummary_group: discord.app_commands.Group,
    barcello_alias_group: discord.app_commands.Group,
    tree,  # noqa: ANN001
    guild,  # noqa: ANN001
    ctx,  # noqa: ANN001
    **kwargs,  # noqa: ANN003
) -> None:
    barcello_group = discord.app_commands.Group(name="barcello", description="barcello")
    triggers_group.add_command(barcello_group)

    for name in (
        "on",
        "off",
        "status",
        "calibrate",
        "run",
        "schedule_add",
        "schedule_edit",
        "schedule_remove",
        "schedule_show",
        "schedule_list",
    ):
        @barcello_group.command(name=name, description=name)
        async def _placeholder(interaction):  # noqa: ANN001
            return None


def _stub_register_triggers(
    triggers_group: discord.app_commands.Group,
    campaigns_group: discord.app_commands.Group,
    qna_group: discord.app_commands.Group,
    ctx,  # noqa: ANN001
    **kwargs,  # noqa: ANN003
):
    phrases_group = discord.app_commands.Group(name="phrases", description="phrases")
    triggers_group.add_command(phrases_group)
    return phrases_group


def _patch_noop_registrars(commands_module, monkeypatch: pytest.MonkeyPatch) -> None:
    noop = lambda *args, **kwargs: None
    for name in [
        "register_status",
        "register_database",
        "register_ai",
        "register_embed",
        "register_roles",
        "register_stt",
        "register_translate",
        "register_audio_notes",
        "register_messaggi",
        "register_voice_ingest",
        "register_privacy",
        "register_riassunto",
        "register_aura",
        "register_attivita",
        "register_inattivi",
        "register_greetings",
        "register_moderazione_utenti",
        "register_resoconto",
        "register_ask",
    ]:
        monkeypatch.setattr(commands_module, name, noop)

    monkeypatch.setattr(commands_module, "register_barcello", _stub_register_barcello)
    monkeypatch.setattr(commands_module, "register_triggers", _stub_register_triggers)


def test_setup_registers_triggers_root_with_barcello_run_contract(import_fresh, monkeypatch: pytest.MonkeyPatch) -> None:
    commands_module = import_fresh("app.plugins.commands")
    _patch_noop_registrars(commands_module, monkeypatch)

    bot = _FakeBot()
    config = SimpleNamespace(guild_id=123)
    ctx = SimpleNamespace(bot=bot, config=config, footer=None, author=None)
    monkeypatch.setattr(commands_module.CommandContext, "from_registry", lambda registry: ctx)

    commands_module.setup(registry=SimpleNamespace())

    root_names = {command.name for command in bot.tree.get_commands()}
    assert "triggers" in root_names
    assert "dmchannelsummary" in root_names
    assert "dmserversummary" in root_names

    triggers_root = next(command for command in bot.tree.get_commands() if command.name == "triggers")
    barcello_group = next(command for command in triggers_root.commands if command.name == "barcello")
    assert {command.name for command in barcello_group.commands} == {
        "on",
        "off",
        "status",
        "calibrate",
        "run",
        "schedule_add",
        "schedule_edit",
        "schedule_remove",
        "schedule_show",
        "schedule_list",
    }


def test_setup_fails_fast_when_triggers_barcello_run_contract_is_broken(import_fresh, monkeypatch: pytest.MonkeyPatch) -> None:
    commands_module = import_fresh("app.plugins.commands")
    _patch_noop_registrars(commands_module, monkeypatch)

    def _broken_register_barcello(
        triggers_group: discord.app_commands.Group,
        dmchannelsummary_group: discord.app_commands.Group,
        barcello_alias_group: discord.app_commands.Group,
        tree,  # noqa: ANN001
        guild,  # noqa: ANN001
        ctx,  # noqa: ANN001
        **kwargs,  # noqa: ANN003
    ) -> None:
        barcello_group = discord.app_commands.Group(name="barcello", description="barcello")
        triggers_group.add_command(barcello_group)
        for name in ("on", "off", "status", "calibrate"):
            @barcello_group.command(name=name, description=name)
            async def _placeholder(interaction):  # noqa: ANN001
                return None

    monkeypatch.setattr(commands_module, "register_barcello", _broken_register_barcello)

    bot = _FakeBot()
    config = SimpleNamespace(guild_id=123)
    ctx = SimpleNamespace(bot=bot, config=config, footer=None, author=None)
    monkeypatch.setattr(commands_module.CommandContext, "from_registry", lambda registry: ctx)

    with pytest.raises(RuntimeError, match="missing /triggers barcello commands: run, schedule_add, schedule_edit, schedule_list, schedule_remove, schedule_show"):
        commands_module.setup(registry=SimpleNamespace())


def test_remove_legacy_summary_commands_removes_only_banned_roots(import_fresh) -> None:
    commands_module = import_fresh("app.plugins.commands")
    bot = _FakeBot()
    guild = discord.Object(id=123)

    bot.tree._global_remote_commands = [
        SimpleNamespace(name="dmsummary", id=10),
        SimpleNamespace(name="triggers", id=11),
    ]
    bot.tree._guild_remote_commands = [
        SimpleNamespace(name="activitysummary", id=20),
        SimpleNamespace(name="dmchannelsummary", id=21),
    ]

    asyncio.run(commands_module._remove_legacy_summary_commands(bot=bot, guild_obj=guild))

    assert bot.deleted_global_ids == [10]
    assert bot.deleted_guild_ids == [(123, 20)]


def test_remove_legacy_summary_commands_is_idempotent_when_no_legacy(import_fresh) -> None:
    commands_module = import_fresh("app.plugins.commands")
    bot = _FakeBot()
    guild = discord.Object(id=123)

    bot.tree._global_remote_commands = [SimpleNamespace(name="dmchannelsummary", id=100)]
    bot.tree._guild_remote_commands = [SimpleNamespace(name="dmserversummary", id=200)]

    asyncio.run(commands_module._remove_legacy_summary_commands(bot=bot, guild_obj=guild))
    asyncio.run(commands_module._remove_legacy_summary_commands(bot=bot, guild_obj=guild))

    assert bot.deleted_global_ids == []
    assert bot.deleted_guild_ids == []


def test_setup_registers_activity_subgroup_without_duplicate_on(import_fresh, monkeypatch: pytest.MonkeyPatch) -> None:
    commands_module = import_fresh("app.plugins.commands")

    noop = lambda *args, **kwargs: None
    for name in [
        "register_status",
        "register_database",
        "register_ai",
        "register_embed",
        "register_roles",
        "register_stt",
        "register_translate",
        "register_audio_notes",
        "register_messaggi",
        "register_voice_ingest",
        "register_privacy",
        "register_riassunto",
        "register_aura",
        "register_inattivi",
        "register_greetings",
        "register_moderazione_utenti",
        "register_resoconto",
        "register_ask",
    ]:
        monkeypatch.setattr(commands_module, name, noop)

    monkeypatch.setattr(commands_module, "register_barcello", _stub_register_barcello)
    monkeypatch.setattr(commands_module, "register_triggers", _stub_register_triggers)

    from app.plugins.commands_modular.attivita import register_attivita as real_register_attivita

    monkeypatch.setattr(commands_module, "register_attivita", real_register_attivita)

    bot = _FakeBot()
    config = SimpleNamespace(guild_id=123)
    ctx = SimpleNamespace(bot=bot, config=config, footer=None, author=None)
    monkeypatch.setattr(commands_module.CommandContext, "from_registry", lambda registry: ctx)

    commands_module.setup(registry=SimpleNamespace())

    root_by_name = {command.name: command for command in bot.tree.get_commands()}
    assert "triggers" in root_by_name
    assert "barcello" in root_by_name
    assert "dmserversummary" in root_by_name
    assert "attivita" in root_by_name

    dmserversummary_group = root_by_name["dmserversummary"]
    activity_group = next(command for command in dmserversummary_group.commands if command.name == "activity")
    assert {command.name for command in activity_group.commands} == {
        "on",
        "off",
        "status",
        "today",
        "yesterday",
        "last",
        "range",
    }

    attivita_alias_group = root_by_name["attivita"]
    assert {command.name for command in attivita_alias_group.commands} == {"oggi", "ieri", "ultimi", "range"}
