from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
                    "template_inactivity_reason": "Via per inattività: {inactivity_text}",
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
        assert member_flow_notifications.send_notification.await_count == 1
        assert member_flow_notifications.send_notification.await_args.kwargs["action_type"] == "inactive_tempban"

    asyncio.run(_run())
