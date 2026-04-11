from __future__ import annotations

import asyncio
import io
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import discord

if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = SimpleNamespace(Row=dict)

if "httpx" not in sys.modules:
    sys.modules["httpx"] = SimpleNamespace()

from app.services.daily_activity_report import (
    DailyActivityReportService,
    DailyReportPaginationView,
    build_combined_activity_inactive_txt,
)
from app.services.footer import FooterService, attach_footer_meta, get_footer_meta
from app.shared.discord.embed_body import format_standard_title


class _FakePaginationDatabase:
    def __init__(self) -> None:
        self.settings: dict[str, str] = {}
        self.pagination_state: dict[str, dict[str, object]] = {}

    async def get_setting(self, key: str) -> str | None:
        return self.settings.get(key)

    async def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value

    async def delete_setting(self, key: str) -> None:
        self.settings.pop(key, None)

    async def execute(self, _query: str, _params: tuple[str, ...]) -> None:
        return None

    async def fetchall(self, query: str, params: tuple[str, ...]):
        prefix = str(params[0]).replace('%', '') if params else ''
        if 'FROM settings' not in query:
            return []
        return [
            {'key': key, 'value': value}
            for key, value in sorted(self.settings.items())
            if not prefix or key.startswith(prefix)
        ]

    async def upsert_daily_report_pagination_state(
        self,
        *,
        message_id: str,
        channel_id: str,
        guild_id: str,
        report_type: str,
        embeds_json: str,
        metadata_json: str,
        current_index: int,
    ) -> None:
        self.pagination_state[message_id] = {
            'message_id': message_id,
            'channel_id': channel_id,
            'guild_id': guild_id,
            'report_type': report_type,
            'embeds_json': embeds_json,
            'metadata_json': metadata_json,
            'current_index': current_index,
        }

    async def get_daily_report_pagination_state(self, *, message_id: str):
        return self.pagination_state.get(message_id)

    async def update_daily_report_pagination_current_index(self, *, message_id: str, current_index: int) -> None:
        if message_id in self.pagination_state:
            self.pagination_state[message_id]['current_index'] = current_index


class _FakeBot:
    def __init__(self) -> None:
        self.views: list[object] = []

    def add_view(self, view: object) -> None:
        self.views.append(view)


def _build_service() -> tuple[DailyActivityReportService, _FakePaginationDatabase, FooterService]:
    database = _FakePaginationDatabase()
    footer_service = FooterService(database)
    service = DailyActivityReportService(
        database,
        _FakeBot(),
        activity_service=object(),
        footer_service=footer_service,
    )
    return service, database, footer_service


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


def test_daily_report_persisted_pagination_stores_footer_context_per_embed() -> None:
    async def _run() -> None:
        service, _, _ = _build_service()
        activity_embed = discord.Embed(title="Pagina attività", description="Contenuto attività")
        inactive_embed = discord.Embed(title="Pagina inattivi", description="Contenuto inattivi")
        attach_footer_meta(activity_embed, service_name="daily_activity_report", used_local_processing=True)
        attach_footer_meta(inactive_embed, service_name="inactivity_moderation", contributors=["gpt-4o-mini"], used_local_processing=False)

        await service.persist_pagination_record(
            message_id="42",
            channel_id="7",
            guild_id="9",
            embeds=[activity_embed, inactive_embed],
            metadata={"has_activity": True, "has_inactive": True},
            current_index=0,
        )
        record = await service.load_pagination_record(message_id="42")

        assert record is not None
        first = record["embeds"][0]
        second = record["embeds"][1]
        assert first["embed"]["title"] == "Pagina attività"
        assert second["embed"]["description"] == "Contenuto inattivi"
        assert first["footer"]["service_name"] == "daily_activity_report"
        assert second["footer"]["service_name"] == "inactivity_moderation"
        assert second["footer"]["contributors"] == ["gpt-4o-mini"]

    asyncio.run(_run())


def test_daily_report_navigation_rehydrates_footer_meta_before_edit() -> None:
    async def _run() -> None:
        service, database, footer_service = _build_service()
        await footer_service.set_version("9.9")
        await footer_service.set_global_phrase("Pipeline footer centralizzata")
        await footer_service.set_service_phrase("inactivity_moderation", "Moderazione inattivi")

        activity_embed = discord.Embed(title="Pagina attività", description="Contenuto attività")
        inactive_embed = discord.Embed(title="Pagina inattivi", description="Contenuto inattivi")
        attach_footer_meta(activity_embed, service_name="daily_activity_report", used_local_processing=True)
        attach_footer_meta(inactive_embed, service_name="inactivity_moderation", contributors=["gpt-4o-mini"], used_local_processing=False)

        await service.persist_pagination_record(
            message_id="100",
            channel_id="7",
            guild_id="9",
            embeds=[activity_embed, inactive_embed],
            metadata={"has_activity": True, "has_inactive": True},
            current_index=0,
        )

        captured: dict[str, object] = {}

        class _Response:
            async def edit_message(self, *, embed: discord.Embed, view: object) -> None:
                captured["embed"] = embed
                captured["view"] = view

        interaction = SimpleNamespace(
            message=SimpleNamespace(id=100),
            response=_Response(),
        )

        view = DailyReportPaginationView(service, current_index=0, total_pages=2)
        await view._navigate(interaction, action="next")

        edited_embed = captured["embed"]
        assert isinstance(edited_embed, discord.Embed)
        assert edited_embed.title == "Pagina inattivi"
        assert edited_embed.description == "Contenuto inattivi"
        assert database.pagination_state["100"]["current_index"] == 1

        assert get_footer_meta(edited_embed) is None
        assert edited_embed.footer.text == (
            "Barcellometro 9.9 · Moderazione inattivi · Dati elaborati con gpt-4o-mini"
        )

    asyncio.run(_run())




def test_daily_report_navigation_removes_persisted_footer_when_service_disabled() -> None:
    async def _run() -> None:
        service, database, footer_service = _build_service()
        await footer_service.set_enabled(False)

        embed = discord.Embed(title="Pagina inattivi", description="Contenuto inattivi")
        embed.set_footer(text="Footer persistito da sopprimere")

        await service.persist_pagination_record(
            message_id="101",
            channel_id="7",
            guild_id="9",
            embeds=[embed],
            metadata={"has_activity": False, "has_inactive": True},
            current_index=0,
        )

        captured: dict[str, object] = {}

        class _Response:
            async def edit_message(self, *, embed: discord.Embed, view: object) -> None:
                captured["embed"] = embed
                captured["view"] = view

        interaction = SimpleNamespace(
            message=SimpleNamespace(id=101),
            response=_Response(),
        )

        view = DailyReportPaginationView(service, current_index=0, total_pages=1)
        await view._navigate(interaction, action="next")

        edited_embed = captured["embed"]
        assert isinstance(edited_embed, discord.Embed)
        assert edited_embed.footer.text is None

    asyncio.run(_run())

def test_daily_report_source_uses_footer_hydration_helper_without_manual_footer_bypass() -> None:
    report_source = Path("app/services/daily_activity_report.py").read_text(encoding="utf-8")

    assert "hydrate_persisted_embed_with_footer(" in report_source
    assert "extract_persistable_footer_context(" in report_source
    assert ".set_footer(" not in report_source


def test_daily_report_view_buttons_order_timeout_and_custom_ids_are_present() -> None:
    report_source = Path("app/services/daily_activity_report.py").read_text(encoding="utf-8")

    start_idx = report_source.index('label="⏮️ INIZIO"')
    prev_idx = report_source.index('label="⬅️ INDIETRO"')
    next_idx = report_source.index('label="➡️ AVANTI"')

    assert start_idx < prev_idx < next_idx
    assert "super().__init__(timeout=None)" in report_source
    assert 'custom_id="daily_report:nav:start"' in report_source
    assert 'custom_id="daily_report:nav:prev"' in report_source
    assert 'custom_id="daily_report:nav:next"' in report_source


def test_daily_report_view_button_states_sync_logic_is_present() -> None:
    report_source = Path("app/services/daily_activity_report.py").read_text(encoding="utf-8")

    assert "def _sync_button_states(self) -> None:" in report_source
    assert "is_first = self._current_index <= 0" in report_source
    assert "is_last = self._current_index >= self._total_pages - 1" in report_source
    assert "self.start_button.disabled = is_first" in report_source
    assert "self.prev_button.disabled = is_first" in report_source
    assert "self.next_button.disabled = is_last" in report_source


def test_daily_report_view_sync_is_called_at_init_and_after_navigation() -> None:
    report_source = Path("app/services/daily_activity_report.py").read_text(encoding="utf-8")

    assert "self._sync_button_states()" in report_source
    assert "self._current_index = target_index" in report_source
    assert "self._total_pages = len(embeds_payload)" in report_source


def test_daily_report_uses_single_file_send_and_never_two_txt_attachments() -> None:
    report_source = Path("app/services/daily_activity_report.py").read_text(encoding="utf-8")

    assert "build_combined_activity_inactive_txt(" in report_source
    assert "channel.send(embed=report_embeds[0], view=view, file=txt_file)" in report_source
    assert "files=[txt_file, inactive_txt_file]" not in report_source


def test_daily_report_pagination_persistence_db_methods_are_present() -> None:
    database_source = Path("app/services/database.py").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS daily_report_pagination_state" in database_source
    assert "async def upsert_daily_report_pagination_state(" in database_source
    assert "async def get_daily_report_pagination_state(" in database_source
    assert "async def update_daily_report_pagination_current_index(" in database_source


def test_inactive_embed_builder_and_single_send_flow_are_present() -> None:
    inactive_source = Path("app/services/inactive_members_moderation.py").read_text(encoding="utf-8")
    report_source = Path("app/services/daily_activity_report.py").read_text(encoding="utf-8")

    assert "async def build_serverwide_inactive_embeds(" in inactive_source
    assert "-> tuple[list[discord.Embed], discord.File | None, InactivityActionsView | None]" in inactive_source
    assert "build_auto_inactive_completed_embed" in inactive_source
    assert "for extra_embed in embeds[1:]" in inactive_source

    assert "DailyReportPaginationView" in report_source
    assert "build_serverwide_inactive_embeds(" in report_source
    assert "channel.send(embed=report_embeds[0], view=view" in report_source
    assert "for idx in range(0, len(embeds), 10)" not in report_source


def test_daily_report_navigation_reapplies_canonical_serversummary_author_pagination() -> None:
    async def _run() -> None:
        service, _, _ = _build_service()
        embed_one = discord.Embed(title="Pagina attività", description="Contenuto attività")
        embed_two = discord.Embed(title="Pagina inattivi", description="Contenuto inattivi")
        attach_footer_meta(embed_one, service_name="daily_activity_report", used_local_processing=True)
        attach_footer_meta(embed_two, service_name="inactivity_moderation", used_local_processing=True)

        await service.persist_pagination_record(
            message_id="102",
            channel_id="7",
            guild_id="9",
            embeds=[embed_one, embed_two],
            metadata={"has_activity": True, "has_inactive": True},
            current_index=0,
        )

        captured: dict[str, object] = {}

        class _Response:
            async def edit_message(self, *, embed: discord.Embed, view: object) -> None:
                captured["embed"] = embed
                captured["view"] = view

        interaction = SimpleNamespace(
            message=SimpleNamespace(id=102),
            response=_Response(),
        )

        view = DailyReportPaginationView(service, current_index=0, total_pages=2)
        await view._navigate(interaction, action="next")

        edited_embed = captured["embed"]
        assert isinstance(edited_embed, discord.Embed)
        assert edited_embed.author.name == "servizio SERVER SUMMARY · (Pag. 2/2)"

    asyncio.run(_run())


def test_daily_report_source_finalizes_canonical_serversummary_author_before_send() -> None:
    report_source = Path("app/services/daily_activity_report.py").read_text(encoding="utf-8")

    attach_idx = report_source.index("attach_author_meta_to_all(")
    finalize_idx = report_source.index('await finalize_embeds_author(report_embeds, None, default_service_name="daily_resoconto")')
    send_idx = report_source.index("channel.send(embed=report_embeds[0], view=view")

    assert "canonical_top_level_command=\"serversummary\"" in report_source
    assert attach_idx < finalize_idx < send_idx


def test_inactive_serverwide_embed_title_has_no_page_suffix() -> None:
    inactive_source = Path("app/services/inactive_members_moderation.py").read_text(encoding="utf-8")

    assert 'build_server_summary_title("INATTIVI")' in inactive_source
    assert "INATTIVI (SERVER-WIDE) — PAG." not in inactive_source
    assert format_standard_title("RESOCONTO SERVER · INATTIVI", emoji="🗣️") == "🗣️ __**RESOCONTO SERVER · INATTIVI**__"
