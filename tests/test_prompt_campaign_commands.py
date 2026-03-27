import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import discord
import pytest

from tests._sqlite_stub import ensure_sqlite_stub
from tests._embed_test_utils import embed_visible_text, primary_field

ensure_sqlite_stub()

pytest.importorskip("aiosqlite")

import app.plugins.commands_modular.triggers as triggers_module
from app.plugins.commands_modular.triggers import register_triggers


def _get_subgroup(group: discord.app_commands.Group, name: str):
    return next(cmd for cmd in group.commands if isinstance(cmd, discord.app_commands.Group) and cmd.name == name)


def _get_command_callback(group: discord.app_commands.Group, name: str):
    return next(cmd.callback for cmd in group.commands if cmd.name == name)


def test_prompt_create_supports_optional_fields_and_one_shot_defaults() -> None:
    async def _run() -> None:
        db = SimpleNamespace(create_message_campaign=AsyncMock(return_value=42))
        scheduler = SimpleNamespace(is_valid_embed_color=lambda _c: True)
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone=ZoneInfo("Europe/Rome"), footer=None)

        group = discord.app_commands.Group(name="admin", description="x")
        campaigns = discord.app_commands.Group(name="campaigns", description="x")
        qna = discord.app_commands.Group(name="qna", description="x")
        old_permission = triggers_module.check_permission
        triggers_module.check_permission = AsyncMock(return_value=True)
        try:
            register_triggers(group, campaigns, qna, ctx)
            prompt_group = _get_subgroup(campaigns, "prompt")
            callback = _get_command_callback(prompt_group, "schedule_add")
            interaction = SimpleNamespace(
                guild_id=1,
                channel_id=2,
                user=SimpleNamespace(id=999),
                command=SimpleNamespace(qualified_name="campaigns prompt schedule_add"),
                data={"name": "schedule_add"},
                response=SimpleNamespace(send_message=AsyncMock(), is_done=lambda: False),
            )

            await callback(
                interaction,
                prompt_text="scrivi un update",
                name=None,
                publish_at=None,
                every=None,
                embed_title=None,
                embed_color=None,
            )
        finally:
            triggers_module.check_permission = old_permission

        kwargs = db.create_message_campaign.await_args.kwargs
        assert kwargs["interval_minutes"] == 0
        assert kwargs["name"].startswith("prompt-")
        assert len(kwargs["start_time_local"]) == 5 and ":" in kwargs["start_time_local"]
        sent_embed = interaction.response.send_message.await_args.kwargs["embed"]
        body_upper = embed_visible_text(sent_embed).upper()
        assert "PROMPT" in body_upper
        assert "SCHEDULE_ADD" in body_upper
        assert "42" in body_upper
        assert "CREATED" in body_upper
        assert primary_field(sent_embed).name == "✅ __**OK**__"
        if "NEXT RUN" in body_upper:
            next_run_section = body_upper.split("NEXT RUN", 1)[1]
            assert any(char.isdigit() for char in next_run_section)

    asyncio.run(_run())


def test_prompt_list_shows_one_shot_label() -> None:
    async def _run() -> None:
        rows = [
            {
                "id": 9,
                "type": "AI_PROMPT",
                "enabled": 1,
                "name": "p1",
                "channel_id": "2",
                "next_run_at": "2026-01-01T10:00:00+00:00",
                "interval_minutes": 0,
                "embed_title": None,
                "embed_color": None,
            }
        ]
        db = SimpleNamespace(list_message_campaigns=AsyncMock(return_value=rows))
        scheduler = SimpleNamespace(is_valid_embed_color=lambda _c: True)
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone=ZoneInfo("Europe/Rome"), footer=None)

        group = discord.app_commands.Group(name="admin", description="x")
        campaigns = discord.app_commands.Group(name="campaigns", description="x")
        qna = discord.app_commands.Group(name="qna", description="x")
        old_permission = triggers_module.check_permission
        triggers_module.check_permission = AsyncMock(return_value=True)
        try:
            register_triggers(group, campaigns, qna, ctx)
            prompt_group = _get_subgroup(campaigns, "prompt")
            callback = _get_command_callback(prompt_group, "schedule_list")
            interaction = SimpleNamespace(
                guild_id=1,
                channel_id=2,
                command=SimpleNamespace(qualified_name="campaigns prompt schedule_list"),
                data={"name": "schedule_list"},
                response=SimpleNamespace(send_message=AsyncMock(), is_done=lambda: False),
            )
            await callback(interaction)
        finally:
            triggers_module.check_permission = old_permission

        sent_embed = interaction.response.send_message.await_args.kwargs["embed"]
        assert "every=one-shot" in embed_visible_text(sent_embed)
        assert primary_field(sent_embed).name == "ℹ️ __**INFO**__"

    asyncio.run(_run())


def test_prompt_show_resolves_schedule_by_name() -> None:
    async def _run() -> None:
        rows = [
            {
                "id": 9,
                "type": "AI_PROMPT",
                "enabled": 1,
                "name": "morning-news",
                "channel_id": "2",
                "next_run_at": "2026-01-01T10:00:00+00:00",
                "interval_minutes": 0,
                "start_time_local": "10:00",
                "embed_title": None,
                "embed_color": None,
                "text": "Scrivi un update",
            }
        ]
        db = SimpleNamespace(
            list_message_campaigns=AsyncMock(return_value=rows),
            get_message_campaign=AsyncMock(return_value=None),
        )
        scheduler = SimpleNamespace(is_valid_embed_color=lambda _c: True)
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone=ZoneInfo("Europe/Rome"), footer=None)

        group = discord.app_commands.Group(name="admin", description="x")
        campaigns = discord.app_commands.Group(name="campaigns", description="x")
        qna = discord.app_commands.Group(name="qna", description="x")
        old_permission = triggers_module.check_permission
        triggers_module.check_permission = AsyncMock(return_value=True)
        try:
            register_triggers(group, campaigns, qna, ctx)
            prompt_group = _get_subgroup(campaigns, "prompt")
            callback = _get_command_callback(prompt_group, "schedule_show")
            interaction = SimpleNamespace(
                guild_id=1,
                channel_id=2,
                command=SimpleNamespace(qualified_name="campaigns prompt schedule_show"),
                data={"name": "schedule_show"},
                response=SimpleNamespace(send_message=AsyncMock(), is_done=lambda: False),
            )
            await callback(interaction, id_or_name="morning-news")
        finally:
            triggers_module.check_permission = old_permission

        sent_embed = interaction.response.send_message.await_args.kwargs["embed"]
        visible_text = embed_visible_text(sent_embed)
        assert "morning-news" in visible_text
        assert "Prompt Text" in visible_text
        assert "Scrivi un update" in visible_text
        assert primary_field(sent_embed).name == "ℹ️ __**INFO**__"

    asyncio.run(_run())


def test_prompt_show_rejects_ambiguous_schedule_name() -> None:
    async def _run() -> None:
        rows = [
            {"id": 9, "type": "AI_PROMPT", "enabled": 1, "name": "dup", "channel_id": "2", "next_run_at": "2026-01-01T10:00:00+00:00", "interval_minutes": 0},
            {"id": 10, "type": "AI_PROMPT", "enabled": 1, "name": "dup", "channel_id": "2", "next_run_at": "2026-01-01T10:00:00+00:00", "interval_minutes": 0},
        ]
        db = SimpleNamespace(
            list_message_campaigns=AsyncMock(return_value=rows),
            get_message_campaign=AsyncMock(return_value=None),
        )
        scheduler = SimpleNamespace(is_valid_embed_color=lambda _c: True)
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone=ZoneInfo("Europe/Rome"), footer=None)

        group = discord.app_commands.Group(name="admin", description="x")
        campaigns = discord.app_commands.Group(name="campaigns", description="x")
        qna = discord.app_commands.Group(name="qna", description="x")
        old_permission = triggers_module.check_permission
        triggers_module.check_permission = AsyncMock(return_value=True)
        try:
            register_triggers(group, campaigns, qna, ctx)
            prompt_group = _get_subgroup(campaigns, "prompt")
            callback = _get_command_callback(prompt_group, "schedule_show")
            interaction = SimpleNamespace(
                guild_id=1,
                channel_id=2,
                command=SimpleNamespace(qualified_name="campaigns prompt schedule_show"),
                data={"name": "schedule_show"},
                response=SimpleNamespace(send_message=AsyncMock(), is_done=lambda: False),
            )
            await callback(interaction, id_or_name="dup")
        finally:
            triggers_module.check_permission = old_permission

        sent_embed = interaction.response.send_message.await_args.kwargs["embed"]
        assert "ambiguous" in embed_visible_text(sent_embed).lower()
        assert primary_field(sent_embed).name == "⚠️ __**WARNING**__"

    asyncio.run(_run())
