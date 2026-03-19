from __future__ import annotations

import asyncio
import types
from types import SimpleNamespace

import discord
import pytest


@pytest.fixture
def roles_module(import_fresh):
    return import_fresh("app.plugins.commands_modular.roles")


@pytest.fixture
def triggers_module(import_fresh):
    return import_fresh("app.plugins.commands_modular.triggers")


class _Response:
    def __init__(self) -> None:
        self.payload = None

    def is_done(self) -> bool:
        return self.payload is not None

    async def send_message(self, content=None, embed=None, ephemeral: bool = False, **kwargs) -> None:
        self.payload = {"content": content, "embed": embed, "ephemeral": ephemeral, **kwargs}


class _Followup:
    async def send(self, *args, **kwargs) -> None:
        return None


class _Guild:
    def __init__(self) -> None:
        self._roles = {123: SimpleNamespace(id=123, mention="<@&123>", name="Moderatori")}
        self._members = {456: SimpleNamespace(id=456, mention="<@456>", display_name="Alice")}

    def get_role(self, role_id: int):
        return self._roles.get(role_id)

    def get_member(self, user_id: int):
        return self._members.get(user_id)


class _Interaction:
    def __init__(self, command) -> None:
        self.command = command
        self.guild_id = 1
        self.channel_id = 2
        self.guild = _Guild()
        self.response = _Response()
        self.followup = _Followup()
        self.user = SimpleNamespace(id=99, guild_permissions=SimpleNamespace(administrator=False), roles=[])


class _TriggerDb:
    async def list_trigger_phrases_guild(self, guild_id: str):
        assert guild_id == "1"
        return [{"id": 7, "phrase": "ciao", "match_mode": "CONTAINS", "embed_color": "#FFAA00", "cooldown_seconds": None, "allowed_role_ids": ["123"], "enabled": 1}]

    async def get_trigger_state_any_channel(self, guild_id: str, key: str):
        assert (guild_id, key) == ("1", "frasi")
        return {"templates": {"DEFAULT": "ciao", "FIRST": "benvenuto"}}


def _find_command(group: discord.app_commands.Group, *names: str):
    current = group
    for name in names[:-1]:
        current = next(cmd for cmd in current.commands if isinstance(cmd, discord.app_commands.Group) and cmd.name == name)
    return next(cmd for cmd in current.commands if cmd.name == names[-1])


def test_triggers_guard_uses_resolved_permission_keys(triggers_module, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, tuple[str, ...]]] = []

    async def _check_permission(interaction, command_name, ctx, *, legacy_aliases=()):
        seen.append((command_name, tuple(legacy_aliases)))
        return True

    sent = []

    async def _send_standard_response(interaction, **kwargs):
        sent.append(kwargs)

    monkeypatch.setattr(triggers_module, "check_permission", _check_permission)
    monkeypatch.setattr(triggers_module, "send_standard_response", _send_standard_response)

    bm_group = discord.app_commands.Group(name="bm", description="bm")
    campagne_group = discord.app_commands.Group(name="campagne", description="campagne")
    qna_group = discord.app_commands.Group(name="qna", description="qna")
    insights_group = discord.app_commands.Group(name="insights", description="insights")
    ctx = SimpleNamespace(database=_TriggerDb(), footer=None, guard=None, timezone=None, message_scheduler=None, trigger_engine=None)
    frasi_group = triggers_module.register_triggers(bm_group, campagne_group, qna_group, insights_group, ctx)

    entry_list = _find_command(frasi_group, "entry_list")
    asyncio.run(entry_list.callback(_Interaction(entry_list)))

    template_show = _find_command(frasi_group, "template_global_show")
    asyncio.run(template_show.callback(_Interaction(template_show)))

    prompt_show = _find_command(campagne_group, "prompt", "entry_show")

    async def _get_message_campaign(self, guild_id, id):
        return None

    ctx.database.get_message_campaign = types.MethodType(_get_message_campaign, ctx.database)
    asyncio.run(prompt_show.callback(_Interaction(prompt_show), 5))

    assert seen[0][0] == "bm.frasi.entry_list"
    assert "frasi.entry_list" in seen[0][1]
    assert "frasi.list" in seen[0][1]
    assert seen[1][0] == "bm.frasi.template_global_show"
    assert "frasi.template_global_show" in seen[1][1]
    assert "frasi.template_show" in seen[1][1]
    assert seen[2][0] == "bm.campagne.prompt.entry_show"
    assert "campagne.prompt.entry_show" in seen[2][1]
    assert "bm.prompt.entry_show" in seen[2][1]
    assert sent[0]["subcommand_path"] == "frasi entry_list"
    assert sent[1]["subcommand_path"] == "frasi template_global_show"
    assert sent[2]["subcommand_path"] == "prompt entry_show"


def test_role_list_and_user_list_render_labels(roles_module, monkeypatch: pytest.MonkeyPatch) -> None:
    sent = []

    async def _check_permission(*args, **kwargs):
        return True

    async def _send_standard_response(interaction, **kwargs):
        sent.append(kwargs)

    class _Db:
        async def list_role_policies(self, guild_id: str):
            return [
                {"role_id": "123", "command": "bm.test", "usage_limit": 5, "cooldown_seconds": 10},
                {"role_id": "999", "command": "bm.test2", "usage_limit": None, "cooldown_seconds": None},
            ]

        async def list_user_policies(self, guild_id: str):
            return [
                {"user_id": "456", "command": "bm.test", "usage_limit": 1, "cooldown_seconds": 0},
                {"user_id": "777", "command": "bm.other", "usage_limit": None, "cooldown_seconds": None},
            ]

    monkeypatch.setattr(roles_module, "check_permission", _check_permission)
    monkeypatch.setattr(roles_module, "send_standard_response", _send_standard_response)

    group = discord.app_commands.Group(name="roles", description="roles")
    roles_module.register_roles(group, SimpleNamespace(database=_Db(), footer=None))

    role_list = _find_command(group, "role_list")
    asyncio.run(role_list.callback(_Interaction(role_list)))
    user_list = _find_command(group, "user_list")
    asyncio.run(user_list.callback(_Interaction(user_list)))

    role_lines = sent[0]["sections"][0].lines
    assert role_lines[0][0] == "<@&123> (Moderatori)"
    assert role_lines[1][0] == "Deleted role (ID: 999)"

    user_lines = sent[1]["sections"][0].lines
    assert user_lines[0][0] == "<@456> (Alice)"
    assert user_lines[1][0] == "Unknown user (ID: 777)"
