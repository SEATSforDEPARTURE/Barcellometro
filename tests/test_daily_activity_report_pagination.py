from __future__ import annotations

import io
import sys
import types
from pathlib import Path
from types import SimpleNamespace

if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = SimpleNamespace(Row=dict)

if "httpx" not in sys.modules:
    sys.modules["httpx"] = SimpleNamespace()

if "discord" not in sys.modules:
    discord_stub = types.ModuleType("discord")

    class _Embed:
        def __init__(self, title: str | None = None, color: int | None = None, description: str | None = None):
            self.title = title
            self.color = color
            self.description = description

        def to_dict(self):
            return {"title": self.title, "description": self.description, "color": self.color}

        @classmethod
        def from_dict(cls, data):
            return cls(title=data.get("title"), description=data.get("description"), color=data.get("color"))

    class _File:
        def __init__(self, fp, filename: str):
            self.fp = fp
            self.filename = filename

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
    discord_stub.File = _File
    discord_stub.Message = object
    discord_stub.Interaction = object
    discord_stub.ButtonStyle = types.SimpleNamespace(primary=1, secondary=2)
    discord_stub.ui = types.SimpleNamespace(View=_View, Button=_Button, button=_button)
    sys.modules["discord"] = discord_stub

from app.features.activity.services.activity_report_service import build_combined_activity_inactive_txt


def test_combined_txt_single_attachment_payload_has_visible_sections() -> None:
    payload, filename, file = build_combined_activity_inactive_txt(
        activity_txt_payload="attività",
        inactive_txt_payload="inattivi",
    )

    assert "SEZIONE 1 — REPORT ATTIVITÀ DETTAGLIATO" in payload
    assert "SEZIONE 2 — INATTIVI SERVER-WIDE" in payload
    assert payload.index("SEZIONE 1") < payload.index("SEZIONE 2")
    assert filename.startswith("report_attivita_e_inattivi_")
    assert filename.endswith(".txt")
    assert file.filename == filename


def test_combined_txt_supports_single_section_without_extra_files() -> None:
    payload, _, file = build_combined_activity_inactive_txt(
        activity_txt_payload="solo attività",
        inactive_txt_payload=None,
    )

    assert "SEZIONE 1 — REPORT ATTIVITÀ DETTAGLIATO" in payload
    assert "SEZIONE 2 — INATTIVI SERVER-WIDE" not in payload
    assert isinstance(file.fp, io.BytesIO)


def test_daily_report_view_buttons_order_timeout_and_custom_ids_are_present() -> None:
    report_source = Path("app/features/activity/services/activity_report_service.py").read_text()

    start_idx = report_source.index('label="⏮️ INIZIO"')
    prev_idx = report_source.index('label="⬅️ INDIETRO"')
    next_idx = report_source.index('label="➡️ AVANTI"')

    assert start_idx < prev_idx < next_idx
    assert "super().__init__(timeout=None)" in report_source
    assert 'custom_id="daily_report:nav:start"' in report_source
    assert 'custom_id="daily_report:nav:prev"' in report_source
    assert 'custom_id="daily_report:nav:next"' in report_source


def test_daily_report_view_button_states_sync_logic_is_present() -> None:
    report_source = Path("app/features/activity/services/activity_report_service.py").read_text()

    assert "def _sync_button_states(self) -> None:" in report_source
    assert "is_first = self._current_index <= 0" in report_source
    assert "is_last = self._current_index >= self._total_pages - 1" in report_source
    assert "self.start_button.disabled = is_first" in report_source
    assert "self.prev_button.disabled = is_first" in report_source
    assert "self.next_button.disabled = is_last" in report_source


def test_daily_report_view_sync_is_called_at_init_and_after_navigation() -> None:
    report_source = Path("app/features/activity/services/activity_report_service.py").read_text()

    assert "self._sync_button_states()" in report_source
    assert "self._current_index = target_index" in report_source
    assert "self._total_pages = len(embeds_payload)" in report_source


def test_daily_report_uses_single_file_send_and_never_two_txt_attachments() -> None:
    report_source = Path("app/features/activity/services/activity_report_service.py").read_text()

    assert "build_combined_activity_inactive_txt(" in report_source
    assert "channel.send(embed=report_embeds[0], view=view, file=txt_file)" in report_source
    assert "files=[txt_file, inactive_txt_file]" not in report_source


def test_daily_report_pagination_persistence_db_methods_are_present() -> None:
    database_source = Path("app/services/database.py").read_text()

    assert "CREATE TABLE IF NOT EXISTS daily_report_pagination_state" in database_source
    assert "async def upsert_daily_report_pagination_state(" in database_source
    assert "async def get_daily_report_pagination_state(" in database_source
    assert "async def update_daily_report_pagination_current_index(" in database_source


def test_inactive_embed_builder_and_single_send_flow_are_present() -> None:
    inactive_source = Path("app/services/inactive_members_moderation.py").read_text()
    report_source = Path("app/features/activity/services/activity_report_service.py").read_text()

    assert "async def build_serverwide_inactive_embeds(" in inactive_source
    assert "-> tuple[list[discord.Embed], discord.File | None, InactivityActionsView | None]" in inactive_source
    assert "build_auto_inactive_completed_embed" in inactive_source
    assert "for extra_embed in embeds[1:]" in inactive_source

    assert "DailyReportPaginationView" in report_source
    assert "build_serverwide_inactive_embeds(" in report_source
    assert "channel.send(embed=report_embeds[0], view=view" in report_source
    assert "for idx in range(0, len(embeds), 10)" not in report_source
