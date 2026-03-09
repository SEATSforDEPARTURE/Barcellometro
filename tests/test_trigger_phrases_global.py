import asyncio
from datetime import datetime, timezone
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
    def __init__(self, *, author=None) -> None:
        self.replies: list[object] = []
        self.author = author

    async def reply(self, *, embed=None, **kwargs):
        self.replies.append(embed)


class _FakeTextChannel:
    def __init__(self, *, message_author=None, guild=None) -> None:
        self.target = _FakeRepliedMessage(author=message_author)
        self.sent_embeds: list[object] = []
        self.guild = guild

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
    def __init__(self, role_ids: list[int], members: dict[int, _FakeMember] | None = None) -> None:
        self._roles = {role_id: _FakeRole(role_id) for role_id in role_ids}
        self._members = members or {}

    def get_member(self, member_id: int):
        return self._members.get(member_id)

    def get_role(self, role_id: int):
        return self._roles.get(role_id)


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

    await db.set_trigger_enabled("g1", "ch-a", "frasi", True)
    await db.add_trigger_phrase("g1", "ch-a", phrase_text, "CONTAINS", False, "#FFAA00")

    service = TriggerEngineService(db, Mock(), Mock(), Mock(), community_insights=Mock())
    channel = _FakeTextChannel(message_author=message_author, guild=guild or _FakeGuild(role_ids=[], members={}))
    service._bot = _FakeBot(channel)

    envelope = EventEnvelope(
        event_id="evt-1",
        event_type="message.create",
        platform="discord",
        ts="2026-01-01T10:00:00+00:00",
        guild_id="g1",
        channel_id="ch-z",
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

            embed = channel.target.replies[0]
            assert embed.title == "💬 FRASI ICONICHE"
            assert getattr(embed.footer, "text", "") == "Servizio offerto dal vostro Barcellometro di fiducia."
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


def test_per_user_template_has_priority_over_first_and_default() -> None:
    async def _run() -> None:
        original_text_channel = triggers_module.discord.TextChannel
        triggers_module.discord.TextChannel = _FakeTextChannel
        try:
            db = DatabaseService(":memory:")
            await db.connect()
            await db.initialize_schema()
            embed = await _run_phrase_once(
                db,
                author_id="42",
                trigger_state={
                    "templates": {"DEFAULT": "default", "FIRST": "first"},
                    "per_user": {"42": {"FIRST": "ciao {author}", "DEFAULT": "x"}},
                },
            )
            assert embed.description == "ciao <@42>"
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
            await db.set_trigger_enabled("g1", "ch-a", "frasi", True)
            await db.add_trigger_phrase("g1", "ch-a", "il criccy", "CONTAINS", False, None)
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
                    channel_id="ch-z",
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
            assert embed.color.value == 0xFFD700
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
        original_now = triggers_module.datetime.now
        triggers_module.discord.TextChannel = _FakeTextChannel
        try:
            db = DatabaseService(":memory:")
            await db.connect()
            await db.initialize_schema()
            await db.set_trigger_enabled("g1", "ch-a", "frasi", True)
            await db.add_trigger_phrase("g1", "ch-a", "ciao", "CONTAINS", False, None, 120, None)
            await db.set_trigger_state_global("g1", "frasi", {"templates": {"FIRST": "first", "DEFAULT": "default {count_user}"}})

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
            triggers_module.datetime.now = Mock(side_effect=lambda tz=None: next(now_values))

            envelope = EventEnvelope(
                event_id="evt-1",
                event_type="message.create",
                platform="discord",
                ts="2026-01-01T10:00:00+00:00",
                guild_id="g1",
                channel_id="ch-z",
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
            triggers_module.datetime.now = original_now

    asyncio.run(_run())


def test_phrase_roles_allow_and_block_users() -> None:
    async def _run() -> None:
        original_text_channel = triggers_module.discord.TextChannel
        triggers_module.discord.TextChannel = _FakeTextChannel
        try:
            db = DatabaseService(":memory:")
            await db.connect()
            await db.initialize_schema()
            await db.set_trigger_enabled("g1", "ch-a", "frasi", True)
            await db.add_trigger_phrase("g1", "ch-a", "ciao", "CONTAINS", False, None, None, ["100"])

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
                channel_id="ch-z",
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
                channel_id="ch-z",
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
        group = app_commands.Group(name="barcellometro", description="x")
        ctx = SimpleNamespace(
            database=db,
            entitlements=SimpleNamespace(resolve_profile=AsyncMock(return_value="mod")),
            timezone=timezone.utc,
            message_scheduler=Mock(),
            trigger_engine=Mock(),
        )
        frasi_group = register_triggers(group, ctx)
        add_cmd = next(c for c in frasi_group.commands if c.name == "add")
        list_cmd = next(c for c in frasi_group.commands if c.name == "list")

        response = Mock()
        response.send_message = AsyncMock()
        interaction = SimpleNamespace(
            guild_id=1,
            channel_id=2,
            guild=_FakeGuild(role_ids=[123, 456], members={}),
            response=response,
            user=SimpleNamespace(id=99),
        )

        await add_cmd.callback(
            interaction,
            phrase="ciao",
            match_mode=SimpleNamespace(value="CONTAINS"),
            colore="#112233",
            cooldown=120,
            ruoli="<@&123>, 456",
        )
        rows = await db.list_trigger_phrases_guild("1")
        assert rows[0]["cooldown_seconds"] == 120
        assert rows[0]["allowed_role_ids"] == ["123", "456"]

        await list_cmd.callback(interaction)
        calls = response.send_message.await_args_list
        assert "Cooldown: 120s" in calls[0].kwargs["content"] or "Cooldown: 120s" in calls[0].args[0]
        list_text = calls[-1].kwargs.get("content") if calls[-1].kwargs else calls[-1].args[0]
        assert "#" in list_text
        assert "cooldown: 120s" in list_text
        assert "ruoli: <@&123>, <@&456>" in list_text
        await db.close()

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

        group = app_commands.Group(name="barcellometro", description="x")
        ctx = SimpleNamespace(
            database=db,
            entitlements=SimpleNamespace(resolve_profile=AsyncMock(return_value="mod")),
            timezone=timezone.utc,
            message_scheduler=Mock(),
            trigger_engine=Mock(),
        )
        frasi_group = register_triggers(group, ctx)
        edit_cmd = next(c for c in frasi_group.commands if c.name == "edit")

        response = Mock()
        response.send_message = AsyncMock()
        interaction = SimpleNamespace(
            guild_id=1,
            channel_id=2,
            guild=_FakeGuild(role_ids=[999], members={}),
            response=response,
            user=SimpleNamespace(id=99),
        )

        await edit_cmd.callback(
            interaction,
            id=phrase_id,
            frase="ciao aggiornato",
            match_mode=SimpleNamespace(value="REGEX"),
            colore="#445566",
            cooldown=300,
            ruoli="999",
            reset_ruoli=False,
            reset_cooldown=False,
            reset_colore=False,
            attiva=False,
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

        group = app_commands.Group(name="barcellometro", description="x")
        ctx = SimpleNamespace(
            database=db,
            entitlements=SimpleNamespace(resolve_profile=AsyncMock(return_value="mod")),
            timezone=timezone.utc,
            message_scheduler=Mock(),
            trigger_engine=Mock(),
        )
        frasi_group = register_triggers(group, ctx)
        edit_cmd = next(c for c in frasi_group.commands if c.name == "edit")

        response = Mock()
        response.send_message = AsyncMock()
        interaction = SimpleNamespace(
            guild_id=1,
            channel_id=2,
            guild=_FakeGuild(role_ids=[123], members={}),
            response=response,
            user=SimpleNamespace(id=99),
        )

        await edit_cmd.callback(
            interaction,
            id=phrase_id,
            reset_ruoli=True,
            reset_cooldown=True,
            reset_colore=True,
        )
        row_after = await db.get_trigger_phrase_by_id("1", phrase_id)
        assert row_after["allowed_role_ids"] == []
        assert row_after["cooldown_seconds"] is None
        assert row_after["embed_color"] is None

        await edit_cmd.callback(interaction, id=99999)
        msg = response.send_message.await_args_list[-1].kwargs.get("content") or response.send_message.await_args_list[-1].args[0]
        assert "non trovata" in msg.lower()
        await db.close()

    asyncio.run(_run())


def test_phrase_milestone_priority_and_exact_threshold_trigger() -> None:
    async def _run() -> None:
        original_text_channel = triggers_module.discord.TextChannel
        triggers_module.discord.TextChannel = _FakeTextChannel
        try:
            db = DatabaseService(":memory:")
            await db.connect()
            await db.initialize_schema()
            await db.set_trigger_enabled("g1", "ch-a", "frasi", True)
            await db.add_trigger_phrase("g1", "ch-a", "ciao", "CONTAINS", False, None, None, None)
            phrase = await db.fetchone("SELECT id FROM trigger_phrases WHERE guild_id = ? LIMIT 1", ("g1",))
            assert phrase is not None
            phrase_id = int(phrase["id"])
            await db.upsert_trigger_phrase_milestone(phrase_id, 5, "milestone {milestone} {count_user_prev}->{count_user}")
            await db.set_trigger_state_global("g1", "frasi", {"templates": {"FIRST": "first", "DEFAULT": "default {count_user}"}})

            service = TriggerEngineService(db, Mock(), Mock(), Mock(), community_insights=Mock())
            channel = _FakeTextChannel(guild=_FakeGuild(role_ids=[], members={1: _FakeMember(1, [])}))
            service._bot = _FakeBot(channel)
            envelope = EventEnvelope(
                event_id="evt",
                event_type="message.create",
                platform="discord",
                ts="2026-01-01T10:00:00+00:00",
                guild_id="g1",
                channel_id="ch-z",
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


def test_phrase_per_user_template_has_priority_over_milestone() -> None:
    async def _run() -> None:
        original_text_channel = triggers_module.discord.TextChannel
        triggers_module.discord.TextChannel = _FakeTextChannel
        try:
            db = DatabaseService(":memory:")
            await db.connect()
            await db.initialize_schema()
            await db.set_trigger_enabled("g1", "ch-a", "frasi", True)
            await db.add_trigger_phrase("g1", "ch-a", "ciao", "CONTAINS", False, None, None, None)
            phrase = await db.fetchone("SELECT id FROM trigger_phrases WHERE guild_id = ? LIMIT 1", ("g1",))
            assert phrase is not None
            phrase_id = int(phrase["id"])
            await db.upsert_trigger_phrase_milestone(phrase_id, 2, "milestone")
            await db.set_trigger_state_global(
                "g1",
                "frasi",
                {"templates": {"FIRST": "first", "DEFAULT": "default"}, "per_user": {"1": {"DEFAULT": "utente", "FIRST": "utente first"}}},
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
                channel_id="ch-z",
                thread_id=None,
                author_id="1",
                content="ciao",
                meta={"message_id": "123"},
            )
            await service._handle_phrases(envelope)
            await service._handle_phrases(envelope)
            assert channel.target.replies[1].description == "utente"
            await db.close()
        finally:
            triggers_module.discord.TextChannel = original_text_channel

    asyncio.run(_run())


def test_phrase_milestone_not_triggered_when_cooldown_blocks() -> None:
    async def _run() -> None:
        original_text_channel = triggers_module.discord.TextChannel
        original_now = triggers_module.datetime.now
        triggers_module.discord.TextChannel = _FakeTextChannel
        try:
            db = DatabaseService(":memory:")
            await db.connect()
            await db.initialize_schema()
            await db.set_trigger_enabled("g1", "ch-a", "frasi", True)
            await db.add_trigger_phrase("g1", "ch-a", "ciao", "CONTAINS", False, None, 120, None)
            phrase = await db.fetchone("SELECT id FROM trigger_phrases WHERE guild_id = ? LIMIT 1", ("g1",))
            assert phrase is not None
            phrase_id = int(phrase["id"])
            await db.upsert_trigger_phrase_milestone(phrase_id, 2, "milestone")
            await db.set_trigger_state_global("g1", "frasi", {"templates": {"FIRST": "first", "DEFAULT": "default"}})

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
            triggers_module.datetime.now = Mock(side_effect=lambda tz=None: next(now_values))
            envelope = EventEnvelope(
                event_id="evt",
                event_type="message.create",
                platform="discord",
                ts="2026-01-01T10:00:00+00:00",
                guild_id="g1",
                channel_id="ch-z",
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
            triggers_module.datetime.now = original_now

    asyncio.run(_run())


def test_frasi_stats_and_milestone_commands() -> None:
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

        group = app_commands.Group(name="barcellometro", description="x")
        ctx = SimpleNamespace(
            database=db,
            entitlements=SimpleNamespace(resolve_profile=AsyncMock(return_value="mod")),
            timezone=timezone.utc,
            message_scheduler=Mock(),
            trigger_engine=Mock(),
        )
        frasi_group = register_triggers(group, ctx)
        stats_cmd = next(c for c in frasi_group.commands if c.name == "stats")
        set_cmd = next(c for c in frasi_group.commands if c.name == "milestone_set")
        list_cmd = next(c for c in frasi_group.commands if c.name == "milestone_list")
        remove_cmd = next(c for c in frasi_group.commands if c.name == "milestone_remove")

        response = Mock()
        response.send_message = AsyncMock()
        guild = _FakeGuild(role_ids=[1], members={10: _FakeMember(10, []), 11: _FakeMember(11, [])})
        interaction = SimpleNamespace(guild_id=1, channel_id=2, guild=guild, response=response, user=SimpleNamespace(id=99))

        await stats_cmd.callback(interaction, id=phrase_id)
        kwargs = response.send_message.await_args_list[-1].kwargs
        embed = kwargs["embed"]
        assert embed.title == f"📊 STATISTICHE FRASE #{phrase_id}"
        field_values = {f.name: f.value for f in embed.fields}
        assert field_values["Utenti unici"] == "2"
        assert field_values["Utilizzi totali"] == "3"

        await set_cmd.callback(interaction, id=phrase_id, soglia=10, testo="dieci")
        await set_cmd.callback(interaction, id=phrase_id, soglia=5, testo="cinque")
        milestones = await db.list_trigger_phrase_milestones(phrase_id)
        assert [int(m["threshold_count"]) for m in milestones] == [5, 10]

        await list_cmd.callback(interaction, id=phrase_id)
        text = response.send_message.await_args_list[-1].kwargs.get("content") or response.send_message.await_args_list[-1].args[0]
        assert "5 →" in text and "10 →" in text

        await remove_cmd.callback(interaction, id=phrase_id, soglia=5)
        milestones_after = await db.list_trigger_phrase_milestones(phrase_id)
        assert [int(m["threshold_count"]) for m in milestones_after] == [10]
        await db.close()

    asyncio.run(_run())
