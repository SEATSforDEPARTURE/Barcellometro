from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import Mock
from unittest.mock import patch

if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(Row=dict)

if "discord" not in sys.modules:
    discord_stub = types.ModuleType("discord")
    class _FakeColour:
        @staticmethod
        def blurple():
            return 0x5865F2

        @staticmethod
        def orange():
            return 0xFAA61A

    class _FakeEmbed:
        def __init__(self, *, title=None, color=None, colour=None):
            self.title = title
            self.color = color if color is not None else colour
            self.description = None
            self.author = SimpleNamespace(name=None)
            self.footer = SimpleNamespace(text=None)
            self.image = SimpleNamespace(url=None)
            self.thumbnail = SimpleNamespace(url=None)
            self.fields: list[SimpleNamespace] = []

        def add_field(self, *, name, value, inline=True):
            self.fields.append(SimpleNamespace(name=name, value=value, inline=inline))

        def set_author(self, *, name=None, icon_url=None):
            _ = icon_url
            self.author = SimpleNamespace(name=name)

        def set_footer(self, *, text=None, icon_url=None):
            _ = icon_url
            self.footer = SimpleNamespace(text=text)

        def set_image(self, *, url=None):
            self.image = SimpleNamespace(url=url)

        def set_thumbnail(self, *, url=None):
            self.thumbnail = SimpleNamespace(url=url)

    discord_stub.Colour = _FakeColour
    discord_stub.Embed = _FakeEmbed
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
from app.shared.discord.embed_body import format_standard_field_name


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
            log_inactivity_dm_delivery=AsyncMock(),
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
                {"dm_reminders_enabled": 1, "grace_days_after_reminder": 7, "template_grace": "Grace {mention} ({user})"},
            )
        )

        result = await service.execute_reminders("1")

        assert result["dm_ok"] == 1
        assert result["dm_fail"] == 1
        sent_embed = member_ok.send.await_args.kwargs["embed"]
        assert sent_embed.title == "🕊️ __**GRAZIA**__"
        description = str(sent_embed.description)
        assert description.startswith("_") and description.endswith("_")
        assert "Grace ***<@42>*** (***<@42>***)" in description
        assert sent_embed.author.name == "servizio INACTIVITY"
        assert sent_embed.footer.text
        database.mark_user_reminded.assert_awaited_once()
        assert database.log_inactivity_dm_delivery.await_count == 2
        event_types = [call.kwargs["event_type"] for call in database.log_inactivity_dm_delivery.await_args_list]
        outcomes = [call.kwargs["outcome"] for call in database.log_inactivity_dm_delivery.await_args_list]
        assert event_types == ["grace", "grace"]
        assert outcomes == ["success", "fail"]

    asyncio.run(_run())


def test_execute_reminders_respects_cooldown_and_logs_skipped() -> None:
    async def _run() -> None:
        member = SimpleNamespace(id=42, mention="<@42>", display_name="Dormiente", send=AsyncMock())
        candidate = InactiveCandidate(
            member=member,
            last_message_ts=(datetime.now(timezone.utc) - timedelta(days=40)).isoformat(),
            last_channel_id=None,
            last_message_id=None,
            count_in_window=0,
            days_inactive=40,
            policy={"inactive_days": 30, "window_days": 30, "min_messages": 1, "mode": "OR"},
        )
        guild = SimpleNamespace(id=1, name="Barcellometro")
        now_iso = datetime.now(timezone.utc).isoformat()
        database = SimpleNamespace(
            get_inactivity_user_state=AsyncMock(return_value=None),
            get_latest_inactivity_dm_delivery=AsyncMock(
                side_effect=[
                    {"sent_at": now_iso, "outcome": "success"},
                    {"sent_at": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(), "outcome": "success"},
                ]
            ),
            mark_user_reminded=AsyncMock(),
            log_inactivity_dm_delivery=AsyncMock(),
        )
        service = InactiveMembersModerationService(database, SimpleNamespace(get_guild=lambda guild_id: guild), member_flow_notifications=None)
        service.scan_inactive_members = AsyncMock(
            return_value=(
                [candidate],
                1,
                {"dm_reminders_enabled": 1, "grace_days_after_reminder": 7, "reminder_cooldown_days": 14, "reminder_cooldown_seconds": 14 * 86400},
            )
        )

        result = await service.execute_reminders("1")

        assert result["dm_ok"] == 0
        assert result["dm_fail"] == 0
        assert result["dm_skipped"] == 1
        member.send.assert_not_awaited()
        database.mark_user_reminded.assert_not_awaited()
        database.log_inactivity_dm_delivery.assert_awaited_once()
        assert database.get_latest_inactivity_dm_delivery.await_count == 2
        assert database.log_inactivity_dm_delivery.await_args.kwargs["outcome"] == "skipped"
        assert database.log_inactivity_dm_delivery.await_args.kwargs["error_summary"] == "cooldown"
        assert database.log_inactivity_dm_delivery.await_args.kwargs["event_type"] == "grace"

    asyncio.run(_run())


def test_execute_reminders_with_zero_cooldown_does_not_skip() -> None:
    async def _run() -> None:
        member = SimpleNamespace(id=42, mention="<@42>", display_name="Dormiente", send=AsyncMock())
        candidate = InactiveCandidate(
            member=member,
            last_message_ts=(datetime.now(timezone.utc) - timedelta(days=40)).isoformat(),
            last_channel_id=None,
            last_message_id=None,
            count_in_window=0,
            days_inactive=40,
            policy={"inactive_days": 30, "window_days": 30, "min_messages": 1, "mode": "OR"},
        )
        guild = SimpleNamespace(id=1, name="Barcellometro")
        now_iso = datetime.now(timezone.utc).isoformat()
        database = SimpleNamespace(
            get_inactivity_user_state=AsyncMock(return_value=None),
            get_latest_inactivity_dm_delivery=AsyncMock(side_effect=[{"sent_at": now_iso, "outcome": "success"}, None]),
            mark_user_reminded=AsyncMock(),
            log_inactivity_dm_delivery=AsyncMock(),
        )
        service = InactiveMembersModerationService(database, SimpleNamespace(get_guild=lambda guild_id: guild), member_flow_notifications=None)
        service.scan_inactive_members = AsyncMock(
            return_value=(
                [candidate],
                1,
                {"dm_reminders_enabled": 1, "grace_days_after_reminder": 7, "reminder_cooldown_seconds": 0},
            )
        )

        result = await service.execute_reminders("1")

        assert result["dm_ok"] == 1
        assert result["dm_skipped"] == 0
        member.send.assert_awaited()
        database.mark_user_reminded.assert_awaited_once()

    asyncio.run(_run())


def test_execute_kick_pipeline_uses_template_tempban_and_logs_tempban_dm_delivery() -> None:
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
            get_inactivity_user_state=AsyncMock(return_value={"last_reminder_at": None, "reminder_count": 1}),
            add_temp_ban=AsyncMock(),
            mark_user_kicked=AsyncMock(),
            log_inactivity_dm_delivery=AsyncMock(),
        )
        service = InactiveMembersModerationService(database, SimpleNamespace(get_guild=lambda guild_id: guild), member_flow_notifications=None)
        service.scan_inactive_members = AsyncMock(
            return_value=(
                [candidate],
                1,
                {
                    "grace_days_after_reminder": 7,
                    "ban_days": 3,
                    "template_tempban": "Tempban {mention} ({user}) rientra: {rejoin_link}",
                    "invite_url": "https://example.test/invite",
                },
            )
        )

        result = await service.execute_kick_pipeline("1", require_grace=False)

        assert result["dm_ok"] == 1
        assert result["kick_ok"] == 1
        assert result["ban_ok"] == 1
        sent_embed = member.send.await_args.kwargs["embed"]
        assert sent_embed.title == "⌛ __**INTERDIZIONE TEMPORANEA**__"
        description = str(sent_embed.description)
        assert description.startswith("_") and description.endswith("_")
        assert "Tempban ***<@42>*** (***<@42>***)" in description
        assert "***https://example.test/invite***" in description
        assert sent_embed.author.name == "servizio INACTIVITY"
        database.log_inactivity_dm_delivery.assert_awaited_once()
        assert database.log_inactivity_dm_delivery.await_args.kwargs["event_type"] == "tempban"
        assert database.log_inactivity_dm_delivery.await_args.kwargs["outcome"] == "success"

    asyncio.run(_run())


def test_inactivity_template_render_drops_unresolved_placeholders_and_supports_reason_line() -> None:
    service = InactiveMembersModerationService(SimpleNamespace(), SimpleNamespace(), member_flow_notifications=None)
    member = SimpleNamespace(id=42, mention="<@42>", name="user-42", display_name="Dormiente")
    guild = SimpleNamespace(id=1, name="Barcellometro")
    rendered = service._render_template(
        "DM {mention} {event_type} {reason_line}{invite_line}{missing_token}",
        member=member,
        guild=guild,
        event_type="tempban",
        days_inactive=30,
        policy={"window_days": 30, "min_messages": 1},
        cfg={"invite_url": "https://discord.gg/rejoin", "grace_days_after_reminder": 7, "ban_days": 7},
        reason="Inattività prolungata",
        reasoning="inactivity_grace_expired_tempban",
        duration_seconds=3600,
    )

    assert "{missing_token}" not in rendered
    assert rendered.startswith("_") and rendered.endswith("_")
    assert "periodo di grazia per inattività scaduto" in rendered
    assert "Reason:" not in rendered
    assert "Invite: ***https://discord.gg/rejoin***" in rendered
    assert "***<@42>***" in rendered
    assert "***tempban***" in rendered
    assert rendered.count("*") % 2 == 0


def test_build_serverwide_inactive_embeds_uses_intro_description_and_chunked_fields() -> None:
    async def _run() -> None:
        members = [
            SimpleNamespace(id=100 + idx, mention=f"<@{100 + idx}>", display_name=f"Dormiente {idx}", name=f"user{idx}")
            for idx in range(1, 41)
        ]
        inactive = [
            InactiveCandidate(
                member=member,
                last_message_ts=(datetime.now(timezone.utc) - timedelta(days=40)).isoformat(),
                last_channel_id=None,
                last_message_id=None,
                count_in_window=0,
                days_inactive=40,
                policy={"inactive_days": 30, "window_days": 30, "min_messages": 1, "mode": "OR"},
            )
            for member in members
        ]
        guild = SimpleNamespace(id=1, name="Barcellometro")
        database = SimpleNamespace(
            list_inactivity_role_policies=AsyncMock(return_value=[]),
            fetch_inactivity_user_states=AsyncMock(return_value={}),
        )
        service = InactiveMembersModerationService(database, SimpleNamespace(get_guild=lambda guild_id: guild), member_flow_notifications=None)

        embeds, txt_file, _ = await service.build_serverwide_inactive_embeds(
            "1",
            "2",
            inactive=inactive,
            cfg={"default_policy": {}, "grace_days_after_reminder": 7},
            considered=120,
            include_actions_view=False,
        )

        assert embeds
        assert txt_file is not None
        first = embeds[0]
        assert first.title == "🗣️ __**RESOCONTO SERVER · INATTIVI**__"
        assert "#" not in first.title
        assert "Barcellometro" not in first.title
        assert "PAG." not in first.title
        assert "“" not in first.title
        assert first.description.startswith("*") and first.description.endswith("*")
        assert "Panoramica dei membri inattivi" in first.description
        first_names = [field.name for field in first.fields]
        assert format_standard_field_name("MEMBRI ANALIZZATI") in first_names
        assert format_standard_field_name("INATTIVI TROVATI") in first_names
        assert format_standard_field_name("STATO REMINDER") in first_names
        assert format_standard_field_name("INATTIVI", emoji="✏️") in first_names
        assert all("Dormiente" not in (embed.description or "") for embed in embeds)
        merged_field_names = [field.name for embed in embeds for field in embed.fields]
        assert format_standard_field_name("INATTIVI (CONT.)", emoji="✏️") in merged_field_names

    asyncio.run(_run())


def test_build_action_embed_moves_main_content_to_dedicated_details_field() -> None:
    service = InactiveMembersModerationService(SimpleNamespace(), SimpleNamespace(), member_flow_notifications=None)
    embed = service.build_action_embed(
        "🤖 Auto inattivi completata",
        {"dm_ok": 2, "dm_fail": 1, "kick_ok": 3, "kick_fail": 0, "ban_ok": 1, "ban_fail": 0, "notify_ok": 4, "errors": ["timeout"]},
    )

    assert embed.title == "🗣️ __**RESOCONTO SERVER · INATTIVI CHECK**__"
    assert embed.description.startswith("*") and embed.description.endswith("*")
    assert "riepilogo finale" in embed.description.lower()
    assert "DM success/fail" not in embed.description
    detail_field = next(field for field in embed.fields if field.name == format_standard_field_name("DETTAGLI", emoji="📌"))
    assert "• DM success/fail: **2/1**" in detail_field.value
    assert "• Errori: timeout" in detail_field.value


def test_execute_reminders_skips_already_graced_members_and_does_not_reset_timer() -> None:
    async def _run() -> None:
        member = SimpleNamespace(id=42, mention="<@42>", display_name="Dormiente", send=AsyncMock())
        candidate = InactiveCandidate(
            member=member,
            last_message_ts=(datetime.now(timezone.utc) - timedelta(days=40)).isoformat(),
            last_channel_id=None,
            last_message_id=None,
            count_in_window=0,
            days_inactive=40,
            policy={"inactive_days": 30, "window_days": 30, "min_messages": 1, "mode": "OR"},
        )
        guild = SimpleNamespace(id=1, name="Barcellometro")
        database = SimpleNamespace(
            get_inactivity_user_state=AsyncMock(return_value={"last_reminder_at": (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()}),
            mark_user_reminded=AsyncMock(),
            log_inactivity_dm_delivery=AsyncMock(),
        )
        service = InactiveMembersModerationService(database, SimpleNamespace(get_guild=lambda guild_id: guild), member_flow_notifications=None)
        service.scan_inactive_members = AsyncMock(
            return_value=(
                [candidate],
                1,
                {"dm_reminders_enabled": 1, "grace_days_after_reminder": 7},
            )
        )

        result = await service.execute_reminders("1")

        assert result["dm_ok"] == 0
        assert result["dm_skipped"] == 1
        member.send.assert_not_awaited()
        database.mark_user_reminded.assert_not_awaited()
        database.log_inactivity_dm_delivery.assert_awaited_once()
        assert database.log_inactivity_dm_delivery.await_args.kwargs["error_summary"] == "already_in_grace"

    asyncio.run(_run())


def test_execute_reminders_publishes_inactive_grace_notification_when_canonical_visible() -> None:
    async def _run() -> None:
        member = SimpleNamespace(id=42, mention="<@42>", display_name="Dormiente", send=AsyncMock())
        candidate = InactiveCandidate(
            member=member,
            last_message_ts=(datetime.now(timezone.utc) - timedelta(days=40)).isoformat(),
            last_channel_id=None,
            last_message_id=None,
            count_in_window=0,
            days_inactive=40,
            policy={"inactive_days": 30, "window_days": 30, "min_messages": 1, "mode": "OR"},
        )
        guild = SimpleNamespace(id=1, name="Barcellometro")
        database = SimpleNamespace(
            get_inactivity_user_state=AsyncMock(return_value=None),
            mark_user_reminded=AsyncMock(),
            log_inactivity_dm_delivery=AsyncMock(),
        )
        member_flow_notifications = SimpleNamespace(
            log_action=AsyncMock(return_value={"canonical_written": True, "canonical_visible": True, "canonical_event": {"event_type_key": "inactive_grace"}}),
            send_notification=AsyncMock(),
        )
        service = InactiveMembersModerationService(database, SimpleNamespace(get_guild=lambda guild_id: guild), member_flow_notifications=member_flow_notifications)
        service.scan_inactive_members = AsyncMock(
            return_value=(
                [candidate],
                1,
                {"dm_reminders_enabled": 1, "grace_days_after_reminder": 7},
            )
        )

        result = await service.execute_reminders("1")

        assert result["dm_ok"] == 1
        member_flow_notifications.log_action.assert_awaited_once()
        member_flow_notifications.send_notification.assert_awaited_once()
        assert member_flow_notifications.send_notification.await_args.kwargs["action_type"] == "inactive_grace"

    asyncio.run(_run())


def test_handle_post_activity_report_auto_runs_kick_before_reminders() -> None:
    async def _run() -> None:
        member = SimpleNamespace(id=42, mention="<@42>", display_name="Dormiente")
        candidate = InactiveCandidate(
            member=member,
            last_message_ts=(datetime.now(timezone.utc) - timedelta(days=40)).isoformat(),
            last_channel_id=None,
            last_message_id=None,
            count_in_window=0,
            days_inactive=40,
            policy={"inactive_days": 30, "window_days": 30, "min_messages": 1, "mode": "OR"},
        )
        send_mock = AsyncMock()
        service = InactiveMembersModerationService(SimpleNamespace(), SimpleNamespace(), member_flow_notifications=None)
        service._get_config = AsyncMock(return_value={"enabled": True, "auto_enabled": True, "grace_days_after_reminder": 7})
        service.scan_inactive_members = AsyncMock(return_value=([candidate], 1, {"enabled": True}))
        service.post_manual_panel = AsyncMock()
        order: list[str] = []

        async def _kick(_guild_id: str, *, require_grace: bool):
            order.append(f"kick:{require_grace}")
            return {"kick_ok": 1}

        async def _reminders(_guild_id: str):
            order.append("reminders")
            return {"dm_ok": 1}

        service.execute_kick_pipeline = AsyncMock(side_effect=_kick)
        service.execute_reminders = AsyncMock(side_effect=_reminders)
        service.build_auto_inactive_completed_embed = Mock(return_value=SimpleNamespace())
        service._bot = SimpleNamespace(get_guild=lambda guild_id: SimpleNamespace(id=guild_id), get_channel=lambda channel_id: SimpleNamespace(send=send_mock))

        with patch("app.services.inactive_members_moderation.discord.abc.Messageable", object):
            await service.handle_post_activity_report("1", "2")

        assert order == ["kick:True", "reminders"]
        send_mock.assert_awaited_once()

    asyncio.run(_run())
