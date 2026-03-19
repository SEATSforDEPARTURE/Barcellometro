from __future__ import annotations

import asyncio
import importlib
import sys
import types
from pathlib import Path

import pytest


@pytest.fixture
def member_flow_module(monkeypatch):
    if "discord" not in sys.modules:
        discord_stub = types.ModuleType("discord")
        discord_stub.File = lambda *args, **kwargs: (args, kwargs)
        discord_stub.Client = object
        discord_stub.Member = object
        discord_stub.Guild = object
        discord_stub.Embed = object
        discord_stub.Colour = types.SimpleNamespace(blurple=lambda: 0)
        discord_stub.ButtonStyle = types.SimpleNamespace(primary=1, danger=2, secondary=3)
        discord_stub.abc = types.SimpleNamespace(User=object, Messageable=object)
        discord_stub.ui = types.SimpleNamespace(View=object, Button=object, button=lambda *args, **kwargs: (lambda fn: fn))
        monkeypatch.setitem(sys.modules, "discord", discord_stub)

    footer_stub = types.ModuleType("app.services.footer")
    footer_stub.attach_footer_meta = lambda embed, **kwargs: embed
    monkeypatch.setitem(sys.modules, "app.services.footer", footer_stub)

    sys.modules.pop("app.services.member_flow_notifications", None)
    return importlib.import_module("app.services.member_flow_notifications")


class _FakeDB:
    async def log_moderation_action(self, **kwargs):
        return "1"


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
    assert service.should_skip_leave_event("1", "2") is True


def test_source_contains_fixed_title_and_footer_service_name() -> None:
    source = Path("app/services/member_flow_notifications.py").read_text()
    assert 'title="🚪 INGRESSI & USCITE"' in source
    assert 'service_name="member_flow_notifications"' in source
