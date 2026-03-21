from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests._sqlite_stub import ensure_sqlite_stub

ensure_sqlite_stub()

if "openai" not in sys.modules:
    sys.modules["openai"] = SimpleNamespace(AsyncOpenAI=object)

import app.plugins.discord_adapter as discord_adapter_module
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


class _AsyncAuditLogIterator:
    def __init__(self, entries):
        self._entries = list(entries)
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._entries):
            raise StopAsyncIteration
        value = self._entries[self._index]
        self._index += 1
        return value


class _FakeGuild:
    def __init__(self, *, guild_id: int, audit_entries: dict[str, list[object]] | None = None) -> None:
        self.id = guild_id
        self.name = "Guild"
        self._audit_entries = audit_entries or {}

    def audit_logs(self, *, limit: int = 6, action=None):
        return _AsyncAuditLogIterator(self._audit_entries.get(action, [])[:limit])


def _build_member(*, guild: _FakeGuild) -> SimpleNamespace:
    return SimpleNamespace(
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


def _configure_registry(*, member_flow, database) -> tuple[ServiceRegistry, _FakeBot]:
    registry = ServiceRegistry()
    bot = _FakeBot()
    registry.register("bot", bot)
    registry.register("database", database)
    registry.register("member_flow_notifications", member_flow)
    registry.register("ingest", SimpleNamespace(emit=AsyncMock(), register_consumer=lambda *_: None))
    registry.register("config", SimpleNamespace(ignore_bots=True))
    return registry, bot


def test_member_join_and_voluntary_remove_notifications_follow_canonical_write_result(monkeypatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(discord_adapter_module, "_DISCORD_NATIVE_MOD_AUDIT_ATTEMPTS", 1)
        monkeypatch.setattr(discord_adapter_module, "_DISCORD_NATIVE_MOD_AUDIT_RETRY_SECONDS", 0)
        monkeypatch.setattr(
            discord_adapter_module.discord,
            "AuditLogAction",
            SimpleNamespace(ban="ban", kick="kick", unban="unban"),
            raising=False,
        )

        member_flow = SimpleNamespace(
            get_recent_departure_action=lambda *_args, **_kwargs: None,
            log_action=AsyncMock(
                side_effect=[
                    {"canonical_written": True, "canonical_visible": True, "canonical_event": {"event_type_key": "join"}},
                    {"canonical_written": False, "canonical_visible": False},
                ]
            ),
            send_notification=AsyncMock(),
        )
        database = SimpleNamespace(
            upsert_user=AsyncMock(),
            upsert_guild_membership=AsyncMock(),
        )
        registry, bot = _configure_registry(member_flow=member_flow, database=database)
        setup_discord_adapter(registry)

        guild = _FakeGuild(guild_id=99)
        member = _build_member(guild=guild)

        await bot.listeners["on_member_join"](member)
        await bot.listeners["on_member_remove"](member)

        assert member_flow.log_action.await_count == 2
        assert member_flow.log_action.await_args_list[1].kwargs["action_type"] == "leave"
        assert member_flow.send_notification.await_count == 1
        assert member_flow.send_notification.await_args.kwargs["action_type"] == "join"
        assert member_flow.send_notification.await_args.kwargs["canonical_event"] == {"event_type_key": "join"}

    asyncio.run(_run())


def test_native_discord_kick_is_classified_as_kick_not_leave_and_preserves_reason(monkeypatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(discord_adapter_module, "_DISCORD_NATIVE_MOD_AUDIT_ATTEMPTS", 1)
        monkeypatch.setattr(discord_adapter_module, "_DISCORD_NATIVE_MOD_AUDIT_RETRY_SECONDS", 0)
        monkeypatch.setattr(
            discord_adapter_module.discord,
            "AuditLogAction",
            SimpleNamespace(ban="ban", kick="kick", unban="unban"),
            raising=False,
        )

        moderator = SimpleNamespace(id=88, mention="<@88>", display_name="Mod")
        audit_entry = SimpleNamespace(
            id=7001,
            target=SimpleNamespace(id=5),
            user=moderator,
            reason="Spam ripetuto",
            created_at=datetime.now(timezone.utc),
        )
        guild = _FakeGuild(guild_id=99, audit_entries={"kick": [audit_entry]})
        member = _build_member(guild=guild)

        async def _log_action(**kwargs):
            return {
                "canonical_written": True,
                "canonical_visible": True,
                "canonical_event": {"event_type_key": kwargs["action_type"], "reason": kwargs["reason"]},
            }

        member_flow = SimpleNamespace(
            get_recent_departure_action=lambda *_args, **_kwargs: None,
            log_action=AsyncMock(side_effect=_log_action),
            send_notification=AsyncMock(),
        )
        database = SimpleNamespace(
            upsert_user=AsyncMock(),
            upsert_guild_membership=AsyncMock(),
        )
        registry, bot = _configure_registry(member_flow=member_flow, database=database)
        setup_discord_adapter(registry)

        await bot.listeners["on_member_remove"](member)

        assert member_flow.log_action.await_count == 1
        kwargs = member_flow.log_action.await_args.kwargs
        assert kwargs["action_type"] == "kick"
        assert kwargs["reason"] == "Spam ripetuto"
        assert kwargs["moderator_id"] == "88"
        assert kwargs["metadata"]["native_moderation"] is True
        assert kwargs["metadata"]["discord_audit_action"] == "kick"
        assert member_flow.send_notification.await_count == 1
        assert member_flow.send_notification.await_args.kwargs["action_type"] == "kick"
        assert member_flow.send_notification.await_args.kwargs["canonical_event"]["event_type_key"] == "kick"

    asyncio.run(_run())


def test_native_discord_ban_is_classified_as_ban_not_leave_and_deduped_across_events(monkeypatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(discord_adapter_module, "_DISCORD_NATIVE_MOD_AUDIT_ATTEMPTS", 1)
        monkeypatch.setattr(discord_adapter_module, "_DISCORD_NATIVE_MOD_AUDIT_RETRY_SECONDS", 0)
        monkeypatch.setattr(
            discord_adapter_module.discord,
            "AuditLogAction",
            SimpleNamespace(ban="ban", kick="kick", unban="unban"),
            raising=False,
        )

        recent_departures: dict[tuple[str, str], str] = {}
        moderator = SimpleNamespace(id=99, mention="<@99>", display_name="Admin")
        audit_entry = SimpleNamespace(
            id=8001,
            target=SimpleNamespace(id=5),
            user=moderator,
            reason="Ban definitivo",
            created_at=datetime.now(timezone.utc),
        )
        guild = _FakeGuild(guild_id=99, audit_entries={"ban": [audit_entry]})
        member = _build_member(guild=guild)
        banned_user = SimpleNamespace(
            id=5,
            name="User",
            display_name="User",
            global_name=None,
            display_avatar=SimpleNamespace(url="https://example.test/avatar.png"),
            bot=False,
        )

        async def _log_action(**kwargs):
            recent_departures[(kwargs["guild_id"], kwargs["user_id"])] = kwargs["action_type"]
            return {
                "canonical_written": True,
                "canonical_visible": True,
                "canonical_event": {"event_type_key": kwargs["action_type"], "reason": kwargs["reason"]},
            }

        member_flow = SimpleNamespace(
            get_recent_departure_action=lambda guild_id, user_id, **_kwargs: recent_departures.get((guild_id, user_id)),
            log_action=AsyncMock(side_effect=_log_action),
            send_notification=AsyncMock(),
        )
        database = SimpleNamespace(
            upsert_user=AsyncMock(),
            upsert_guild_membership=AsyncMock(),
        )
        registry, bot = _configure_registry(member_flow=member_flow, database=database)
        setup_discord_adapter(registry)

        await bot.listeners["on_member_remove"](member)
        await bot.listeners["on_member_ban"](guild, banned_user)

        assert member_flow.log_action.await_count == 1
        kwargs = member_flow.log_action.await_args.kwargs
        assert kwargs["action_type"] == "ban"
        assert kwargs["reason"] == "Ban definitivo"
        assert kwargs["metadata"]["native_moderation"] is True
        assert kwargs["metadata"]["discord_audit_action"] == "ban"
        assert member_flow.send_notification.await_count == 1
        assert member_flow.send_notification.await_args.kwargs["action_type"] == "ban"
        assert member_flow.send_notification.await_args.kwargs["canonical_event"]["event_type_key"] == "ban"

    asyncio.run(_run())
