import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from app.core.service_registry import ServiceRegistry
from app.plugins.discord_adapter import setup as setup_discord_adapter
from app.services.database import DatabaseService
from app.services.footer import FooterService, attach_footer_meta
from app.services.message_scheduler import MessageSchedulerService


class _FakeBot:
    def __init__(self) -> None:
        self.listeners = {}
        self._channels = {}

    def add_listener(self, fn, name):
        self.listeners[name] = fn

    def event(self, fn):
        self.listeners[fn.__name__] = fn
        return fn

    def get_channel(self, channel_id: int):
        return self._channels.get(channel_id)

    async def fetch_channel(self, channel_id: int):
        return self._channels[channel_id]

    def get_guild(self, guild_id: int):
        return SimpleNamespace(id=guild_id, name="Guild")


class _FakeChannel(discord.abc.Messageable):
    def __init__(self, channel_id: int = 10) -> None:
        self.id = channel_id
        self.guild = SimpleNamespace(id=99)
        self.name = "general"
        self.type = "text"
        self.category_id = None
        self.slowmode_delay = 0

    def is_nsfw(self):
        return False

    async def _get_channel(self):  # pragma: no cover
        return self


class _FakeMessageChannel(_FakeChannel):
    async def send(self, **kwargs):
        raise RuntimeError("downstream failure")


def _base_registry(database) -> tuple[ServiceRegistry, _FakeBot]:
    registry = ServiceRegistry()
    bot = _FakeBot()
    registry.register("bot", bot)
    registry.register("database", database)
    registry.register("ingest", SimpleNamespace(emit=AsyncMock(), register_consumer=lambda *_: None))
    registry.register("config", SimpleNamespace(ignore_bots=True))
    return registry, bot


def test_ensure_channel_record_skips_unchanged_upsert() -> None:
    async def _run() -> None:
        database = SimpleNamespace(
            is_channel_enabled=AsyncMock(return_value=False),
            upsert_channel=AsyncMock(),
        )
        registry, bot = _base_registry(database)
        setup_discord_adapter(registry)
        on_message = bot.listeners["on_message"]

        channel = _FakeChannel()
        author = SimpleNamespace(bot=False)
        message = SimpleNamespace(author=author, guild=SimpleNamespace(id=99), channel=channel)

        await on_message(message)
        await on_message(message)

        assert database.upsert_channel.await_count == 1

    asyncio.run(_run())


def test_ensure_channel_record_lock_does_not_break_event() -> None:
    async def _run() -> None:
        database = SimpleNamespace(
            is_channel_enabled=AsyncMock(return_value=False),
            upsert_channel=AsyncMock(side_effect=RuntimeError("database is locked")),
        )
        registry, bot = _base_registry(database)
        setup_discord_adapter(registry)
        on_message = bot.listeners["on_message"]

        channel = _FakeChannel()
        author = SimpleNamespace(bot=False)
        message = SimpleNamespace(author=author, guild=SimpleNamespace(id=99), channel=channel)

        await on_message(message)

    asyncio.run(_run())


def test_retention_prunes_in_batches() -> None:
    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()
        now = datetime.now(timezone.utc).isoformat()
        for idx in range(2505):
            await db.insert_message(
                message_id=f"m{idx}",
                guild_id="g1",
                channel_id="c1",
                author_id="u1",
                ts="2020-01-01T00:00:00+00:00",
                content="x",
                reply_to_message_id=None,
                mentions=[],
                attachments=[],
                embeds=[],
            )
        deleted = await db.prune_messages(now)
        assert deleted == 2505
        row = await db.fetchone("SELECT COUNT(*) AS c FROM messages", ())
        assert int(row["c"]) == 0
        await db.close()

    asyncio.run(_run())


def test_footer_persistence_lock_is_best_effort() -> None:
    async def _run() -> None:
        db = SimpleNamespace(
            get_setting=AsyncMock(return_value=None),
            set_setting=AsyncMock(),
        )
        service = FooterService(db)
        service.record_service_footer_profile = AsyncMock(side_effect=RuntimeError("database is locked"))

        embed = discord.Embed(title="x")
        attach_footer_meta(embed, service_name="barcello", used_local_processing=True)
        out = await service.apply(embed)

        assert out.footer is not None
        assert "Barcellometro" in (out.footer.text or "")

    asyncio.run(_run())


def test_ai_prompt_slot_cache_avoids_duplicate_openai_calls_on_retry_and_updates_next_run() -> None:
    async def _run() -> None:
        db = SimpleNamespace(
            update_campaign_next_run=AsyncMock(),
            get_trigger_enabled=AsyncMock(return_value=True),
            insert_send_log=AsyncMock(),
            get_setting=AsyncMock(return_value="true"),
            set_setting=AsyncMock(),
        )
        bot = _FakeBot()
        channel = _FakeMessageChannel(123)
        bot._channels[123] = channel

        ai_service = SimpleNamespace(
            is_enabled=lambda: True,
            client=lambda: object(),
            get_model=lambda _name: "gpt-4o-mini",
            ask_general_with_web=AsyncMock(return_value="ciao"),
            ask_general=AsyncMock(return_value="ciao"),
        )
        scheduler = MessageSchedulerService(db, bot, ai_service=ai_service)

        campaign = {
            "id": 42,
            "guild_id": "99",
            "channel_id": "123",
            "type": "AI_PROMPT",
            "text": "prompt",
            "interval_minutes": 10,
            "jitter_seconds": 0,
            "only_if_idle_minutes": 0,
            "next_run_at": "2024-01-01T00:00:00+00:00",
            "embed_title": "x",
        }
        now = datetime.now(timezone.utc)

        await scheduler._process_campaign(campaign, now)
        await scheduler._process_campaign(campaign, now)

        assert ai_service.ask_general_with_web.await_count == 1
        assert db.update_campaign_next_run.await_count >= 2
        statuses = [call.kwargs["status"] for call in db.insert_send_log.await_args_list]
        assert "error" in statuses

    asyncio.run(_run())
