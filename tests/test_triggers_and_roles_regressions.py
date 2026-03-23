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
        self._members = {
            456: SimpleNamespace(id=456, mention="<@456>", display_name="Alice"),
            789: SimpleNamespace(id=789, mention="<@789>", display_name="Mario"),
        }

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


def test_triggers_guard_uses_canonical_admin_permission_keys(triggers_module, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def _check_permission(interaction, command_name, ctx):
        seen.append(command_name)
        return True

    sent = []

    async def _send_standard_response(interaction, **kwargs):
        sent.append(kwargs)

    monkeypatch.setattr(triggers_module, "check_permission", _check_permission)
    monkeypatch.setattr(triggers_module, "send_standard_response", _send_standard_response)

    triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
    campaigns_group = discord.app_commands.Group(name="campaigns", description="campaigns")
    qna_group = discord.app_commands.Group(name="qna", description="qna")
    ctx = SimpleNamespace(database=_TriggerDb(), footer=None, guard=None, timezone=None, message_scheduler=None, trigger_engine=None)
    frasi_group = triggers_module.register_triggers(triggers_group, campaigns_group, qna_group, ctx, triggers_root="triggers")

    entry_list = _find_command(frasi_group, "entry_list")
    asyncio.run(entry_list.callback(_Interaction(entry_list)))

    template_show = _find_command(frasi_group, "template_global_show")
    asyncio.run(template_show.callback(_Interaction(template_show)))

    prompt_show = _find_command(campaigns_group, "prompt", "schedule_show")

    async def _get_message_campaign(self, guild_id, id):
        return None

    ctx.database.get_message_campaign = types.MethodType(_get_message_campaign, ctx.database)
    asyncio.run(prompt_show.callback(_Interaction(prompt_show), "5"))

    assert seen == [
        "admin.triggers.phrases.entry_list",
        "admin.triggers.phrases.template_global_show",
        "admin.campaigns.prompt.schedule_show",
    ]
    assert sent[0]["subcommand_path"] == "triggers phrases entry_list"
    assert sent[1]["subcommand_path"] == "triggers phrases template_global_show"
    assert sent[2]["subcommand_path"] == "campaigns prompt schedule_show"
    assert [payload["top_level"] for payload in sent] == ["triggers", "triggers", "campaigns"]
    assert sent[0]["visual_top_level"] == "triggers"
    assert sent[1]["visual_top_level"] == "triggers"
    assert sent[2]["visual_top_level"] == "campaigns"


def test_permission_helpers_keep_only_canonical_keys(import_fresh) -> None:
    permissions_module = import_fresh("app.plugins.commands_modular.permissions")

    assert permissions_module.canonical_permission_key("admin.frasi.entry_list") == "admin.triggers.phrases.entry_list"
    assert permissions_module.canonical_permission_key(" Admin.Frasi.Entry_List ") == "admin.triggers.phrases.entry_list"
    assert permissions_module.canonical_permission_key("admin.status") == "status"
    assert permissions_module.canonical_permission_key("admin.events.on") == "database.events.on"
    assert permissions_module.canonical_permission_key("admin.retention.config_show") == "database.retention.limits_show"
    assert permissions_module.canonical_permission_key("admin.backfill.config_reset") == "database.backfill.limits_reset"
    assert permissions_module.canonical_permission_key("admin.ai.model_show") == "ai.model_show"
    assert permissions_module.canonical_permission_key("admin.audionotes.config_show") == "audio.clips.limits_show"
    assert permissions_module.canonical_permission_key("admin.stt.config_reset") == "audio.clips.stt_reset"
    assert permissions_module.canonical_permission_key("admin.translate.config_set") == "audio.clips.translate_set"
    assert permissions_module.canonical_permission_key("admin.campaigns.quiet.config_set") == "admin.campaigns.quiet.range_set"
    assert permissions_module.canonical_permission_key("admin.campagne.cap.config_show") == "admin.campaigns.cap.limits_show"
    assert permissions_module.canonical_permission_key("admin.insights.template_show") == "admin.campaigns.insights.template_show"
    assert permissions_module.canonical_permission_key("admin.barcello.mood_set") == "status.mood_set"


def test_role_list_and_user_list_render_labels(roles_module, monkeypatch: pytest.MonkeyPatch) -> None:
    sent = []

    async def _check_permission(*args, **kwargs):
        return True

    async def _send_standard_response(interaction, **kwargs):
        sent.append(kwargs)

    class _Db:
        async def list_role_policies(self, guild_id: str):
            return [
                {"role_id": "123", "command": "admin.test", "usage_limit": 5, "cooldown_seconds": 10},
                {"role_id": "999", "command": "admin.test2", "usage_limit": None, "cooldown_seconds": None},
            ]

        async def list_user_policies(self, guild_id: str):
            return [
                {"user_id": "456", "command": "admin.test", "usage_limit": 1, "cooldown_seconds": 0},
                {"user_id": "777", "command": "admin.other", "usage_limit": None, "cooldown_seconds": None},
            ]

    monkeypatch.setattr(roles_module, "check_permission", _check_permission)
    monkeypatch.setattr(roles_module, "send_standard_response", _send_standard_response)

    group = discord.app_commands.Group(name="commandguard", description="commandguard")
    roles_module.register_roles(group, SimpleNamespace(database=_Db(), footer=None), top_level="commandguard", visual_top_level="commandguard")

    role_list = _find_command(group, "role_list")
    asyncio.run(role_list.callback(_Interaction(role_list)))
    user_list = _find_command(group, "user_list")
    asyncio.run(user_list.callback(_Interaction(user_list)))

    role_lines = sent[0]["sections"][0].lines
    assert sent[0]["top_level"] == "commandguard"
    assert sent[1]["top_level"] == "commandguard"
    assert sent[0]["visual_top_level"] == "commandguard"
    assert sent[1]["visual_top_level"] == "commandguard"
    assert role_lines[0][0] == "<@&123> (Moderatori)"
    assert role_lines[1][0] == "Deleted role (ID: 999)"
    assert "command=admin.test" in role_lines[0][1]
    assert "command=admin.test2" in role_lines[1][1]

    user_lines = sent[1]["sections"][0].lines
    assert user_lines[0][0] == "<@456> (Alice)"
    assert user_lines[1][0] == "Unknown user (ID: 777)"
    assert "command=admin.test" in user_lines[0][1]
    assert "command=admin.other" in user_lines[1][1]


def test_qna_bonus_show_passes_user_as_subtitle_arg(triggers_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _check_permission(*args, **kwargs):
        return True

    sent = []

    async def _send_standard_response(interaction, **kwargs):
        sent.append(kwargs)

    class _Db(_TriggerDb):
        async def get_qna_bonus(self, guild_id: str, user_id: str):
            assert (guild_id, user_id) == ("1", "789")
            return 4, None

    monkeypatch.setattr(triggers_module, "check_permission", _check_permission)
    monkeypatch.setattr(triggers_module, "send_standard_response", _send_standard_response)

    triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
    campaigns_group = discord.app_commands.Group(name="campaigns", description="campaigns")
    qna_group = discord.app_commands.Group(name="qna", description="qna")
    ctx = SimpleNamespace(database=_Db(), footer=None, guard=None, timezone=None, message_scheduler=None, trigger_engine=None)
    triggers_module.register_triggers(triggers_group, campaigns_group, qna_group, ctx, triggers_root="triggers")

    cmd = _find_command(qna_group, "bonus_show")
    interaction = _Interaction(cmd)
    user = interaction.guild.get_member(789)
    asyncio.run(cmd.callback(interaction, user))

    assert sent
    assert sent[0]["subcommand_path"] == "qna bonus_show"
    assert sent[0]["subtitle_args"] == [user]
