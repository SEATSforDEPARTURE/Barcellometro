from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import Mock

if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(Row=dict)

if "discord" not in sys.modules:
    discord_stub = types.ModuleType("discord")
    discord_stub.Member = object
    discord_stub.Client = object
    discord_stub.Guild = object
    discord_stub.Object = object
    discord_stub.Interaction = object
    discord_stub.Message = object
    discord_stub.ButtonStyle = types.SimpleNamespace(primary=1, danger=2, secondary=3)
    discord_stub.abc = types.SimpleNamespace(Messageable=object)
    discord_stub.ui = types.SimpleNamespace(
        View=object,
        Button=object,
        button=lambda *args, **kwargs: (lambda fn: fn),
    )
    sys.modules["discord"] = discord_stub

from app.services.inactive_members_moderation import _state_int
from app.services.inactive_members_moderation import InactiveCandidate, InactiveMembersModerationService


class _FakeRow:
    def __init__(self, data: dict[str, object]) -> None:
        self._data = data

    def keys(self):
        return self._data.keys()

    def __getitem__(self, key: str):
        return self._data[key]


def test_state_int_handles_row_dict_and_missing_values() -> None:
    row = _FakeRow({"reminder_count": "2"})
    assert _state_int(row, "reminder_count", 0) == 2
    assert _state_int(row, "missing", 7) == 7
    assert _state_int({"reminder_count": None}, "reminder_count", 3) == 3
    assert _state_int({"reminder_count": "x"}, "reminder_count", 5) == 5
    assert _state_int(None, "reminder_count", 4) == 4


def test_execute_kick_pipeline_uses_operation_id_and_hides_inactive_kick_when_tempban_exists() -> None:
    async def _run() -> None:
        sys.modules["discord"].Object = lambda id: SimpleNamespace(id=id)
        member = SimpleNamespace(
            id=42,
            mention="<@42>",
            display_name="Dormiente",
            send=AsyncMock(),
            kick=AsyncMock(),
        )
        candidate = InactiveCandidate(
            member=member,
            last_message_ts=(datetime.now(timezone.utc) - timedelta(days=40)).isoformat(),
            last_channel_id=None,
            last_message_id=None,
            count_in_window=0,
            days_inactive=40,
            policy={"inactive_days": 30, "window_days": 30, "min_messages": 1, "mode": "OR"},
        )
        guild = SimpleNamespace(id=1, name="Barcellometro", ban=AsyncMock())
        database = SimpleNamespace(
            get_inactivity_user_state=AsyncMock(return_value={"last_reminder_at": None, "reminder_count": 0}),
            add_temp_ban=AsyncMock(),
            mark_user_kicked=AsyncMock(),
        )
        member_flow_notifications = SimpleNamespace(
            log_action=AsyncMock(
                side_effect=[
                    {"canonical_written": True, "canonical_visible": False},
                    {"canonical_written": True, "canonical_visible": True},
                ]
            ),
            send_notification=AsyncMock(),
        )
        service = InactiveMembersModerationService(database, SimpleNamespace(get_guild=lambda guild_id: guild), member_flow_notifications=member_flow_notifications)
        service.scan_inactive_members = AsyncMock(
            return_value=(
                [candidate],
                1,
                {
                    "grace_days_after_reminder": 7,
                    "ban_days": 3,
                    "dm_kick_template": "Kick {user}",
                    "invite_url": "https://example.test/invite",
                },
            )
        )

        result = await service.execute_kick_pipeline("1", require_grace=False)

        assert result["kick_ok"] == 1
        assert result["ban_ok"] == 1
        assert member_flow_notifications.log_action.await_count == 2
        first_metadata = member_flow_notifications.log_action.await_args_list[0].kwargs["metadata"]
        second_metadata = member_flow_notifications.log_action.await_args_list[1].kwargs["metadata"]
        assert member_flow_notifications.log_action.await_args_list[0].kwargs["action_type"] == "inactive_kick"
        assert member_flow_notifications.log_action.await_args_list[1].kwargs["action_type"] == "inactive_tempban"
        assert first_metadata["visible_in_greetings"] is False
        assert first_metadata["operation_id"] == second_metadata["operation_id"]
        assert member_flow_notifications.log_action.await_args_list[0].kwargs["reason"] != "Via per inattività: è stato inattivo per 40 giorni"
        assert member_flow_notifications.send_notification.await_count == 1
        assert member_flow_notifications.send_notification.await_args.kwargs["action_type"] == "inactive_tempban"

    asyncio.run(_run())


def test_run_due_unbans_applies_auto_tempban_after_manual_grace() -> None:
    async def _run() -> None:
        sys.modules["discord"].Object = lambda id: SimpleNamespace(id=id)
        guild = SimpleNamespace(id=1, unban=AsyncMock(), ban=AsyncMock())
        database = SimpleNamespace(
            list_due_temp_unbans=AsyncMock(return_value=[]),
            list_due_manual_grace=AsyncMock(return_value=[{"id": "g1", "guild_id": "1", "user_id": "42"}]),
            get_setting=AsyncMock(return_value="7200"),
            log_moderation_action=AsyncMock(),
            add_temp_ban=AsyncMock(),
            clear_user_ban_state=AsyncMock(),
        )
        service = InactiveMembersModerationService(database, SimpleNamespace(get_guild=lambda guild_id: guild), member_flow_notifications=None)
        await service._run_due_unbans()

        guild.ban.assert_awaited_once()
        database.add_temp_ban.assert_awaited_once()
        assert database.log_moderation_action.await_count == 2
        assert database.log_moderation_action.await_args_list[0].kwargs["action_type"] == "ungrace"
        assert database.log_moderation_action.await_args_list[1].kwargs["action_type"] == "tempban"
        assert database.log_moderation_action.await_args_list[1].kwargs["duration_seconds"] == 7200

    asyncio.run(_run())


def test_run_due_unbans_skips_auto_tempban_after_reset_to_zero() -> None:
    async def _run() -> None:
        guild = SimpleNamespace(id=1, unban=AsyncMock(), ban=AsyncMock())
        database = SimpleNamespace(
            list_due_temp_unbans=AsyncMock(return_value=[]),
            list_due_manual_grace=AsyncMock(return_value=[{"id": "g1", "guild_id": "1", "user_id": "42"}]),
            get_setting=AsyncMock(return_value="0"),
            log_moderation_action=AsyncMock(),
            add_temp_ban=AsyncMock(),
            clear_user_ban_state=AsyncMock(),
        )
        service = InactiveMembersModerationService(database, SimpleNamespace(get_guild=lambda guild_id: guild), member_flow_notifications=None)
        await service._run_due_unbans()

        guild.ban.assert_not_awaited()
        database.add_temp_ban.assert_not_awaited()
        assert database.log_moderation_action.await_count == 1
        assert database.log_moderation_action.await_args.kwargs["action_type"] == "ungrace"

    asyncio.run(_run())


def test_run_due_unbans_uses_member_flow_audit_for_manual_grace_auto_actions() -> None:
    async def _run() -> None:
        sys.modules["discord"].Object = lambda id: SimpleNamespace(id=id)
        guild = SimpleNamespace(id=1, unban=AsyncMock(), ban=AsyncMock())
        database = SimpleNamespace(
            list_due_temp_unbans=AsyncMock(return_value=[]),
            list_due_manual_grace=AsyncMock(return_value=[{"id": "g1", "guild_id": "1", "user_id": "42"}]),
            get_setting=AsyncMock(return_value="1800"),
            log_moderation_action=AsyncMock(),
            add_temp_ban=AsyncMock(),
            clear_user_ban_state=AsyncMock(),
        )
        member_flow_notifications = SimpleNamespace(
            log_action=AsyncMock(
                side_effect=[
                    {"canonical_written": True, "canonical_visible": False},
                    {"canonical_written": True, "canonical_visible": True, "canonical_event": {"event_type_key": "tempban", "visible_in_greetings": True}},
                ]
            ),
            send_notification=AsyncMock(),
            remember_departure_action=Mock(),
        )
        service = InactiveMembersModerationService(
            database,
            SimpleNamespace(get_guild=lambda guild_id: guild),
            member_flow_notifications=member_flow_notifications,
        )

        await service._run_due_unbans()

        assert member_flow_notifications.log_action.await_count == 2
        assert member_flow_notifications.log_action.await_args_list[0].kwargs["action_type"] == "ungrace"
        assert member_flow_notifications.log_action.await_args_list[0].kwargs["metadata"]["source"] == "users_grace_auto_expiry"
        assert member_flow_notifications.log_action.await_args_list[1].kwargs["action_type"] == "tempban"
        assert member_flow_notifications.log_action.await_args_list[1].kwargs["metadata"]["source"] == "users_grace_auto_tempban"
        assert member_flow_notifications.log_action.await_args_list[1].kwargs["metadata"]["greetings_origin"] == "manual_grace_expired_auto_tempban"
        assert member_flow_notifications.remember_departure_action.call_count == 1
        assert member_flow_notifications.send_notification.await_count == 1
        assert member_flow_notifications.send_notification.await_args.kwargs["action_type"] == "tempban"
        assert member_flow_notifications.send_notification.await_args.kwargs["reason"] is None
        database.log_moderation_action.assert_not_awaited()

    asyncio.run(_run())


def test_execute_reminders_respects_dm_toggle_and_skips_sending() -> None:
    async def _run() -> None:
        guild = SimpleNamespace(id=1, name="Barcellometro")
        database = SimpleNamespace(
            get_inactivity_user_state=AsyncMock(return_value=None),
            mark_user_reminded=AsyncMock(),
            log_inactivity_dm_delivery=AsyncMock(),
        )
        service = InactiveMembersModerationService(database, SimpleNamespace(get_guild=lambda guild_id: guild), member_flow_notifications=None)
        service.scan_inactive_members = AsyncMock(return_value=([], 0, {"dm_reminders_enabled": 0}))

        result = await service.execute_reminders("1")

        assert result["disabled"] is True
        database.mark_user_reminded.assert_not_awaited()
        database.log_inactivity_dm_delivery.assert_not_awaited()

    asyncio.run(_run())


def test_execute_reminders_logs_dm_delivery_outcomes() -> None:
    async def _run() -> None:
        member_ok = SimpleNamespace(id=42, mention="<@42>", display_name="Dormiente", send=AsyncMock())
        member_fail = SimpleNamespace(id=43, mention="<@43>", display_name="Ghost", send=AsyncMock(side_effect=PermissionError("Forbidden")))
        candidate_ok = InactiveCandidate(
            member=member_ok,
            last_message_ts=(datetime.now(timezone.utc) - timedelta(days=40)).isoformat(),
            last_channel_id=None,
            last_message_id=None,
            count_in_window=0,
            days_inactive=40,
            policy={"inactive_days": 30, "window_days": 30, "min_messages": 1, "mode": "OR"},
        )
        candidate_fail = InactiveCandidate(
            member=member_fail,
            last_message_ts=(datetime.now(timezone.utc) - timedelta(days=50)).isoformat(),
            last_channel_id=None,
            last_message_id=None,
            count_in_window=0,
            days_inactive=50,
            policy={"inactive_days": 30, "window_days": 30, "min_messages": 1, "mode": "OR"},
        )
        guild = SimpleNamespace(id=1, name="Barcellometro")
        database = SimpleNamespace(
            get_inactivity_user_state=AsyncMock(return_value=None),
            mark_user_reminded=AsyncMock(),
            log_inactivity_dm_delivery=AsyncMock(),
        )
        service = InactiveMembersModerationService(database, SimpleNamespace(get_guild=lambda guild_id: guild), member_flow_notifications=None)
        service.scan_inactive_members = AsyncMock(
            return_value=(
                [candidate_ok, candidate_fail],
                2,
                {"dm_reminders_enabled": 1, "grace_days_after_reminder": 7, "dm_reminder_template": "Ciao {user}"},
            )
        )

        result = await service.execute_reminders("1")

        assert result["dm_ok"] == 1
        assert result["dm_fail"] == 1
        database.mark_user_reminded.assert_awaited_once()
        assert database.log_inactivity_dm_delivery.await_count == 2
        outcomes = [call.kwargs["outcome"] for call in database.log_inactivity_dm_delivery.await_args_list]
        assert outcomes == ["success", "fail"]

    asyncio.run(_run())
