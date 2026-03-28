from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(Row=dict)

from app.services.inactive_members_moderation import InactiveMembersModerationService
from app.services.users_moderation_dms import UsersModerationDmService


class _FakeDb:
    def __init__(self, *, enabled: int = 1, cooldown_days: int = 14, invite_url: str | None = None) -> None:
        self.config = {
            "enabled": enabled,
            "cooldown_days": cooldown_days,
            "invite_url": invite_url,
            "grace_template": "GRACE {mention} ({user}) {duration_human} {now_it} {expires_at_utc} {expires_at_it} {reason_line}{invite_line}",
            "tempban_template": "TEMPBAN {mention} ({user}) {duration_human} {now_it} {expires_at_utc} {expires_at_it} {reason_line}{invite_line}",
        }
        self.latest: dict[tuple[str, str, str], dict[str, str]] = {}
        self.logs: list[dict[str, object]] = []

    async def get_users_dm_config(self, guild_id: str):
        _ = guild_id
        return self.config

    async def get_latest_users_dm_delivery(self, guild_id: str, user_id: str, event_type: str):
        return self.latest.get((guild_id, user_id, event_type))

    async def log_users_dm_delivery(self, **kwargs):
        self.logs.append(kwargs)


class _FakeUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id
        self.mention = f"<@{user_id}>"
        self.name = f"user-{user_id}"
        self.display_name = f"Display {user_id}"
        self.send = AsyncMock()


class _FakeGuild:
    def __init__(self, user: _FakeUser | None = None) -> None:
        self.id = 1
        self.name = "Barcellometro"
        self._user = user
        self.ban = AsyncMock()

    def get_member(self, user_id: int):
        if self._user is None:
            return None
        return self._user if self._user.id == user_id else None


def test_users_dm_manual_grace_renders_template_and_logs_success() -> None:
    async def _run() -> None:
        db = _FakeDb(invite_url="https://discord.gg/server")
        user = _FakeUser(42)
        guild = _FakeGuild(user)
        service = UsersModerationDmService(db)

        result = await service.send_for_event(
            guild=guild,
            user=user,
            event_type="grace",
            duration_seconds=7200,
            expires_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            reason="Manual grace reason",
            metadata={"source": "test"},
        )

        assert result == {"sent": True}
        user.send.assert_awaited_once()
        sent_embed = user.send.await_args.kwargs["embed"]
        assert sent_embed.title.startswith("🛡️")
        assert "GRACE MANUALE ATTIVATO" in sent_embed.title
        assert "Manual grace reason" in str(sent_embed.description)
        assert "GRACE <@42> (<@42>)" in str(sent_embed.description)
        assert "https://discord.gg/server" in str(sent_embed.description)
        assert "2026-01-01 12:00 UTC" in str(sent_embed.description)
        assert "01/01/2026 13:00" in str(sent_embed.description)
        assert sent_embed.author.name
        assert sent_embed.footer.text
        assert db.logs[-1]["outcome"] == "success"
        assert db.logs[-1]["event_type"] == "grace"

    asyncio.run(_run())


def test_users_dm_cooldown_skips_send_and_logs_skipped() -> None:
    async def _run() -> None:
        db = _FakeDb(cooldown_days=14)
        now_iso = datetime.now(timezone.utc).isoformat()
        db.latest[("1", "42", "grace")] = {"sent_at": now_iso, "outcome": "success"}
        user = _FakeUser(42)
        guild = _FakeGuild(user)
        service = UsersModerationDmService(db)

        result = await service.send_for_event(
            guild=guild,
            user=user,
            event_type="grace",
            duration_seconds=1800,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            reason="manual grace",
        )

        assert result["sent"] is False
        assert result["skipped"] == "cooldown"
        user.send.assert_not_awaited()
        assert db.logs[-1]["outcome"] == "skipped"
        assert db.logs[-1]["error_summary"] == "cooldown"

    asyncio.run(_run())


def test_users_dm_disabled_skips_send_and_logs_skipped() -> None:
    async def _run() -> None:
        db = _FakeDb(enabled=0)
        user = _FakeUser(42)
        guild = _FakeGuild(user)
        service = UsersModerationDmService(db)

        result = await service.send_for_event(
            guild=guild,
            user=user,
            event_type="grace",
            duration_seconds=1800,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            reason="manual grace",
        )

        assert result["sent"] is False
        assert result["skipped"] == "disabled"
        user.send.assert_not_awaited()
        assert db.logs[-1]["outcome"] == "skipped"
        assert db.logs[-1]["error_summary"] == "disabled"

    asyncio.run(_run())


def test_users_dm_text_fallback_when_embed_send_fails() -> None:
    async def _run() -> None:
        db = _FakeDb(invite_url="https://discord.gg/server")
        user = _FakeUser(42)
        user.send = AsyncMock(side_effect=[RuntimeError("embed blocked"), None])
        guild = _FakeGuild(user)
        service = UsersModerationDmService(db)

        result = await service.send_for_event(
            guild=guild,
            user=user,
            event_type="grace",
            duration_seconds=7200,
            expires_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            reason="Manual grace reason",
            metadata={"source": "test"},
        )

        assert result == {"sent": True, "fallback": "text"}
        assert user.send.await_count == 2
        assert db.logs[-1]["outcome"] == "success"
        assert db.logs[-1]["metadata"]["delivery_fallback"] == "text"

    asyncio.run(_run())


def test_auto_tempban_after_manual_grace_uses_tempban_template_and_logs() -> None:
    async def _run() -> None:
        user = _FakeUser(42)
        guild = _FakeGuild()

        database = SimpleNamespace(
            list_due_temp_unbans=AsyncMock(return_value=[]),
            list_due_manual_grace=AsyncMock(return_value=[{"id": "grace-1", "guild_id": "1", "user_id": "42"}]),
            get_setting=AsyncMock(return_value="3600"),
            log_moderation_action=AsyncMock(),
            add_temp_ban=AsyncMock(),
            clear_user_ban_state=AsyncMock(),
            get_users_dm_config=AsyncMock(
                return_value={
                    "enabled": 1,
                    "cooldown_days": 14,
                    "invite_url": "https://discord.gg/rejoin",
                    "grace_template": "GRACE {user}",
                    "tempban_template": "AUTO TEMPBAN {mention} ({user}) {duration_human} {invite_line}",
                }
            ),
            get_latest_users_dm_delivery=AsyncMock(return_value=None),
            log_users_dm_delivery=AsyncMock(),
        )
        bot = SimpleNamespace(
            get_guild=lambda guild_id: guild if guild_id == 1 else None,
            fetch_user=AsyncMock(return_value=user),
        )
        service = InactiveMembersModerationService(database, bot, member_flow_notifications=None)

        await service._run_due_unbans()

        guild.ban.assert_awaited_once()
        user.send.assert_awaited_once()
        dm_embed = user.send.await_args.kwargs["embed"]
        assert dm_embed.title.startswith("🔨")
        assert "BAN TEMPORANEO AUTOMATICO" in dm_embed.title
        assert "AUTO TEMPBAN <@42> (<@42>)" in str(dm_embed.description)
        assert "https://discord.gg/rejoin" in str(dm_embed.description)
        assert dm_embed.author.name
        assert dm_embed.footer.text
        assert database.log_users_dm_delivery.await_count >= 1
        assert database.log_users_dm_delivery.await_args_list[-1].kwargs["event_type"] == "tempban"
        assert database.log_users_dm_delivery.await_args_list[-1].kwargs["outcome"] == "success"

    asyncio.run(_run())
