from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests._sqlite_stub import ensure_sqlite_stub

ensure_sqlite_stub()

if "openai" not in sys.modules:
    sys.modules["openai"] = SimpleNamespace(AsyncOpenAI=object)

from app.core.service_registry import ServiceRegistry
from app.plugins.discord_adapter import setup as setup_discord_adapter


class _FakeBot:
    def __init__(self) -> None:
        self.listeners = {}

    def add_listener(self, fn, name):
        self.listeners[name] = fn

    def event(self, fn):
        self.listeners[fn.__name__] = fn
        return fn

    def get_channel(self, channel_id: int):
        return None

    def get_guild(self, guild_id: int):
        return SimpleNamespace(id=guild_id, name="Guild")


def test_member_join_and_remove_notifications_follow_canonical_write_result() -> None:
    async def _run() -> None:
        member_flow = SimpleNamespace(
            log_action=AsyncMock(
                side_effect=[
                    {"canonical_written": True, "canonical_visible": True},
                    {"canonical_written": False, "canonical_visible": False},
                ]
            ),
            send_notification=AsyncMock(),
        )
        database = SimpleNamespace(
            upsert_user=AsyncMock(),
            upsert_guild_membership=AsyncMock(),
        )
        registry = ServiceRegistry()
        bot = _FakeBot()
        registry.register("bot", bot)
        registry.register("database", database)
        registry.register("member_flow_notifications", member_flow)
        registry.register("ingest", SimpleNamespace(emit=AsyncMock(), register_consumer=lambda *_: None))
        registry.register("config", SimpleNamespace(ignore_bots=True))
        setup_discord_adapter(registry)

        guild = SimpleNamespace(id=99)
        member = SimpleNamespace(
            id=5,
            guild=guild,
            name="User",
            display_name="User",
            global_name=None,
            display_avatar=SimpleNamespace(url="https://example.test/avatar.png"),
            bot=False,
            joined_at=None,
            nick=None,
        )

        await bot.listeners["on_member_join"](member)
        await bot.listeners["on_member_remove"](member)

        assert member_flow.log_action.await_count == 2
        assert member_flow.send_notification.await_count == 1
        assert member_flow.send_notification.await_args.kwargs["action_type"] == "join"

    asyncio.run(_run())
