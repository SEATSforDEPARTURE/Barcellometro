from __future__ import annotations

import asyncio
import importlib
import logging
import sys
import types
from pathlib import Path

import pytest

from tests._sqlite_stub import ensure_sqlite_stub

ensure_sqlite_stub()

from app.services.database import DatabaseService


@pytest.fixture
def member_flow_module(monkeypatch):
    discord_stub = types.ModuleType("discord")

    class _Embed:
        def __init__(self, *, title=None, description=None, colour=None, timestamp=None):
            self.title = title
            self.description = description
            self.colour = colour
            self.timestamp = timestamp
            self.fields = []
            self.footer = types.SimpleNamespace(text=None)
            self.author = types.SimpleNamespace(name=None)
            self.thumbnail = types.SimpleNamespace(url=None)

        def add_field(self, *, name, value, inline=True):
            self.fields.append(types.SimpleNamespace(name=name, value=value, inline=inline))

        def set_footer(self, *, text=None):
            self.footer = types.SimpleNamespace(text=text)

        def set_author(self, *, name=None):
            self.author = types.SimpleNamespace(name=name)

        def set_thumbnail(self, *, url=None):
            self.thumbnail = types.SimpleNamespace(url=url)

    discord_stub.File = lambda *args, **kwargs: (args, kwargs)
    discord_stub.Client = object
    discord_stub.Member = object
    discord_stub.Guild = object
    discord_stub.Embed = _Embed
    discord_stub.Colour = types.SimpleNamespace(blurple=lambda: 0)
    discord_stub.ButtonStyle = types.SimpleNamespace(primary=1, danger=2, secondary=3)
    discord_stub.abc = types.SimpleNamespace(User=object, Messageable=object)
    discord_stub.ui = types.SimpleNamespace(View=object, Button=object, button=lambda *args, **kwargs: (lambda fn: fn))
    monkeypatch.setitem(sys.modules, "discord", discord_stub)

    footer_stub = types.ModuleType("app.services.footer")
    footer_stub.attach_footer_meta = lambda embed, **kwargs: embed
    monkeypatch.setitem(sys.modules, "app.services.footer", footer_stub)
    author_stub = types.ModuleType("app.services.author")

    def _attach_author_meta(embed, **kwargs):
        canonical = str(kwargs.get("canonical_top_level_command") or "").strip().upper()
        embed.set_author(name=f"servizio {canonical}" if canonical else "servizio UNKNOWN")
        return embed

    author_stub.attach_author_meta = _attach_author_meta
    monkeypatch.setitem(sys.modules, "app.services.author", author_stub)

    sys.modules.pop("app.services.member_flow_notifications", None)
    return importlib.import_module("app.services.member_flow_notifications")


class _FakeDB:
    async def log_moderation_action(self, **kwargs):
        return "1"

    async def list_recent_visible_departures(self, guild_id: str, user_id: str, since_iso: str):
        return []

    async def get_inactivity_config(self, guild_id: str):
        return {
            "notify_channel_id": "77",
            "atrio_channel_id": "55",
            "invite_url": "https://discord.gg/barcello",
            "notify_card_enabled": False,
            "template_inactivity_reason": "LEGACY DB TEMPLATE {display_name}",
            "atrio_template": "LEGACY ATRIO TEMPLATE {display_name}",
        }


def test_parse_duration_input_supports_days_hours_minutes(member_flow_module) -> None:
    assert member_flow_module.parse_duration_input("7d") == 7 * 86400
    assert member_flow_module.parse_duration_input("12h") == 12 * 3600
    assert member_flow_module.parse_duration_input("30m") == 30 * 60


def test_member_flow_card_fallback_is_safe_without_pillow(member_flow_module, monkeypatch) -> None:
    real_import = __import__

    def _fake_import(name, *args, **kwargs):
        if name == "PIL":
            raise ImportError("missing pillow")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import)

    class _Asset:
        async def read(self):
            return b"avatar"

    class _Member:
        display_avatar = _Asset()
        display_name = "Example"
        name = "Example"

    out = asyncio.run(member_flow_module.generate_member_flow_card(member=_Member(), guild_name="Guild", event_label="WELCOME"))
    assert out is None


def test_member_flow_service_dedupes_leave_after_explicit_action(member_flow_module) -> None:
    service = member_flow_module.MemberFlowNotificationsService(_FakeDB(), object())
    service.remember_departure_action("1", "2", "kick")
    assert asyncio.run(service.should_skip_leave_event("1", "2")) is True


def test_member_flow_log_action_writes_raw_and_canonical_join_leave_and_manual_departures(member_flow_module, tmp_path) -> None:
    async def _run() -> None:
        db = DatabaseService(str(tmp_path / "member_flow.sqlite"))
        await db.connect()
        await db.initialize_schema()
        service = member_flow_module.MemberFlowNotificationsService(db, object())

        join_result = await service.log_action(
            guild_id="1",
            user_id="42",
            action_type="join",
            reason="Ingresso nel server",
            metadata={"source": "discord_adapter"},
        )
        leave_result = await service.log_action(
            guild_id="1",
            user_id="42",
            action_type="leave",
            reason="Uscita naturale",
            metadata={"source": "discord_adapter"},
        )
        kick_result = await service.log_action(
            guild_id="1",
            user_id="77",
            action_type="kick",
            reason="Kick manuale",
            moderator_id="9",
            metadata={"source": "moderazione_utenti"},
        )
        ban_result = await service.log_action(
            guild_id="1",
            user_id="78",
            action_type="ban",
            reason="Ban manuale",
            moderator_id="9",
            metadata={"source": "moderazione_utenti"},
        )
        tempban_result = await service.log_action(
            guild_id="1",
            user_id="79",
            action_type="tempban",
            reason="Tempban manuale",
            moderator_id="9",
            duration_seconds=86400,
            expires_at="2026-03-22T00:00:00+00:00",
            metadata={"source": "moderazione_utenti"},
        )

        raw_counts = {
            row["action_type"]: row["total"]
            for row in await db.fetchall(
                """
                SELECT action_type, COUNT(*) AS total
                FROM moderation_actions
                GROUP BY action_type
                """,
            )
        }
        canonical_rows = await db.fetchall(
            """
            SELECT event_type_key, visible_in_greetings, source, reason, metadata_json
            FROM member_flow_events
            ORDER BY occurred_at ASC
            """,
        )
        raw_rows = await db.fetchall(
            """
            SELECT action_type, reason, metadata_json
            FROM moderation_actions
            WHERE action_type IN ('kick', 'ban')
            ORDER BY created_at ASC
            """,
        )

        assert join_result["canonical_written"] is True
        assert leave_result["canonical_written"] is True
        assert kick_result["canonical_written"] is True
        assert ban_result["canonical_written"] is True
        assert tempban_result["canonical_written"] is True
        assert raw_counts == {
            "join": 1,
            "leave": 1,
            "kick": 1,
            "ban": 1,
            "tempban": 1,
        }
        assert [(row["event_type_key"], int(row["visible_in_greetings"]), row["source"]) for row in canonical_rows] == [
            ("join", 1, "discord_adapter"),
            ("leave", 1, "discord_adapter"),
            ("kick", 1, "moderazione_utenti"),
            ("ban", 1, "moderazione_utenti"),
            ("tempban", 1, "moderazione_utenti"),
        ]
        assert [(row["action_type"], row["reason"]) for row in raw_rows] == [
            ("kick", "Kick manuale"),
            ("ban", "Ban manuale"),
        ]
        kick_canonical = canonical_rows[2]
        ban_canonical = canonical_rows[3]
        assert kick_canonical["reason"] == "Kick manuale"
        assert ban_canonical["reason"] == "Ban manuale"
        assert '"raw_action_id"' in kick_canonical["metadata_json"]
        assert '"raw_action_id"' in ban_canonical["metadata_json"]

        await db.close()

    asyncio.run(_run())


def test_member_flow_log_action_supports_unban_without_mirror_warning(member_flow_module, tmp_path, caplog) -> None:
    async def _run() -> None:
        db = DatabaseService(str(tmp_path / "member_flow_unban.sqlite"))
        await db.connect()
        await db.initialize_schema()
        service = member_flow_module.MemberFlowNotificationsService(db, object())

        with caplog.at_level(logging.WARNING):
            result = await service.log_action(
                guild_id="1",
                user_id="88",
                action_type="unban",
                reason="Revoca ban",
                moderator_id="9",
                metadata={"source": "discord_adapter"},
            )

        stored = await db.fetchall(
            """
            SELECT event_type_key, visible_in_greetings, source, reason
            FROM member_flow_events
            ORDER BY occurred_at ASC
            """,
        )

        assert result["canonical_written"] is True
        assert result["canonical_visible"] is False
        assert result["canonical_event"] is not None
        assert result["canonical_event"]["event_type_key"] == "unban"
        assert result["canonical_event"]["visible_in_greetings"] is False
        assert [(row["event_type_key"], int(row["visible_in_greetings"]), row["source"], row["reason"]) for row in stored] == [
            ("unban", 0, "discord_adapter", "Revoca ban"),
        ]
        assert "member flow event mirror failed" not in caplog.text

        await db.close()

    asyncio.run(_run())


def test_member_flow_leave_dedupe_is_restart_safe_and_ignores_non_departures(member_flow_module, tmp_path) -> None:
    async def _run() -> None:
        db = DatabaseService(str(tmp_path / "member_flow_restart.sqlite"))
        await db.connect()
        await db.initialize_schema()

        first_service = member_flow_module.MemberFlowNotificationsService(db, object())
        await first_service.log_action(
            guild_id="55",
            user_id="7",
            action_type="kick",
            reason="Kick manuale",
            metadata={"source": "moderazione_utenti"},
        )

        restarted_service = member_flow_module.MemberFlowNotificationsService(db, object())
        assert await restarted_service.should_skip_leave_event("55", "7") is True
        leave_result = await restarted_service.log_action(
            guild_id="55",
            user_id="7",
            action_type="leave",
            reason="Gateway leave dopo kick",
            metadata={"source": "discord_adapter"},
        )

        grace_service = member_flow_module.MemberFlowNotificationsService(db, object())
        await grace_service.log_action(
            guild_id="55",
            user_id="9",
            action_type="grace",
            reason="Grace manuale",
            metadata={"source": "moderazione_utenti"},
        )
        await grace_service.log_action(
            guild_id="55",
            user_id="10",
            action_type="inactive_grace",
            reason="Reminder inattività",
            metadata={"source": "inactive_members_moderation"},
        )
        assert await grace_service.should_skip_leave_event("55", "9") is False
        assert await grace_service.should_skip_leave_event("55", "10") is False
        leave_after_grace = await grace_service.log_action(
            guild_id="55",
            user_id="9",
            action_type="leave",
            reason="Leave dopo grace",
            metadata={"source": "discord_adapter"},
        )

        raw_leave_count = await db.fetchone(
            "SELECT COUNT(*) AS total FROM moderation_actions WHERE guild_id = ? AND user_id = ? AND action_type = 'leave'",
            ("55", "7"),
        )
        canonical_leave_count = await db.fetchone(
            "SELECT COUNT(*) AS total FROM member_flow_events WHERE guild_id = ? AND user_id = ? AND event_type_key = 'leave'",
            ("55", "7"),
        )
        hidden_leave = await db.fetchone(
            """
            SELECT visible_in_greetings
            FROM member_flow_events
            WHERE guild_id = ? AND user_id = ? AND event_type_key = 'leave'
            ORDER BY occurred_at DESC
            LIMIT 1
            """,
            ("55", "7"),
        )

        assert leave_result["canonical_written"] is True
        assert leave_result["canonical_visible"] is False
        assert leave_after_grace["canonical_written"] is True
        assert int(raw_leave_count["total"]) == 1
        assert int(canonical_leave_count["total"]) == 1
        assert int(hidden_leave["visible_in_greetings"]) == 0

        await db.close()

    asyncio.run(_run())


def test_member_flow_explicit_departure_hides_recent_visible_leave_but_keeps_backend_history(member_flow_module, tmp_path) -> None:
    async def _run() -> None:
        db = DatabaseService(str(tmp_path / "member_flow_leave_suppression.sqlite"))
        await db.connect()
        await db.initialize_schema()
        service = member_flow_module.MemberFlowNotificationsService(db, object())

        leave_result = await service.log_action(
            guild_id="77",
            user_id="42",
            action_type="leave",
            reason="Gateway remove iniziale",
            metadata={"source": "discord_adapter"},
        )
        kick_result = await service.log_action(
            guild_id="77",
            user_id="42",
            action_type="kick",
            reason="Kick manuale definitivo",
            metadata={"source": "moderazione_utenti"},
        )

        raw_rows = await db.fetchall(
            """
            SELECT action_type
            FROM moderation_actions
            WHERE guild_id = ? AND user_id = ?
            ORDER BY created_at ASC
            """,
            ("77", "42"),
        )
        canonical_rows = await db.fetchall(
            """
            SELECT event_type_key, visible_in_greetings
            FROM member_flow_events
            WHERE guild_id = ? AND user_id = ?
            ORDER BY occurred_at ASC, id ASC
            """,
            ("77", "42"),
        )

        assert leave_result["canonical_written"] is True
        assert leave_result["canonical_visible"] is True
        assert kick_result["canonical_written"] is True
        assert kick_result["canonical_visible"] is True
        assert [row["action_type"] for row in raw_rows] == ["leave", "kick"]
        assert [(row["event_type_key"], int(row["visible_in_greetings"])) for row in canonical_rows] == [
            ("leave", 0),
            ("kick", 1),
        ]

        await db.close()

    asyncio.run(_run())


def test_member_flow_inactive_tempban_hides_inactive_kick_in_same_operation(member_flow_module, tmp_path) -> None:
    async def _run() -> None:
        db = DatabaseService(str(tmp_path / "member_flow_inactive.sqlite"))
        await db.connect()
        await db.initialize_schema()
        service = member_flow_module.MemberFlowNotificationsService(db, object())

        operation_id = "inactive-op-1"
        inactive_kick = await service.log_action(
            guild_id="91",
            user_id="12",
            action_type="inactive_kick",
            reason="Kick per inattività",
            metadata={
                "source": "inactive_members_moderation",
                "operation_id": operation_id,
                "visible_in_greetings": False,
            },
        )
        inactive_tempban = await service.log_action(
            guild_id="91",
            user_id="12",
            action_type="inactive_tempban",
            reason="Tempban per inattività",
            duration_seconds=7 * 86400,
            expires_at="2026-03-28T00:00:00+00:00",
            metadata={
                "source": "inactive_members_moderation",
                "operation_id": operation_id,
            },
        )

        rows = await db.list_member_flow_events_by_operation_id("91", operation_id)

        assert inactive_kick["canonical_written"] is True
        assert inactive_tempban["canonical_written"] is True
        assert [(row["event_type_key"], row["visible_in_greetings"]) for row in rows] == [
            ("inactive_kick", False),
            ("inactive_tempban", True),
        ]

        await db.close()

    asyncio.run(_run())


def test_member_flow_operation_duplicate_keeps_backend_audit_but_hides_second_feed_event(member_flow_module, tmp_path) -> None:
    async def _run() -> None:
        db = DatabaseService(str(tmp_path / "member_flow_operation_dupe.sqlite"))
        await db.connect()
        await db.initialize_schema()
        service = member_flow_module.MemberFlowNotificationsService(db, object())

        first = await service.log_action(
            guild_id="88",
            user_id="55",
            action_type="ban",
            reason="Ban audit 1",
            metadata={
                "source": "discord_adapter",
                "operation_id": "discord_native:88:ban:entry-1",
            },
        )
        second = await service.log_action(
            guild_id="88",
            user_id="55",
            action_type="ban",
            reason="Ban audit 2",
            metadata={
                "source": "discord_adapter",
                "operation_id": "discord_native:88:ban:entry-1",
            },
        )

        raw_rows = await db.fetchall(
            """
            SELECT action_type, reason
            FROM moderation_actions
            WHERE guild_id = ? AND user_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            ("88", "55"),
        )
        canonical_rows = await db.fetchall(
            """
            SELECT event_type_key, visible_in_greetings, reason, operation_id
            FROM member_flow_events
            WHERE guild_id = ? AND user_id = ?
            ORDER BY occurred_at ASC, id ASC
            """,
            ("88", "55"),
        )

        assert first["canonical_visible"] is True
        assert second["canonical_visible"] is False
        assert [row["reason"] for row in raw_rows] == ["Ban audit 1", "Ban audit 2"]
        assert [(row["event_type_key"], int(row["visible_in_greetings"]), row["operation_id"]) for row in canonical_rows] == [
            ("ban", 1, "discord_native:88:ban:entry-1"),
            ("ban", 0, "discord_native:88:ban:entry-1"),
        ]

        await db.close()

    asyncio.run(_run())


def test_source_contains_author_title_mapping_and_footer_service_name() -> None:
    source = Path("app/services/member_flow_notifications.py").read_text(encoding="utf-8")
    assert 'embed = discord.Embed(title=copy.event_label, description=copy.narrative[:4096], colour=self._colour_for_event_type(str(canonical_payload.get("event_type_key") or action_type)))' in source
    assert '_ENTRY_LIKE_EVENT_TYPES = frozenset({"join", "grace", "inactive_grace"})' in source
    assert '"inactive_tempban",' in source
    assert 'attach_author_meta(' in source
    assert 'canonical_top_level_command="greetings"' in source
    assert 'embed.set_author(name="🚪 INGRESSI & USCITE")' not in source
    assert 'service_name="member_flow_notifications"' in source
    assert 'embed.add_field(name="Evento"' not in source
    assert 'timestamp=created_at' not in source
    assert 'set_footer(' not in source
    assert 'Oggi alle' not in source


def test_send_notification_renders_author_title_description_and_footer_from_canonical_event(member_flow_module) -> None:
    class _Channel:
        def __init__(self) -> None:
            self.sent = []

        async def send(self, *, embed=None, files=None):
            self.sent.append({"embed": embed, "files": files})

    class _Guild:
        id = 1
        name = "Barcellometro"

        def __init__(self, channel) -> None:
            self._channel = channel

        def get_channel(self, channel_id: int):
            return self._channel if channel_id == 77 else None

    async def _run() -> None:
        channel = _Channel()
        guild = _Guild(channel)
        user = types.SimpleNamespace(
            id=42,
            mention="<@42>",
            name="new_user",
            display_name="New User",
            display_avatar=types.SimpleNamespace(url="https://example.test/avatar.png"),
        )
        service = member_flow_module.MemberFlowNotificationsService(_FakeDB(), object())

        await service.send_notification(
            guild=guild,
            user=user,
            action_type="inactive_tempban",
            canonical_event={
                "event_type_key": "inactive_tempban",
                "reason": "Assenza prolungata",
                "duration_seconds": 7 * 86400,
                "visible_in_greetings": True,
                "metadata": {
                    "inactivity_text": "30 giorni",
                    "occurrence_number": 1,
                },
            },
        )

        payload = channel.sent[0]["embed"]
        assert payload.author.name == "servizio GREETINGS"
        assert payload.title == "**💤 PRIMO BAN TEMPORANEO PER INATTIVITÀ**"
        assert payload.description is not None
        assert payload.description == payload.description[:4096]
        assert payload.fields == []
        assert payload.thumbnail.url == "https://example.test/avatar.png"
        assert payload.timestamp is None
        assert 'Stato barcello "Barcellometro"' not in payload.description
        assert "ALLERTA" not in payload.title
        assert "inattività" in payload.description.lower()

    asyncio.run(_run())


def test_send_notification_appends_reason_block_inside_description_without_extra_fields(member_flow_module) -> None:
    class _Channel:
        def __init__(self) -> None:
            self.sent = []

        async def send(self, *, embed=None, files=None):
            self.sent.append({"embed": embed, "files": files})

    class _Guild:
        id = 1
        name = "Barcellometro"

        def __init__(self, channel) -> None:
            self._channel = channel

        def get_channel(self, channel_id: int):
            return self._channel if channel_id == 77 else None

    async def _run() -> None:
        channel = _Channel()
        guild = _Guild(channel)
        user = types.SimpleNamespace(
            id=42,
            mention="<@42>",
            name="new_user",
            display_name="New User",
            display_avatar=types.SimpleNamespace(url="https://example.test/avatar.png"),
        )
        service = member_flow_module.MemberFlowNotificationsService(_FakeDB(), object())

        await service.send_notification(
            guild=guild,
            user=user,
            action_type="kick",
            canonical_event={
                "event_type_key": "kick",
                "reason": "Motivo tecnico non editoriale",
                "visible_in_greetings": True,
                "metadata": {
                    "occurrence_number": 1,
                    "greetings_reason": "Spam creativo",
                },
            },
        )

        payload = channel.sent[0]["embed"]
        assert payload.description is not None
        assert "**👇 La moderazione aggiunge:**" in payload.description
        assert "Spam creativo" in payload.description
        assert "Motivo tecnico non editoriale" not in payload.description
        assert payload.fields == []

    asyncio.run(_run())


def test_send_notification_skips_reason_block_when_greetings_reason_is_missing(member_flow_module) -> None:
    class _Channel:
        def __init__(self) -> None:
            self.sent = []

        async def send(self, *, embed=None, files=None):
            self.sent.append({"embed": embed, "files": files})

    class _Guild:
        id = 1
        name = "Barcellometro"

        def __init__(self, channel) -> None:
            self._channel = channel

        def get_channel(self, channel_id: int):
            return self._channel if channel_id == 77 else None

    async def _run() -> None:
        channel = _Channel()
        guild = _Guild(channel)
        user = types.SimpleNamespace(
            id=42,
            mention="<@42>",
            name="new_user",
            display_name="New User",
            display_avatar=types.SimpleNamespace(url="https://example.test/avatar.png"),
        )
        service = member_flow_module.MemberFlowNotificationsService(_FakeDB(), object())

        await service.send_notification(
            guild=guild,
            user=user,
            action_type="ban",
            canonical_event={
                "event_type_key": "ban",
                "reason": "Ban tramite moderazione nativa Discord",
                "visible_in_greetings": True,
                "metadata": {
                    "occurrence_number": 1,
                    "greetings_reason": None,
                },
            },
        )

        payload = channel.sent[0]["embed"]
        assert payload.description is not None
        assert "**👇 La moderazione aggiunge:**" not in payload.description
        assert payload.fields == []

    asyncio.run(_run())


def test_member_flow_renderer_source_mentions_final_author_title_layout() -> None:
    source = Path("app/services/member_flow_notifications.py").read_text(encoding="utf-8")

    assert "derivato dal top-level canonico (non hardcoded)" in source
    assert "attach_author_meta(" in source
    assert "embed.set_thumbnail(url=avatar_url)" in source
    assert 'title=copy.event_label' in source
    assert 'description=copy.narrative[:4096]' in source
    assert 'embed.add_field(name="Evento"' not in source
    assert 'Stato barcello "' not in source
    assert 'Oggi alle' not in source


def test_send_notification_uses_copy_service_values_and_join_copy(member_flow_module, monkeypatch) -> None:
    attached = {}

    def _attach_footer(embed, **kwargs):
        attached["service_name"] = kwargs.get("service_name")
        embed.set_footer(text="Barcellometro dev")
        return embed

    monkeypatch.setattr(member_flow_module, "attach_footer_meta", _attach_footer)

    class _Channel:
        def __init__(self) -> None:
            self.sent = []

        async def send(self, *, embed=None, files=None):
            self.sent.append(embed)

    class _Guild:
        id = 1
        name = "Barcellometro"

        def __init__(self, channel) -> None:
            self._channel = channel

        def get_channel(self, channel_id: int):
            return self._channel

    async def _run() -> None:
        channel = _Channel()
        guild = _Guild(channel)
        user = types.SimpleNamespace(
            id=42,
            mention="<@42>",
            name="new_user",
            display_name="New User",
            display_avatar=types.SimpleNamespace(url="https://example.test/avatar.png"),
        )
        service = member_flow_module.MemberFlowNotificationsService(_FakeDB(), object())

        await service.send_notification(
            guild=guild,
            user=user,
            action_type="join",
            canonical_event={
                "event_type_key": "join",
                "reason": "Ingresso nel server",
                "visible_in_greetings": True,
                "metadata": {
                    "occurrence_number": 1,
                },
            },
        )

        embed = channel.sent[0]
        assert embed.author.name == "servizio GREETINGS"
        assert embed.title == "**✨ PRIMO INGRESSO**"
        assert "benvenut" in embed.description.lower()
        assert "<@42>" in embed.description
        assert embed.footer.text == "Barcellometro dev"
        assert attached["service_name"] == "member_flow_notifications"

    asyncio.run(_run())


def test_send_notification_ignores_legacy_db_template_values(member_flow_module) -> None:
    class _Channel:
        def __init__(self) -> None:
            self.sent = []

        async def send(self, *, embed=None, files=None):
            self.sent.append(embed)

    class _Guild:
        id = 1
        name = "Barcellometro"

        def __init__(self, channel) -> None:
            self._channel = channel

        def get_channel(self, channel_id: int):
            return self._channel

    async def _run() -> None:
        channel = _Channel()
        guild = _Guild(channel)
        user = types.SimpleNamespace(
            id=42,
            mention="<@42>",
            name="new_user",
            display_name="New User",
            display_avatar=types.SimpleNamespace(url="https://example.test/avatar.png"),
        )
        service = member_flow_module.MemberFlowNotificationsService(_FakeDB(), object())

        await service.send_notification(
            guild=guild,
            user=user,
            action_type="inactive_kick",
            canonical_event={
                "event_type_key": "inactive_kick",
                "reason": "Inattività prolungata",
                "visible_in_greetings": True,
                "metadata": {
                    "inactivity_text": "30 giorni",
                    "occurrence_number": 1,
                },
            },
        )

        narrative = channel.sent[0].description
        assert "LEGACY DB TEMPLATE" not in narrative
        assert "LEGACY ATRIO TEMPLATE" not in narrative
        assert "30 giorni" in narrative

    asyncio.run(_run())


@pytest.mark.parametrize(
    ("event_type", "expected_colour"),
    [
        ("join", 0xC58C5C),
        ("grace", 0xC58C5C),
        ("inactive_grace", 0xC58C5C),
        ("leave", 0x6B4423),
        ("kick", 0x6B4423),
        ("ban", 0x6B4423),
        ("tempban", 0x6B4423),
        ("inactive_kick", 0x6B4423),
        ("inactive_tempban", 0x6B4423),
    ],
)
def test_send_notification_uses_canonical_greetings_palette_by_event_type(member_flow_module, event_type: str, expected_colour: int) -> None:
    class _Channel:
        def __init__(self) -> None:
            self.sent = []

        async def send(self, *, embed=None, files=None):
            self.sent.append(embed)

    class _Guild:
        id = 1
        name = "Barcellometro"

        def __init__(self, channel) -> None:
            self._channel = channel

        def get_channel(self, channel_id: int):
            return self._channel

    async def _run() -> None:
        channel = _Channel()
        guild = _Guild(channel)
        user = types.SimpleNamespace(
            id=42,
            mention="<@42>",
            name="new_user",
            display_name="New User",
            display_avatar=types.SimpleNamespace(url="https://example.test/avatar.png"),
        )
        service = member_flow_module.MemberFlowNotificationsService(_FakeDB(), object())

        await service.send_notification(
            guild=guild,
            user=user,
            action_type=event_type,
            canonical_event={
                "event_type_key": event_type,
                "reason": f"Evento {event_type}",
                "visible_in_greetings": True,
                "metadata": {"occurrence_number": 1},
            },
        )

        embed = channel.sent[0]
        assert embed.colour == expected_colour
        assert embed.author.name == "servizio GREETINGS"
        assert embed.fields == []

    asyncio.run(_run())


def test_send_notification_uses_copy_service_as_single_source_for_title_and_description(member_flow_module) -> None:
    class _Channel:
        def __init__(self) -> None:
            self.sent = []

        async def send(self, *, embed=None, files=None):
            self.sent.append(embed)

    class _Guild:
        id = 1
        name = "Barcellometro"

        def __init__(self, channel) -> None:
            self._channel = channel

        def get_channel(self, channel_id: int):
            return self._channel

    async def _run() -> None:
        channel = _Channel()
        guild = _Guild(channel)
        user = types.SimpleNamespace(
            id=42,
            mention="<@42>",
            name="new_user",
            display_name="New User",
            display_avatar=types.SimpleNamespace(url="https://example.test/avatar.png"),
        )
        service = member_flow_module.MemberFlowNotificationsService(_FakeDB(), object())
        service._copy_service.render_canonical_event_copy = types.MethodType(
            lambda self, **kwargs: asyncio.sleep(
                0,
                result=types.SimpleNamespace(
                    event_label="COPY EVENT LABEL",
                    narrative="COPY NARRATIVE",
                ),
            ),
            service._copy_service,
        )

        await service.send_notification(
            guild=guild,
            user=user,
            action_type="leave",
            canonical_event={
                "event_type_key": "leave",
                "reason": "Uscita dal server",
                "visible_in_greetings": True,
                "metadata": {},
            },
        )

        embed = channel.sent[0]
        assert embed.author.name == "servizio GREETINGS"
        assert embed.title == "COPY EVENT LABEL"
        assert embed.description == "COPY NARRATIVE"
        assert embed.fields == []

    asyncio.run(_run())


def test_send_notification_reads_runtime_values_only_from_canonical_timeline(member_flow_module) -> None:
    class _Channel:
        def __init__(self) -> None:
            self.sent = []

        async def send(self, *, embed=None, files=None):
            self.sent.append(embed)

    class _Guild:
        id = 1
        name = "Barcellometro"

        def __init__(self, channel) -> None:
            self._channel = channel

        def get_channel(self, channel_id: int):
            return self._channel

    async def _run() -> None:
        channel = _Channel()
        guild = _Guild(channel)
        user = types.SimpleNamespace(
            id=42,
            mention="<@42>",
            name="new_user",
            display_name="New User",
            display_avatar=types.SimpleNamespace(url="https://example.test/avatar.png"),
        )
        service = member_flow_module.MemberFlowNotificationsService(_FakeDB(), object())
        service._copy_service.render_event_copy = types.MethodType(  # type: ignore[method-assign]
            lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("live runtime must use canonical timeline copy")),
            service._copy_service,
        )
        service._copy_service.render_canonical_event_copy = types.MethodType(
            lambda self, **kwargs: asyncio.sleep(
                0,
                result=types.SimpleNamespace(
                    event_label="CANONICAL EVENT",
                    narrative="CANONICAL NARRATIVE",
                ),
            ),
            service._copy_service,
        )

        await service.send_notification(
            guild=guild,
            user=user,
            action_type="leave",
            canonical_event={
                "event_type_key": "leave",
                "reason": "Uscita dal server",
                "visible_in_greetings": True,
                "metadata": {"occurrence_number": 2},
            },
        )

        embed = channel.sent[0]
        assert embed.author.name == "servizio GREETINGS"
        assert embed.title == "CANONICAL EVENT"
        assert embed.description == "CANONICAL NARRATIVE"
        assert embed.fields == []

    asyncio.run(_run())


def test_send_notification_uses_avatar_fallback_when_display_avatar_is_missing(member_flow_module) -> None:
    class _Channel:
        def __init__(self) -> None:
            self.sent = []

        async def send(self, *, embed=None, files=None):
            self.sent.append(embed)

    class _Guild:
        id = 1
        name = "Barcellometro"

        def __init__(self, channel) -> None:
            self._channel = channel

        def get_channel(self, channel_id: int):
            return self._channel

    async def _run() -> None:
        channel = _Channel()
        guild = _Guild(channel)
        user = types.SimpleNamespace(
            id=42,
            mention="<@42>",
            name="new_user",
            display_name="New User",
            display_avatar=None,
            avatar=types.SimpleNamespace(url="https://example.test/avatar-fallback.png"),
        )
        service = member_flow_module.MemberFlowNotificationsService(_FakeDB(), object())

        await service.send_notification(
            guild=guild,
            user=user,
            action_type="leave",
            canonical_event={
                "event_type_key": "leave",
                "reason": "Uscita dal server",
                "visible_in_greetings": True,
                "metadata": {"occurrence_number": 1},
            },
        )

        embed = channel.sent[0]
        assert embed.thumbnail.url == "https://example.test/avatar-fallback.png"

    asyncio.run(_run())


def test_send_notification_keeps_thumbnail_empty_when_no_avatar_is_available(member_flow_module) -> None:
    class _Channel:
        def __init__(self) -> None:
            self.sent = []

        async def send(self, *, embed=None, files=None):
            self.sent.append(embed)

    class _Guild:
        id = 1
        name = "Barcellometro"

        def __init__(self, channel) -> None:
            self._channel = channel

        def get_channel(self, channel_id: int):
            return self._channel

    async def _run() -> None:
        channel = _Channel()
        guild = _Guild(channel)
        user = types.SimpleNamespace(
            id=42,
            mention="<@42>",
            name="new_user",
            display_name="New User",
            display_avatar=None,
            avatar=None,
            default_avatar=None,
        )
        service = member_flow_module.MemberFlowNotificationsService(_FakeDB(), object())

        await service.send_notification(
            guild=guild,
            user=user,
            action_type="leave",
            canonical_event={
                "event_type_key": "leave",
                "reason": "Uscita dal server",
                "visible_in_greetings": True,
                "metadata": {"occurrence_number": 1},
            },
        )

        embed = channel.sent[0]
        assert embed.thumbnail.url is None

    asyncio.run(_run())
