from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = SimpleNamespace(Row=dict)

if "discord" not in sys.modules:
    discord_stub = types.ModuleType("discord")

    class _Embed:
        def __init__(self, title: str | None = None, color: int | None = None, description: str | None = None):
            self.title = title
            self.color = color
            self.description = description

    class _View:
        def __init__(self, timeout: float | None = None):
            self.timeout = timeout
            self.children = []

    class _Button:
        def __init__(self):
            self.disabled = False

    def _button(*args, **kwargs):
        def deco(fn):
            return fn

        return deco

    discord_stub.Embed = _Embed
    discord_stub.Message = object
    discord_stub.Interaction = object
    discord_stub.ButtonStyle = types.SimpleNamespace(primary=1, secondary=2)
    discord_stub.ui = types.SimpleNamespace(View=_View, Button=_Button, button=_button)
    sys.modules["discord"] = discord_stub

from app.services.daily_activity_report import DailyReportPaginationView


def test_daily_report_pagination_view_disables_edge_buttons() -> None:
    embeds = [
        __import__("discord").Embed(title="p1"),
        __import__("discord").Embed(title="p2"),
        __import__("discord").Embed(title="p3"),
    ]
    view = DailyReportPaginationView(embeds)

    view._index = 0
    view._sync_buttons()
    assert view.prev_button.disabled is True
    assert view.next_button.disabled is False

    view._index = 2
    view._sync_buttons()
    assert view.prev_button.disabled is False
    assert view.next_button.disabled is True


def test_inactive_embed_builder_and_single_send_flow_are_present() -> None:
    inactive_source = Path("app/services/inactive_members_moderation.py").read_text()
    report_source = Path("app/services/daily_activity_report.py").read_text()

    assert "async def build_serverwide_inactive_embeds(" in inactive_source
    assert "-> tuple[list[discord.Embed], discord.File | None, InactivityActionsView | None]" in inactive_source
    assert "build_auto_inactive_completed_embed" in inactive_source
    assert "for extra_embed in embeds[1:]" in inactive_source

    assert "DailyReportPaginationView" in report_source
    assert "build_serverwide_inactive_embeds(" in report_source
    assert "channel.send(embed=report_embeds[0], view=view" in report_source
    assert "for idx in range(0, len(embeds), 10)" not in report_source
