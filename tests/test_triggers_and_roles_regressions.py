from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(Row=dict, Connection=object)
if "openai" not in sys.modules:
    sys.modules["openai"] = types.SimpleNamespace(AsyncOpenAI=object)
if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace(AsyncClient=object, Client=object)

sys.path.append(str(Path(__file__).resolve().parents[1]))

import discord

import importlib.util

ROLES_PATH = Path(__file__).resolve().parents[1] / "app/plugins/commands_modular/roles.py"
roles_spec = importlib.util.spec_from_file_location("roles_module", ROLES_PATH)
roles_module = importlib.util.module_from_spec(roles_spec)
assert roles_spec and roles_spec.loader
roles_spec.loader.exec_module(roles_module)
register_roles = roles_module.register_roles

TRIGGERS_PATH = Path(__file__).resolve().parents[1] / "app/plugins/commands_modular/triggers.py"
triggers_spec = importlib.util.spec_from_file_location("triggers_module", TRIGGERS_PATH)
triggers_module = importlib.util.module_from_spec(triggers_spec)
assert triggers_spec and triggers_spec.loader
triggers_spec.loader.exec_module(triggers_module)
register_triggers = triggers_module.register_triggers


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


def test_triggers_guard_uses_resolved_permission_keys(monkeypatch) -> None:
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
    frasi_group = register_triggers(bm_group, campagne_group, qna_group, insights_group, ctx)

    entry_list = _find_command(frasi_group, "entry_list")
    interaction = _Interaction(entry_list)
    import asyncio
    asyncio.run(entry_list.callback(interaction))

    template_show = _find_command(frasi_group, "template_global_show")
    interaction = _Interaction(template_show)
    asyncio.run(template_show.callback(interaction))

    prompt_show = _find_command(campagne_group, "prompt", "entry_show")

    async def _get_message_campaign(self, guild_id, id):
        return None

    ctx.database.get_message_campaign = types.MethodType(_get_message_campaign, ctx.database)
    interaction = _Interaction(prompt_show)
    asyncio.run(prompt_show.callback(interaction, 5))

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


def test_role_list_and_user_list_render_labels(monkeypatch) -> None:
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
    register_roles(group, SimpleNamespace(database=_Db(), footer=None))

    import asyncio
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
