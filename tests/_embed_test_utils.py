from __future__ import annotations

from types import SimpleNamespace

import discord
from discord import app_commands

from app.services.author import AuthorService
from app.services.footer import FooterService


class SettingsDatabaseStub:
    def __init__(self) -> None:
        self.settings: dict[str, str] = {}

    async def get_setting(self, key: str) -> str | None:
        return self.settings.get(key)

    async def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value

    async def delete_setting(self, key: str) -> None:
        self.settings.pop(key, None)

    async def execute(self, _query: str, _params: tuple[str, ...] = ()) -> None:
        return None

    async def fetchall(self, query: str, params: tuple[str, ...] = ()):
        prefix = str(params[0]).replace('%', '') if params else ''
        if 'FROM settings' not in query:
            return []
        return [
            {'key': key, 'value': value}
            for key, value in sorted(self.settings.items())
            if not prefix or key.startswith(prefix)
        ]


class ResponseStub:
    def __init__(self) -> None:
        self.sent_messages: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def is_done(self) -> bool:
        return False

    async def send_message(self, *args, **kwargs) -> None:
        self.sent_messages.append((args, kwargs))


class FollowupStub:
    def __init__(self) -> None:
        self.sent_messages: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def send(self, *args, **kwargs) -> None:
        self.sent_messages.append((args, kwargs))


class InteractionStub:
    def __init__(self, command) -> None:
        self.command = command
        self.guild_id = 1
        self.channel_id = 2
        self.guild = None
        self.channel = None
        self.response = ResponseStub()
        self.followup = FollowupStub()
        self.user = SimpleNamespace(
            id=99,
            guild_permissions=SimpleNamespace(administrator=True),
            roles=[],
        )


def find_command(group: discord.app_commands.Group, *names: str):
    current = group
    for name in names[:-1]:
        current = next(
            cmd for cmd in current.commands if isinstance(cmd, discord.app_commands.Group) and cmd.name == name
        )
    return next(cmd for cmd in current.commands if cmd.name == names[-1])


def register_embed_tree(embed_module):
    database = SettingsDatabaseStub()
    footer = FooterService(database)
    author = AuthorService(database)
    ctx = SimpleNamespace(
        database=database,
        footer=footer,
        author=author,
        ai=None,
        guard=None,
        timezone=None,
        message_scheduler=None,
        backfill=None,
        retention=None,
        status=None,
        bot=None,
        config=None,
        entitlements=None,
        barcello_service=None,
        barcello_calibration_service=None,
        summary_service=None,
        ingest=None,
        voice_ingest=None,
        daily_resoconto=None,
        trigger_engine=None,
        activity_insights=None,
        inactivity=None,
        daily_activity_report=None,
        inactive_members_moderation=None,
        channel_summary=None,
        aura_eligibility=None,
        aura_rolling=None,
        member_flow_notifications=None,
    )
    embed_group = app_commands.Group(name='embed', description='embed')
    embed_module.register_embed(embed_group, ctx)
    footer_group = next(
        cmd for cmd in embed_group.commands if isinstance(cmd, discord.app_commands.Group) and cmd.name == 'footer'
    )
    author_group = next(
        cmd for cmd in embed_group.commands if isinstance(cmd, discord.app_commands.Group) and cmd.name == 'author'
    )
    return SimpleNamespace(
        database=database,
        ctx=ctx,
        embed_group=embed_group,
        footer_group=footer_group,
        author_group=author_group,
    )


def section_payload(kwargs: dict[str, object], index: int = 0):
    section = kwargs['sections'][index]
    return section.title, section.lines
