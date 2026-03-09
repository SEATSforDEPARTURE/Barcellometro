import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

pytest.importorskip("aiosqlite")

from app.plugins.commands_modular.triggers import register_triggers
from app.services.database import DatabaseService
from app.services.ingest import EventEnvelope
from app.services.triggers import TriggerEngineService
import app.services.triggers as triggers_module


class _FakeRepliedMessage:
    def __init__(self) -> None:
        self.replies: list[object] = []

    async def reply(self, *, embed=None, **kwargs):
        self.replies.append(embed)


class _FakeTextChannel:
    def __init__(self) -> None:
        self.target = _FakeRepliedMessage()
        self.sent_embeds: list[object] = []

    async def fetch_message(self, _message_id: int):
        return self.target

    async def send(self, *, embed=None, **kwargs):
        self.sent_embeds.append(embed)


class _FakeBot:
    def __init__(self, channel: _FakeTextChannel) -> None:
        self._channel = channel

    def get_channel(self, _channel_id: int):
        return self._channel


def test_phrases_are_guild_wide_with_dedup_and_embed() -> None:
    async def _run() -> None:
        original_text_channel = triggers_module.discord.TextChannel
        triggers_module.discord.TextChannel = _FakeTextChannel
        try:
            db = DatabaseService(":memory:")
            await db.connect()
            await db.initialize_schema()
            await db.set_trigger_enabled("g1", "ch-a", "frasi", True)

            await db.add_trigger_phrase("g1", "ch-a", "il criccy", "CONTAINS", False, "#FFAA00")
            await db.add_trigger_phrase("g1", "ch-b", "il criccy", "CONTAINS", False, "#00AA00")

            row = await db.fetchone("SELECT MIN(id) AS id FROM trigger_phrases WHERE guild_id = ?", ("g1",))
            assert row is not None
            winner_id = int(row["id"])

            service = TriggerEngineService(db, Mock(), Mock(), Mock(), community_insights=Mock())
            channel = _FakeTextChannel()
            service._bot = _FakeBot(channel)

            envelope = EventEnvelope(
                event_id="evt-1",
                event_type="message.create",
                platform="discord",
                ts="2026-01-01T10:00:00+00:00",
                guild_id="g1",
                channel_id="ch-z",
                thread_id=None,
                author_id="u1",
                content="oggi dico IL CRICCY sempre",
                meta={"message_id": "123"},
            )
            await service._handle_phrases(envelope)

            assert len(channel.target.replies) == 1
            embed = channel.target.replies[0]
            assert embed.title == "💬 FRASI ICONICHE"
            assert embed.description == "il criccy"
            assert getattr(embed.footer, "text", "") == "Servizio offerto dal vostro Barcellometro di fiducia."

            stats = await db.get_phrase_user_stats(winner_id, "u1")
            assert int(stats.get("count", 0)) == 1

            other = await db.fetchone(
                "SELECT id FROM trigger_phrases WHERE guild_id = ? AND id != ? ORDER BY id ASC LIMIT 1",
                ("g1", winner_id),
            )
            assert other is not None
            other_stats = await db.get_phrase_user_stats(int(other["id"]), "u1")
            assert other_stats == {}

            await db.close()
        finally:
            triggers_module.discord.TextChannel = original_text_channel

    asyncio.run(_run())


def test_db_global_phrase_state_and_color_column() -> None:
    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()

        await db.add_trigger_phrase("g1", "c1", "frase", "CONTAINS", False, "#112233")
        rows = await db.list_trigger_phrases_guild("g1")
        assert rows and rows[0]["embed_color"] == "#112233"

        await db.set_trigger_state("g1", "legacy-channel", "frasi", {"templates": {"DEFAULT": "x"}})
        state = await db.get_trigger_state_any_channel("g1", "frasi")
        assert state.get("templates", {}).get("DEFAULT") == "x"

        await db.set_trigger_state_global("g1", "frasi", {"templates": {"DEFAULT": "global"}})
        state2 = await db.get_trigger_state_any_channel("g1", "frasi")
        assert state2.get("templates", {}).get("DEFAULT") == "global"

        await db.close()

    asyncio.run(_run())


def test_register_triggers_keeps_frasi_top_level() -> None:
    from discord import app_commands

    group = app_commands.Group(name="barcellometro", description="x")
    ctx = SimpleNamespace(
        database=Mock(),
        entitlements=SimpleNamespace(resolve_profile=AsyncMock(return_value="mod")),
        timezone=None,
        message_scheduler=None,
        trigger_engine=None,
    )
    frasi_group = register_triggers(group, ctx)

    names = [command.name for command in group.commands]
    assert "frasi" not in names
    assert frasi_group.name == "frasi"
