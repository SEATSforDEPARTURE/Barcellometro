import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import discord
import pytest

pytest.importorskip("aiosqlite")

from app.plugins.commands_modular import triggers as triggers_module
from app.plugins.commands_modular.triggers import register_triggers


def _get_subgroup(group: discord.app_commands.Group, name: str):
    return next(cmd for cmd in group.commands if isinstance(cmd, discord.app_commands.Group) and cmd.name == name)


def _get_command_callback(group: discord.app_commands.Group, name: str):
    return next(cmd.callback for cmd in group.commands if cmd.name == name)


def test_prompt_create_supports_optional_fields_and_one_shot_defaults() -> None:
    async def _run() -> None:
        db = SimpleNamespace(create_message_campaign=AsyncMock(return_value=42))
        scheduler = SimpleNamespace(is_valid_embed_color=lambda _c: True)
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone=ZoneInfo("Europe/Rome"))

        group = discord.app_commands.Group(name="bm", description="x")
        campagne = discord.app_commands.Group(name="campagne", description="x")
        qna = discord.app_commands.Group(name="qna", description="x")
        insights = discord.app_commands.Group(name="insights", description="x")

        old_permission = triggers_module.check_permission
        triggers_module.check_permission = AsyncMock(return_value=True)
        try:
            register_triggers(group, campagne, qna, insights, ctx)
            prompt_group = _get_subgroup(campagne, "prompt")
            callback = _get_command_callback(prompt_group, "create")
            interaction = SimpleNamespace(
                guild_id=1,
                channel_id=2,
                user=SimpleNamespace(id=999),
                command=SimpleNamespace(qualified_name="campagne prompt create"),
                data={"name": "create"},
                response=SimpleNamespace(send_message=AsyncMock()),
            )

            await callback(
                interaction,
                prompt_text="scrivi un update",
                name=None,
                time_local=None,
                interval_minutes=None,
                embed_title=None,
                embed_color=None,
            )
        finally:
            triggers_module.check_permission = old_permission

        kwargs = db.create_message_campaign.await_args.kwargs
        assert kwargs["interval_minutes"] == 0
        assert kwargs["name"].startswith("prompt-")
        assert len(kwargs["start_time_local"]) == 5 and ":" in kwargs["start_time_local"]
        msg = interaction.response.send_message.await_args.args[0]
        assert "one-shot" in msg

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
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone=ZoneInfo("Europe/Rome"))

        group = discord.app_commands.Group(name="bm", description="x")
        campagne = discord.app_commands.Group(name="campagne", description="x")
        qna = discord.app_commands.Group(name="qna", description="x")
        insights = discord.app_commands.Group(name="insights", description="x")

        old_permission = triggers_module.check_permission
        triggers_module.check_permission = AsyncMock(return_value=True)
        try:
            register_triggers(group, campagne, qna, insights, ctx)
            prompt_group = _get_subgroup(campagne, "prompt")
            callback = _get_command_callback(prompt_group, "list")
            interaction = SimpleNamespace(
                guild_id=1,
                channel_id=2,
                command=SimpleNamespace(qualified_name="campagne prompt list"),
                data={"name": "list"},
                response=SimpleNamespace(send_message=AsyncMock()),
            )
            await callback(interaction)
        finally:
            triggers_module.check_permission = old_permission

        sent = interaction.response.send_message.await_args.args[0]
        assert "frequenza=one-shot" in sent

    asyncio.run(_run())
