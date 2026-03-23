import asyncio
import sys
import types
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Iterator
from unittest.mock import AsyncMock, Mock

import pytest

from tests._sqlite_stub import ensure_sqlite_stub

ensure_sqlite_stub()

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.AsyncOpenAI = object
    sys.modules["openai"] = openai_stub

if "httpx" not in sys.modules:
    httpx_stub = types.ModuleType("httpx")
    httpx_stub.AsyncClient = object
    httpx_stub.Client = object
    sys.modules["httpx"] = httpx_stub

pytest.importorskip("aiosqlite")

from app.plugins.commands_modular.triggers import register_triggers
import app.plugins.commands_modular.triggers as trigger_commands_module
from app.services.database import DatabaseService
from app.services.ingest import EventEnvelope
from app.services.triggers_service import TriggerEngineService
import app.services.triggers_service as triggers_module


class _FakeRepliedMessage:
    def __init__(self, *, author=None) -> None:
        self.replies: list[object] = []
        self.author = author

    async def reply(self, *, embed=None, **kwargs):
        self.replies.append(embed)


class _FakeTextChannel:
    def __init__(self, *, message_author=None, guild=None) -> None:
        self.target = _FakeRepliedMessage(author=message_author)
        self.sent_embeds: list[object] = []
        self.guild = guild or _FakeGuild(role_ids=[], members={})

    async def fetch_message(self, _message_id: int):
        return self.target

    async def send(self, *, embed=None, **kwargs):
        self.sent_embeds.append(embed)


class _FakeBot:
    def __init__(self, channel: _FakeTextChannel) -> None:
        self._channel = channel

    def get_channel(self, _channel_id: int):
        return self._channel


class _FakeRole:
    def __init__(self, role_id: int) -> None:
        self.id = role_id


class _FakeMember:
    def __init__(self, member_id: int, role_ids: list[int]) -> None:
        self.id = member_id
        self.roles = [_FakeRole(role_id) for role_id in role_ids]
        self.display_name = f"member-{member_id}"
        self.mention = f"<@{member_id}>"


class _FakeGuild:
    def __init__(self, role_ids: list[int], members: dict[int, _FakeMember] | None = None, guild_id: int = 1) -> None:
        self.id = guild_id
        self._roles = {role_id: _FakeRole(role_id) for role_id in role_ids}
        self._members = members or {}

    def get_member(self, member_id: int):
        return self._members.get(member_id)

    def get_role(self, role_id: int):
        return self._roles.get(role_id)


class _FakeDatetime:
    _values: Iterator[datetime] | None = None
    _last_value: datetime | None = None

    @classmethod
    def set_values(cls, values) -> None:
        cls._values = iter(values)
        cls._last_value = None

    @classmethod
    def now(cls, tz=None):
        assert cls._values is not None
        try:
            value = next(cls._values)
            cls._last_value = value
        except StopIteration:
            assert cls._last_value is not None
            value = cls._last_value
        return value if tz is None else value.astimezone(tz)

    @staticmethod
    def fromisoformat(value: str):
        return datetime.fromisoformat(value)


async def _run_phrase_once(
    db: DatabaseService,
    *,
    phrase_text: str = "il criccy",
    content: str = "oggi dico il criccy",
    author_id: str = "u1",
    trigger_state: dict | None = None,
    message_author: object | None = None,
    guild: object | None = None,
) -> object:
    if trigger_state is not None:
        await db.set_trigger_state_global("g1", "frasi", trigger_state)

    await db.set_trigger_enabled("g1", "101", "frasi", True)
    await db.add_trigger_phrase("g1", "101", phrase_text, "CONTAINS", False, "#FFAA00")

    service = TriggerEngineService(db, Mock(), Mock(), Mock(), community_insights=Mock())
    channel = _FakeTextChannel(message_author=message_author, guild=guild or _FakeGuild(role_ids=[], members={}))
    service._bot = _FakeBot(channel)

    envelope = EventEnvelope(
        event_id="evt-1",
        event_type="message.create",
        platform="discord",
        ts="2026-01-01T10:00:00+00:00",
        guild_id="g1",
        channel_id="102",
        thread_id=None,
        author_id=author_id,
        content=content,
        meta={"message_id": "123"},
    )
    await service._handle_phrases(envelope)
    assert len(channel.target.replies) == 1
    return channel.target.replies[0]


def test_phrases_are_guild_wide_with_dedup_and_embed() -> None:
    async def _run() -> None:
        original_text_channel = triggers_module.discord.TextChannel
        triggers_module.discord.TextChannel = _FakeTextChannel
        try:
            db = DatabaseService(":memory:")
            await db.connect()
            await db.initialize_schema()
            await db.set_trigger_enabled("g1", "101", "frasi", True)

            await db.add_trigger_phrase("g1", "101", "il criccy", "CONTAINS", False, "#FFAA00")
            await db.add_trigger_phrase("g1", "103", "il criccy", "CONTAINS", False, "#00AA00")

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
                channel_id="102",
                thread_id=None,
                author_id="u1",
                content="oggi dico IL CRICCY sempre",
                meta={"message_id": "123"},
            )
            await service._handle_phrases(envelope)

            embed = channel.target.replies[0]
            assert embed.title == "💬 FRASI ICONICHE"
            assert getattr(embed.footer, "text", None) in ("", None)
            assert embed.color.value == 0xFFAA00

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


def test_embed_description_uses_default_template_not_raw_phrase() -> None:
    async def _run() -> None:
        original_text_channel = triggers_module.discord.TextChannel
        triggers_module.discord.TextChannel = _FakeTextChannel
        try:
            db = DatabaseService(":memory:")
            await db.connect()
            await db.initialize_schema()
            embed = await _run_phrase_once(
                db,
                trigger_state={"templates": {"DEFAULT": "template default {count_user}", "FIRST": "template first"}},
            )
            assert embed.description == "template first"
            embed2 = await _run_phrase_once(
                db,
                trigger_state={"templates": {"DEFAULT": "template default {count_user}", "FIRST": "template first"}},
            )
            assert embed2.description == "template default 2"
            await db.close()
        finally:
            triggers_module.discord.TextChannel = original_text_channel

    asyncio.run(_run())


def test_custom_user_phrase_is_rendered_in_template() -> None:
    async def _run() -> None:
        original_text_channel = triggers_module.discord.TextChannel
        triggers_module.discord.TextChannel = _FakeTextChannel
        try:
            db = DatabaseService(":memory:")
            await db.connect()
            await db.initialize_schema()
            await db.upsert_trigger_phrase_global_user_custom_text("g1", "42", "Che micia")
            embed = await _run_phrase_once(
                db,
                author_id="42",
                trigger_state={
                    "templates": {"DEFAULT": "default {custom_user_phrase}", "FIRST": "first {custom_user_phrase}"},
                },
            )
            assert embed.description == "first Che micia"
            await db.close()
        finally:
            triggers_module.discord.TextChannel = original_text_channel

    asyncio.run(_run())


def test_template_fallback_does_not_break_trigger() -> None:
    async def _run() -> None:
        original_text_channel = triggers_module.discord.TextChannel
        triggers_module.discord.TextChannel = _FakeTextChannel
        try:
            db = DatabaseService(":memory:")
            await db.connect()
            await db.initialize_schema()
            await db.set_trigger_enabled("g1", "101", "frasi", True)
            await db.add_trigger_phrase("g1", "101", "il criccy", "CONTAINS", False, None)
            await db.set_trigger_state_global("g1", "frasi", {"templates": {"FIRST": "ok"}})

            service = TriggerEngineService(db, Mock(), Mock(), Mock(), community_insights=Mock())
            channel = _FakeTextChannel()
            service._bot = _FakeBot(channel)

            original_render = service._render_phrase_template
            service._render_phrase_template = Mock(side_effect=RuntimeError("boom"))
            try:
                envelope = EventEnvelope(
                    event_id="evt-1",
                    event_type="message.create",
                    platform="discord",
                    ts="2026-01-01T10:00:00+00:00",
                    guild_id="g1",
                    channel_id="102",
                    thread_id=None,
                    author_id="u1",
                    content="oggi dico il criccy",
                    meta={"message_id": "123"},
                )
                await service._handle_phrases(envelope)
            finally:
                service._render_phrase_template = original_render

            embed = channel.target.replies[0]
            assert embed.description == "il criccy"
            assert embed.color.value == 0xF1C40F
            await db.close()
        finally:
            triggers_module.discord.TextChannel = original_text_channel

    asyncio.run(_run())


def test_author_name_placeholder_prefers_display_name_then_name_then_default() -> None:
    async def _run() -> None:
        original_text_channel = triggers_module.discord.TextChannel
        triggers_module.discord.TextChannel = _FakeTextChannel
        try:
            db = DatabaseService(":memory:")
            await db.connect()
            await db.initialize_schema()

            embed_display = await _run_phrase_once(
                db,
                author_id="100",
                trigger_state={"templates": {"FIRST": "ciao {author_name}"}},
                message_author=SimpleNamespace(display_name="Display Hero", name="RawName"),
            )
            assert embed_display.description == "ciao Display Hero"

            embed_name = await _run_phrase_once(
                db,
                author_id="101",
                trigger_state={"templates": {"FIRST": "ciao {author_name}"}},
                message_author=SimpleNamespace(display_name=None, name="OnlyName"),
            )
            assert embed_name.description == "ciao OnlyName"

            embed_default = await _run_phrase_once(
                db,
                author_id=None,
                trigger_state={"templates": {"FIRST": "ciao {author_name}"}},
                message_author=SimpleNamespace(display_name=None, name=None),
            )
            assert embed_default.description == "ciao utente"

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


def test_register_triggers_returns_phrases_subgroup_under_triggers() -> None:
    from discord import app_commands

    group = app_commands.Group(name="admin", description="x")
    ctx = SimpleNamespace(
        database=Mock(),
        entitlements=SimpleNamespace(resolve_profile=AsyncMock(return_value="mod")),
        timezone=None,
        message_scheduler=None,
        trigger_engine=None,
    )
    frasi_group = register_triggers(group, app_commands.Group(name="campagne", description="x"), app_commands.Group(name="qna", description="x"), app_commands.Group(name="insights", description="x"), ctx)

    names = [command.name for command in group.commands]
    assert "frasi" not in names
    assert frasi_group.name == "phrases"


def test_db_trigger_phrase_columns_backcompat_and_serialization() -> None:
    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()

        await db.add_trigger_phrase("g1", "c1", "frase", "CONTAINS", False, None, 120, ["123", 456])
        rows = await db.list_trigger_phrases_guild("g1")
        assert rows[0]["cooldown_seconds"] == 120
        assert rows[0]["allowed_role_ids"] == ["123", "456"]

        await db.close()

    asyncio.run(_run())


def test_phrase_cooldown_blocks_second_hit_and_does_not_consume_first() -> None:
    async def _run() -> None:
        original_text_channel = triggers_module.discord.TextChannel
        original_datetime = triggers_module.datetime
        triggers_module.discord.TextChannel = _FakeTextChannel
        try:
            db = DatabaseService(":memory:")
            await db.connect()
            await db.initialize_schema()
            await db.set_trigger_enabled("g1", "101", "frasi", True)
            await db.add_trigger_phrase("g1", "101", "ciao", "CONTAINS", False, None, 120, None)
            await db.set_trigger_state_global("g1", "frasi", {"templates": {"FIRST": "first", "DEFAULT": "default {count_user}"}, "global_milestones_enabled": True})

            service = TriggerEngineService(db, Mock(), Mock(), Mock(), community_insights=Mock())
            channel = _FakeTextChannel(guild=_FakeGuild(role_ids=[], members={1: _FakeMember(1, [])}))
            service._bot = _FakeBot(channel)

            now_values = iter(
                [
                    datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
                    datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
                    datetime(2026, 1, 1, 10, 1, 0, tzinfo=timezone.utc),
                    datetime(2026, 1, 1, 10, 3, 1, tzinfo=timezone.utc),
                    datetime(2026, 1, 1, 10, 3, 1, tzinfo=timezone.utc),
                ]
            )
            _FakeDatetime.set_values(now_values)
            triggers_module.datetime = _FakeDatetime

            envelope = EventEnvelope(
                event_id="evt-1",
                event_type="message.create",
                platform="discord",
                ts="2026-01-01T10:00:00+00:00",
                guild_id="g1",
                channel_id="102",
                thread_id=None,
                author_id="1",
                content="ciao a tutti",
                meta={"message_id": "123"},
            )
            await service._handle_phrases(envelope)
            await service._handle_phrases(envelope)
            await service._handle_phrases(envelope)

            assert len(channel.target.replies) == 2
            assert channel.target.replies[0].description == "first"
            assert channel.target.replies[1].description == "default 2"

            phrase_row = await db.fetchone("SELECT id FROM trigger_phrases WHERE guild_id = ? LIMIT 1", ("g1",))
            assert phrase_row is not None
            stats = await db.get_phrase_user_stats(int(phrase_row["id"]), "1")
            assert int(stats.get("count") or 0) == 2
            await db.close()
        finally:
            triggers_module.discord.TextChannel = original_text_channel
            triggers_module.datetime = original_datetime

    asyncio.run(_run())


def test_phrase_roles_allow_and_block_users() -> None:
    async def _run() -> None:
        original_text_channel = triggers_module.discord.TextChannel
        triggers_module.discord.TextChannel = _FakeTextChannel
        try:
            db = DatabaseService(":memory:")
            await db.connect()
            await db.initialize_schema()
            await db.set_trigger_enabled("g1", "101", "frasi", True)
            await db.add_trigger_phrase("g1", "101", "ciao", "CONTAINS", False, None, None, ["100"])

            service = TriggerEngineService(db, Mock(), Mock(), Mock(), community_insights=Mock())
            guild = _FakeGuild(
                role_ids=[100],
                members={1: _FakeMember(1, [100]), 2: _FakeMember(2, [200])},
            )
            channel = _FakeTextChannel(guild=guild)
            service._bot = _FakeBot(channel)

            allowed = EventEnvelope(
                event_id="evt-1",
                event_type="message.create",
                platform="discord",
                ts="2026-01-01T10:00:00+00:00",
                guild_id="g1",
                channel_id="102",
                thread_id=None,
                author_id="1",
                content="ciao",
                meta={"message_id": "123"},
            )
            blocked = EventEnvelope(
                event_id="evt-2",
                event_type="message.create",
                platform="discord",
                ts="2026-01-01T10:00:01+00:00",
                guild_id="g1",
                channel_id="102",
                thread_id=None,
                author_id="2",
                content="ciao",
                meta={"message_id": "124"},
            )
            await service._handle_phrases(allowed)
            await service._handle_phrases(blocked)

            assert len(channel.target.replies) == 1
            phrase_row = await db.fetchone("SELECT id FROM trigger_phrases WHERE guild_id = ? LIMIT 1", ("g1",))
            assert phrase_row is not None
            assert int((await db.get_phrase_user_stats(int(phrase_row["id"]), "1")).get("count") or 0) == 1
            assert (await db.get_phrase_user_stats(int(phrase_row["id"]), "2")) == {}
            await db.close()
        finally:
            triggers_module.discord.TextChannel = original_text_channel

    asyncio.run(_run())


def test_frasi_add_and_list_include_cooldown_and_roles() -> None:
    async def _run() -> None:
        from discord import app_commands

        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()
        group = app_commands.Group(name="admin", description="x")
        ctx = SimpleNamespace(
            database=db,
            entitlements=SimpleNamespace(resolve_profile=AsyncMock(return_value="mod")),
            timezone=timezone.utc,
            message_scheduler=Mock(),
            trigger_engine=Mock(),
            footer=None,
        )
        old_permission = trigger_commands_module.check_permission
        trigger_commands_module.check_permission = AsyncMock(return_value=True)
        frasi_group = register_triggers(group, app_commands.Group(name="campagne", description="x"), app_commands.Group(name="qna", description="x"), app_commands.Group(name="insights", description="x"), ctx)
        add_cmd = next(c for c in frasi_group.commands if c.name == "entry_add")
        list_cmd = next(c for c in frasi_group.commands if c.name == "entry_list")

        response = Mock()
        response.send_message = AsyncMock()
        response.is_done = Mock(return_value=False)
        interaction = SimpleNamespace(
            guild_id=1,
            channel_id=2,
            guild=_FakeGuild(role_ids=[123, 456], members={}),
            response=response,
            user=SimpleNamespace(id=99),
        )
        try:
            await add_cmd.callback(
                interaction,
                phrase="ciao",
                match_mode=SimpleNamespace(value="CONTAINS"),
                color="#112233",
                cooldown_seconds=120,
                role_ids="123, 456",
            )
            rows = await db.list_trigger_phrases_guild("1")
            assert rows[0]["cooldown_seconds"] == 120
            assert rows[0]["allowed_role_ids"] == ["123", "456"]

            await list_cmd.callback(interaction)
            sent_embed = response.send_message.await_args_list[-1].kwargs["embed"]
            description = sent_embed.description or ""
            assert "#" in description
            assert "cooldown: 120s" in description
            assert "roles: <@&123>, <@&456>" in description
            await db.close()
        finally:
            trigger_commands_module.check_permission = old_permission

    asyncio.run(_run())


def test_frasi_edit_updates_in_place_and_preserves_stats() -> None:
    async def _run() -> None:
        from discord import app_commands

        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()
        await db.add_trigger_phrase("1", "2", "ciao", "CONTAINS", False, "#112233", 120, ["123"])
        row_before = await db.fetchone("SELECT id FROM trigger_phrases WHERE guild_id = ? LIMIT 1", ("1",))
        assert row_before is not None
        phrase_id = int(row_before["id"])
        await db.increment_phrase_user_stats(phrase_id, "u-1", "2026-01-01T10:00:00+00:00", "m1")

        group = app_commands.Group(name="admin", description="x")
        ctx = SimpleNamespace(
            database=db,
            entitlements=SimpleNamespace(resolve_profile=AsyncMock(return_value="mod")),
            timezone=timezone.utc,
            message_scheduler=Mock(),
            trigger_engine=Mock(),
            footer=None,
        )
        old_permission = trigger_commands_module.check_permission
        trigger_commands_module.check_permission = AsyncMock(return_value=True)
        frasi_group = register_triggers(group, app_commands.Group(name="campagne", description="x"), app_commands.Group(name="qna", description="x"), app_commands.Group(name="insights", description="x"), ctx)
        edit_cmd = next(c for c in frasi_group.commands if c.name == "entry_edit")

        response = Mock()
        response.send_message = AsyncMock()
        response.is_done = Mock(return_value=False)
        interaction = SimpleNamespace(
            guild_id=1,
            channel_id=2,
            guild=_FakeGuild(role_ids=[999], members={}),
            response=response,
            user=SimpleNamespace(id=99),
        )
        try:
            await edit_cmd.callback(
                interaction,
                id=phrase_id,
                phrase="ciao aggiornato",
                match_mode=SimpleNamespace(value="REGEX"),
                color="#445566",
                cooldown_seconds=300,
                role_ids="999",
                reset_role_ids=False,
                reset_cooldown=False,
                reset_color=False,
                enabled=False,
            )
            row_after = await db.get_trigger_phrase_by_id("1", phrase_id)
            assert row_after["id"] == phrase_id
            assert row_after["phrase"] == "ciao aggiornato"
            assert row_after["match_mode"] == "REGEX"
            assert row_after["embed_color"] == "#445566"
            assert row_after["cooldown_seconds"] == 300
            assert row_after["allowed_role_ids"] == ["999"]
            assert int(row_after["enabled"]) == 0

            stats = await db.get_phrase_user_stats(phrase_id, "u-1")
            assert int(stats.get("count") or 0) == 1
            await db.close()
        finally:
            trigger_commands_module.check_permission = old_permission

    asyncio.run(_run())


def test_frasi_edit_reset_fields_and_missing_id() -> None:
    async def _run() -> None:
        from discord import app_commands

        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()
        await db.add_trigger_phrase("1", "2", "ciao", "CONTAINS", False, "#112233", 120, ["123"])
        row_before = await db.fetchone("SELECT id FROM trigger_phrases WHERE guild_id = ? LIMIT 1", ("1",))
        assert row_before is not None
        phrase_id = int(row_before["id"])

        group = app_commands.Group(name="admin", description="x")
        ctx = SimpleNamespace(
            database=db,
            entitlements=SimpleNamespace(resolve_profile=AsyncMock(return_value="mod")),
            timezone=timezone.utc,
            message_scheduler=Mock(),
            trigger_engine=Mock(),
            footer=None,
        )
        old_permission = trigger_commands_module.check_permission
        trigger_commands_module.check_permission = AsyncMock(return_value=True)
        frasi_group = register_triggers(group, app_commands.Group(name="campagne", description="x"), app_commands.Group(name="qna", description="x"), app_commands.Group(name="insights", description="x"), ctx)
        edit_cmd = next(c for c in frasi_group.commands if c.name == "entry_edit")

        response = Mock()
        response.send_message = AsyncMock()
        response.is_done = Mock(return_value=False)
        interaction = SimpleNamespace(
            guild_id=1,
            channel_id=2,
            guild=_FakeGuild(role_ids=[123], members={}),
            response=response,
            user=SimpleNamespace(id=99),
        )
        try:
            await edit_cmd.callback(
                interaction,
                id=phrase_id,
                reset_role_ids=True,
                reset_cooldown=True,
                reset_color=True,
            )
            row_after = await db.get_trigger_phrase_by_id("1", phrase_id)
            assert row_after["allowed_role_ids"] == []
            assert row_after["cooldown_seconds"] is None
            assert row_after["embed_color"] is None

            await edit_cmd.callback(interaction, id=99999)
            sent_embed = response.send_message.await_args_list[-1].kwargs["embed"]
            assert "not found" in (sent_embed.description or "").lower()
            await db.close()
        finally:
            trigger_commands_module.check_permission = old_permission

    asyncio.run(_run())


def test_phrase_global_milestone_priority_and_exact_threshold_trigger() -> None:
    async def _run() -> None:
        original_text_channel = triggers_module.discord.TextChannel
        triggers_module.discord.TextChannel = _FakeTextChannel
        try:
            db = DatabaseService(":memory:")
            await db.connect()
            await db.initialize_schema()
            await db.set_trigger_enabled("g1", "101", "frasi", True)
            await db.add_trigger_phrase("g1", "101", "ciao", "CONTAINS", False, None, None, None)
            phrase = await db.fetchone("SELECT id FROM trigger_phrases WHERE guild_id = ? LIMIT 1", ("g1",))
            assert phrase is not None
            phrase_id = int(phrase["id"])
            await db.set_trigger_phrase_global_milestone("g1", 5, "milestone {milestone} {count_user_prev}->{count_user}")
            await db.set_trigger_state_global("g1", "frasi", {"templates": {"FIRST": "first", "DEFAULT": "default {count_user}"}, "global_milestones_enabled": True})

            service = TriggerEngineService(db, Mock(), Mock(), Mock(), community_insights=Mock())
            channel = _FakeTextChannel(guild=_FakeGuild(role_ids=[], members={1: _FakeMember(1, [])}))
            service._bot = _FakeBot(channel)
            envelope = EventEnvelope(
                event_id="evt",
                event_type="message.create",
                platform="discord",
                ts="2026-01-01T10:00:00+00:00",
                guild_id="g1",
                channel_id="102",
                thread_id=None,
                author_id="1",
                content="ciao",
                meta={"message_id": "123"},
            )
            for _ in range(6):
                await service._handle_phrases(envelope)

            assert channel.target.replies[0].description == "first"
            assert channel.target.replies[4].description == "milestone 5 4->5"
            assert channel.target.replies[5].description == "default 6"
            await db.close()
        finally:
            triggers_module.discord.TextChannel = original_text_channel

    asyncio.run(_run())


def test_custom_user_phrase_works_inside_global_milestone() -> None:
    async def _run() -> None:
        original_text_channel = triggers_module.discord.TextChannel
        triggers_module.discord.TextChannel = _FakeTextChannel
        try:
            db = DatabaseService(":memory:")
            await db.connect()
            await db.initialize_schema()
            await db.set_trigger_enabled("g1", "101", "frasi", True)
            await db.add_trigger_phrase("g1", "101", "ciao", "CONTAINS", False, None, None, None)
            phrase = await db.fetchone("SELECT id FROM trigger_phrases WHERE guild_id = ? LIMIT 1", ("g1",))
            assert phrase is not None
            phrase_id = int(phrase["id"])
            await db.set_trigger_phrase_global_milestone("g1", 2, "milestone {custom_user_phrase}")
            await db.upsert_trigger_phrase_global_user_custom_text("g1", "1", "Che micia")
            await db.set_trigger_state_global(
                "g1",
                "frasi",
                {"templates": {"FIRST": "first", "DEFAULT": "default"}, "global_milestones_enabled": True},
            )
            service = TriggerEngineService(db, Mock(), Mock(), Mock(), community_insights=Mock())
            channel = _FakeTextChannel(guild=_FakeGuild(role_ids=[], members={1: _FakeMember(1, [])}))
            service._bot = _FakeBot(channel)
            envelope = EventEnvelope(
                event_id="evt",
                event_type="message.create",
                platform="discord",
                ts="2026-01-01T10:00:00+00:00",
                guild_id="g1",
                channel_id="102",
                thread_id=None,
                author_id="1",
                content="ciao",
                meta={"message_id": "123"},
            )
            await service._handle_phrases(envelope)
            await service._handle_phrases(envelope)
            assert channel.target.replies[1].description == "milestone Che micia"
            await db.close()
        finally:
            triggers_module.discord.TextChannel = original_text_channel

    asyncio.run(_run())


def test_phrase_global_milestone_not_triggered_when_cooldown_blocks() -> None:
    async def _run() -> None:
        original_text_channel = triggers_module.discord.TextChannel
        original_datetime = triggers_module.datetime
        triggers_module.discord.TextChannel = _FakeTextChannel
        try:
            db = DatabaseService(":memory:")
            await db.connect()
            await db.initialize_schema()
            await db.set_trigger_enabled("g1", "101", "frasi", True)
            await db.add_trigger_phrase("g1", "101", "ciao", "CONTAINS", False, None, 120, None)
            phrase = await db.fetchone("SELECT id FROM trigger_phrases WHERE guild_id = ? LIMIT 1", ("g1",))
            assert phrase is not None
            phrase_id = int(phrase["id"])
            await db.set_trigger_phrase_global_milestone("g1", 2, "milestone")
            await db.set_trigger_state_global("g1", "frasi", {"templates": {"FIRST": "first", "DEFAULT": "default"}, "global_milestones_enabled": True})

            service = TriggerEngineService(db, Mock(), Mock(), Mock(), community_insights=Mock())
            channel = _FakeTextChannel(guild=_FakeGuild(role_ids=[], members={1: _FakeMember(1, [])}))
            service._bot = _FakeBot(channel)
            now_values = iter(
                [
                    datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
                    datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
                    datetime(2026, 1, 1, 10, 1, 0, tzinfo=timezone.utc),
                ]
            )
            _FakeDatetime.set_values(now_values)
            triggers_module.datetime = _FakeDatetime
            envelope = EventEnvelope(
                event_id="evt",
                event_type="message.create",
                platform="discord",
                ts="2026-01-01T10:00:00+00:00",
                guild_id="g1",
                channel_id="102",
                thread_id=None,
                author_id="1",
                content="ciao",
                meta={"message_id": "123"},
            )
            await service._handle_phrases(envelope)
            await service._handle_phrases(envelope)
            assert len(channel.target.replies) == 1
            stats = await db.get_phrase_user_stats(phrase_id, "1")
            assert int(stats.get("count") or 0) == 1
            await db.close()
        finally:
            triggers_module.discord.TextChannel = original_text_channel
            triggers_module.datetime = original_datetime

    asyncio.run(_run())


def test_frasi_milestone_commands() -> None:
    async def _run() -> None:
        from discord import app_commands

        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()
        await db.add_trigger_phrase("1", "2", "ciao", "CONTAINS", False)
        phrase = await db.fetchone("SELECT id FROM trigger_phrases WHERE guild_id = ? LIMIT 1", ("1",))
        assert phrase is not None
        phrase_id = int(phrase["id"])
        await db.increment_phrase_user_stats(phrase_id, "10", "2026-01-01T10:00:00+00:00", "m1")
        await db.increment_phrase_user_stats(phrase_id, "10", "2026-01-01T11:00:00+00:00", "m2")
        await db.increment_phrase_user_stats(phrase_id, "11", "2026-01-01T12:00:00+00:00", "m3")

        group = app_commands.Group(name="admin", description="x")
        ctx = SimpleNamespace(
            database=db,
            entitlements=SimpleNamespace(resolve_profile=AsyncMock(return_value="mod")),
            timezone=timezone.utc,
            message_scheduler=Mock(),
            trigger_engine=Mock(),
            footer=None,
        )
        old_permission = trigger_commands_module.check_permission
        trigger_commands_module.check_permission = AsyncMock(return_value=True)
        frasi_group = register_triggers(group, app_commands.Group(name="campagne", description="x"), app_commands.Group(name="qna", description="x"), app_commands.Group(name="insights", description="x"), ctx)
        set_cmd = next(c for c in frasi_group.commands if c.name == "template_milestone_set")
        list_cmd = next(c for c in frasi_group.commands if c.name == "template_milestone_show")
        remove_cmd = next(c for c in frasi_group.commands if c.name == "template_milestone_reset")

        response = Mock()
        response.send_message = AsyncMock()
        response.is_done = Mock(return_value=False)
        guild = _FakeGuild(role_ids=[1], members={10: _FakeMember(10, []), 11: _FakeMember(11, [])})
        interaction = SimpleNamespace(guild_id=1, channel_id=2, guild=guild, response=response, user=SimpleNamespace(id=99))
        try:
            await set_cmd.callback(interaction, threshold=10, text="dieci")
            await set_cmd.callback(interaction, threshold=5, text="cinque")
            milestones = await db.list_trigger_phrase_global_milestones("1")
            assert [int(m["threshold_count"]) for m in milestones] == [5, 10]

            await list_cmd.callback(interaction)
            sent_embed = response.send_message.await_args_list[-1].kwargs["embed"]
            description = sent_embed.description or ""
            assert "5 -> cinque" in description and "10 -> dieci" in description

            await remove_cmd.callback(interaction)
            milestones_after = await db.list_trigger_phrase_global_milestones("1")
            assert milestones_after == []
            await db.close()
        finally:
            trigger_commands_module.check_permission = old_permission

    asyncio.run(_run())


def test_template_set_user_command_is_not_registered() -> None:
    async def _run() -> None:
        from discord import app_commands

        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()
        group = app_commands.Group(name="admin", description="x")
        ctx = SimpleNamespace(
            database=db,
            entitlements=SimpleNamespace(resolve_profile=AsyncMock(return_value="mod")),
            timezone=timezone.utc,
            message_scheduler=Mock(),
            trigger_engine=Mock(),
            footer=None,
        )
        frasi_group = register_triggers(group, app_commands.Group(name="campagne", description="x"), app_commands.Group(name="qna", description="x"), app_commands.Group(name="insights", description="x"), ctx)
        names = {command.name for command in frasi_group.commands}
        assert "template_set_user" not in names
        await db.close()

    asyncio.run(_run())


def test_register_triggers_permission_candidates_use_admin_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from discord import app_commands

    seen: list[tuple[str, tuple[str, ...]]] = []

    async def _check_permission(interaction, command_name, ctx):
        seen.append(command_name)
        return True

    monkeypatch.setattr(trigger_commands_module, "check_permission", _check_permission)

    class _Db:
        async def list_message_campaigns(self, guild_id: str, include_disabled: bool = True):
            _ = guild_id, include_disabled
            return []

    admin_group = app_commands.Group(name="admin", description="x")
    campagne_group = app_commands.Group(name="campagne", description="x")
    qna_group = app_commands.Group(name="qna", description="x")
    insights_group = app_commands.Group(name="insights", description="x")
    ctx = SimpleNamespace(database=_Db(), footer=None, guard=None, timezone=None, message_scheduler=None, trigger_engine=None)

    register_triggers(admin_group, campagne_group, qna_group, insights_group, ctx)
    prompt_group = next(cmd for cmd in campagne_group.commands if isinstance(cmd, app_commands.Group) and cmd.name == "prompt")
    prompt_show = next(cmd for cmd in prompt_group.commands if cmd.name == "schedule_show")

    async def _get_message_campaign(self, guild_id, id):
        return None

    ctx.database.get_message_campaign = types.MethodType(_get_message_campaign, ctx.database)
    interaction = SimpleNamespace(
        guild_id=1,
        channel_id=2,
        command=SimpleNamespace(qualified_name="admin prompt schedule_show"),
        data={"name": "schedule_show"},
        response=SimpleNamespace(send_message=AsyncMock(), is_done=lambda: False),
    )
    asyncio.run(prompt_show.callback(interaction, "5"))

    assert seen == ["admin.campaigns.prompt.schedule_show"]
