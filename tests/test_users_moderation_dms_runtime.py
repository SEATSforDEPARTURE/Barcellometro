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
    def __init__(self, *, enabled: int = 1, cooldown_seconds: int = 14 * 86400, invite_url: str | None = None) -> None:
        self.config = {
            "enabled": enabled,
            "cooldown_days": max(0, cooldown_seconds // 86400),
            "cooldown_seconds": cooldown_seconds,
            "invite_url": invite_url,
            "grace_template": "GRACE {mention} ({user}) {duration_human} {now_it} {expires_at_utc} {expires_at_it} {reason_line}{invite_line}",
            "tempban_template": "TEMPBAN {mention} ({user}) {duration_human} {now_it} {expires_at_utc} {expires_at_it} {reason_line}{invite_line}",
            "kick_template": "KICK {mention} ({user}) {reason_line}{invite_line}",
            "ban_template": "BAN {mention} ({user}) {reason_line}{invite_line}",
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
        assert sent_embed.title == "🕊️ __**GRAZIA**__"
        description = str(sent_embed.description)
        assert description.startswith("_") and description.endswith("_")
        assert "Manual grace reason" in description
        assert "GRACE ***<@42>*** (***<@42>***)" in description
        assert "***https://discord.gg/server***" in description
        assert "***2026-01-01 12:00 UTC***" in description
        assert "***01/01/2026 13:00***" in description
        assert sent_embed.author.name == "servizio USERS"
        assert sent_embed.footer.text
        assert db.logs[-1]["outcome"] == "success"
        assert db.logs[-1]["event_type"] == "grace"

    asyncio.run(_run())


def test_users_dm_cooldown_skips_send_and_logs_skipped() -> None:
    async def _run() -> None:
        db = _FakeDb(cooldown_seconds=14 * 86400)
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


def test_users_dm_zero_cooldown_does_not_skip_send() -> None:
    async def _run() -> None:
        db = _FakeDb(cooldown_seconds=0)
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

        assert result["sent"] is True
        user.send.assert_awaited()
        assert db.logs[-1]["outcome"] == "success"

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
                    "cooldown_seconds": 14 * 86400,
                    "invite_url": "https://discord.gg/rejoin",
                    "grace_template": "GRACE {user}",
                    "tempban_template": "AUTO TEMPBAN {mention} ({user}) {duration_human} {reason_line} {invite_line}",
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
        assert dm_embed.title == "⌛ __**INTERDIZIONE TEMPORANEA**__"
        description = str(dm_embed.description)
        assert description.startswith("_") and description.endswith("_")
        assert "AUTO TEMPBAN ***<@42>*** (***<@42>***)" in description
        assert "periodo di grazia manuale scaduto" in description
        assert "Reason:" not in description
        assert "***https://discord.gg/rejoin***" in description
        assert dm_embed.author.name == "servizio USERS"
        assert dm_embed.footer.text
        assert database.log_users_dm_delivery.await_count >= 1
        assert database.log_users_dm_delivery.await_args_list[-1].kwargs["event_type"] == "tempban"
        assert database.log_users_dm_delivery.await_args_list[-1].kwargs["outcome"] == "success"

    asyncio.run(_run())


def test_users_dm_render_safely_drops_unknown_placeholders_and_keeps_reason_text() -> None:
    async def _run() -> None:
        db = _FakeDb()
        db.config["grace_template"] = "X {mention} {reason} {reason_text} {reason_line}{unknown_placeholder}"
        user = _FakeUser(42)
        guild = _FakeGuild(user)
        service = UsersModerationDmService(db)

        result = await service.send_for_event(
            guild=guild,
            user=user,
            event_type="grace",
            duration_seconds=60,
            expires_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            reason="Motivo moderatore",
        )

        assert result == {"sent": True}
        sent_embed = user.send.await_args.kwargs["embed"]
        body = str(sent_embed.description)
        assert body.startswith("_") and body.endswith("_")
        assert "***La moderazione aggiunge: Motivo moderatore***" in body
        assert "La moderazione aggiunge:" in body
        assert "{unknown_placeholder}" not in body

    asyncio.run(_run())


def test_users_dm_render_reason_text_is_empty_when_reason_missing() -> None:
    async def _run() -> None:
        db = _FakeDb()
        db.config["grace_template"] = "X {mention} {reason_text}{unknown_placeholder}"
        user = _FakeUser(42)
        guild = _FakeGuild(user)
        service = UsersModerationDmService(db)

        result = await service.send_for_event(
            guild=guild,
            user=user,
            event_type="grace",
            duration_seconds=60,
            expires_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            reason=None,
        )

        assert result == {"sent": True}
        sent_embed = user.send.await_args.kwargs["embed"]
        body = str(sent_embed.description)
        assert "{unknown_placeholder}" not in body
        assert "La moderazione aggiunge:" not in body
        assert "None" not in body

    asyncio.run(_run())


def test_users_dm_kick_and_ban_use_dedicated_templates() -> None:
    async def _run() -> None:
        db = _FakeDb(invite_url="https://discord.gg/server")
        user = _FakeUser(42)
        guild = _FakeGuild(user)
        service = UsersModerationDmService(db)

        kick_result = await service.send_for_event(
            guild=guild,
            user=user,
            event_type="kick",
            reason="Repeated abusive language",
        )
        ban_result = await service.send_for_event(
            guild=guild,
            user=user,
            event_type="ban",
            reason="Severe harassment",
        )

        assert kick_result == {"sent": True}
        assert ban_result == {"sent": True}
        assert user.send.await_count == 2
        kick_body = str(user.send.await_args_list[0].kwargs["embed"].description)
        ban_body = str(user.send.await_args_list[1].kwargs["embed"].description)
        assert "KICK ***<@42>*** (***<@42>***)" in kick_body
        assert "Repeated abusive language" in kick_body
        assert "BAN ***<@42>*** (***<@42>***)" in ban_body
        assert "Severe harassment" in ban_body
        assert db.logs[-2]["event_type"] == "kick"
        assert db.logs[-1]["event_type"] == "ban"

    asyncio.run(_run())


def test_users_dm_tempban_reason_line_distinguishes_direct_and_auto_cases() -> None:
    async def _run() -> None:
        db = _FakeDb()
        db.config["tempban_template"] = "TEMPBAN {reason_line}"
        user = _FakeUser(42)
        guild = _FakeGuild(user)
        service = UsersModerationDmService(db)

        direct = await service.send_for_event(
            guild=guild,
            user=user,
            event_type="tempban",
            reason="Spam raid",
            reasoning="users_manual_tempban_direct",
        )
        auto_manual = await service.send_for_event(
            guild=guild,
            user=user,
            event_type="tempban",
            reason=None,
            reasoning="users_manual_grace_expired_tempban",
        )
        auto_inactivity = await service.send_for_event(
            guild=guild,
            user=user,
            event_type="tempban",
            reason=None,
            reasoning="inactivity_grace_expired_tempban",
        )

        assert direct == {"sent": True}
        assert auto_manual == {"sent": True}
        assert auto_inactivity == {"sent": True}
        direct_body = str(user.send.await_args_list[0].kwargs["embed"].description)
        auto_manual_body = str(user.send.await_args_list[1].kwargs["embed"].description)
        auto_inactivity_body = str(user.send.await_args_list[2].kwargs["embed"].description)
        assert "Spam raid" in direct_body
        assert "periodo di grazia" not in direct_body
        assert "periodo di grazia manuale scaduto" in auto_manual_body
        assert "periodo di grazia per inattività scaduto" in auto_inactivity_body

    asyncio.run(_run())


def test_users_dm_send_for_event_by_user_id_fetches_user_when_member_missing() -> None:
    async def _run() -> None:
        db = _FakeDb(invite_url="https://discord.gg/server")
        fetched_user = _FakeUser(777)
        guild = _FakeGuild(user=None)
        bot = SimpleNamespace(fetch_user=AsyncMock(return_value=fetched_user))
        service = UsersModerationDmService(db, bot=bot)

        result = await service.send_for_event_by_user_id(
            guild=guild,
            user_id="777",
            event_type="ban",
            reason="Severe harassment",
            metadata={"source": "test"},
        )

        assert result == {"sent": True}
        bot.fetch_user.assert_awaited_once_with(777)
        fetched_user.send.assert_awaited_once()
        assert db.logs[-1]["event_type"] == "ban"
        assert db.logs[-1]["outcome"] == "success"

    asyncio.run(_run())
