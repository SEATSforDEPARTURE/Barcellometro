import asyncio
from datetime import datetime
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_no_recursive_call_in_channel_summary_window_helper() -> None:
    source = Path("app/plugins/commands_modular/resoconto.py").read_text()
    marker = "async def _run_channel_summary_window"
    start = source.find(marker)
    assert start >= 0
    end = source.find("@canale_group.command", start)
    helper_body = source[start:end]
    assert "await _run_channel_summary_window(" not in helper_body


def test_manual_window_helper_does_not_auto_enable_channel_summary() -> None:
    source = Path("app/plugins/commands_modular/resoconto.py").read_text()
    marker = "async def _run_channel_summary_window"
    start = source.find(marker)
    assert start >= 0
    end = source.find("@canale_group.command", start)
    helper_body = source[start:end]
    assert "set_channel_summary_auto_enabled" in helper_body
    assert "if publish_at_dt:" in helper_body
    schedule_pos = helper_body.find("if publish_at_dt:")
    auto_enable_pos = helper_body.find("set_channel_summary_auto_enabled")
    assert auto_enable_pos > schedule_pos


def test_resoconto_oggi_e_ieri_route_to_window_helper() -> None:
    source = Path("app/plugins/commands_modular/resoconto.py").read_text()
    assert "async def canale_oggi" in source
    assert 'schedule_type="oggi"' in source
    assert "async def canale_ieri" in source
    assert 'schedule_type="ieri"' in source


def test_edit_allows_clearing_recurrence_with_off_or_none() -> None:
    source = Path("app/plugins/commands_modular/resoconto.py").read_text()
    assert 'normalized_every in {"off", "none"}' in source


def test_schedule_scoped_queries_stay_guild_channel_bound() -> None:
    source = Path("app/services/database.py").read_text()
    assert "WHERE guild_id = ? AND channel_id = ?" in source


def test_window_header_is_always_bold_across_period_types() -> None:
    source = Path("app/renderers/channel_summary_renderer.py").read_text()
    assert "**🗓️ Oggi." in source
    assert "**🗓️ Ieri." in source
    assert "**🗓️ {prefix}" in source
    assert "**🗓️ {start_dt.strftime('%d/%m/%Y %H:%M')} → {end_dt.strftime('%d/%m/%Y %H:%M')}**" in source


def test_renderer_supports_per_moment_barcello_map() -> None:
    source = Path("app/renderers/channel_summary_renderer.py").read_text()
    assert "moment_barcello: dict[int, BarcelloResult] | None = None" in source
    assert "(moment_barcello or {}).get(id(it), barcello_status)" in source


def test_channel_summary_trend_uses_previous_equivalent_window() -> None:
    source = Path("app/services/channel_summary.py").read_text()
    assert "duration = max(timedelta(minutes=1), current_end_local - current_start_local)" in source
    assert "previous_start_local = current_start_local - duration" in source
    assert "previous_end_local = current_start_local" in source
    assert "confronto con finestra equivalente precedente" in source


def test_multi_day_moment_cleanup_removes_time_of_day_hooks() -> None:
    source = Path("app/services/channel_summary.py").read_text()
    assert "if multi_day:" in source
    assert "di prima mattina" in source
    assert "verso mezzogiorno" in source
    assert "in serata" in source


def test_update_schedule_can_clear_recurrence_and_keep_publish_at() -> None:
    pytest.importorskip("aiosqlite")
    from app.services.database import DatabaseService

    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        try:
            await db.initialize_schema()
            schedule_id = await db.create_channel_summary_schedule(
                guild_id="1",
                channel_id="2",
                schedule_type="oggi",
                start_ts="2026-01-01T00:00:00+00:00",
                end_ts="2026-01-01T23:59:59+00:00",
                publish_at="2026-01-02T10:00:00+00:00",
                repeat_every_value=24,
                repeat_every_unit="hours",
                created_by="99",
            )
            ok = await db.update_channel_summary_schedule(
                schedule_id=schedule_id,
                guild_id="1",
                channel_id="2",
                publish_at=None,
                repeat_every_value=None,
                repeat_every_unit=None,
                status="active",
            )
            assert ok is True
            row = await db.get_channel_summary_schedule(schedule_id=schedule_id, guild_id="1", channel_id="2")
            assert row is not None
            assert row["repeat_every_value"] is None
            assert row["repeat_every_unit"] is None
            assert row["publish_at"] == "2026-01-02T10:00:00+00:00"
        finally:
            await db.close()

    asyncio.run(_run())


def test_schedule_channel_scope_for_status_edit_delete_clear() -> None:
    pytest.importorskip("aiosqlite")
    from app.services.database import DatabaseService

    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        try:
            await db.initialize_schema()
            sid = await db.create_channel_summary_schedule(
                guild_id="1",
                channel_id="10",
                schedule_type="oggi",
                start_ts="2026-01-01T00:00:00+00:00",
                end_ts="2026-01-01T23:59:59+00:00",
                publish_at="2026-01-02T10:00:00+00:00",
                repeat_every_value=None,
                repeat_every_unit=None,
                created_by="99",
            )
            s_same = await db.list_channel_summary_schedules("1", "10")
            s_other = await db.list_channel_summary_schedules("1", "11")
            assert len(s_same) == 1
            assert len(s_other) == 0

            assert await db.get_channel_summary_schedule(schedule_id=sid, guild_id="1", channel_id="11") is None
            assert await db.delete_channel_summary_schedule(schedule_id=sid, guild_id="1", channel_id="11") is False
            assert await db.clear_channel_summary_schedules(guild_id="1", channel_id="11") == 0
            assert await db.delete_channel_summary_schedule(schedule_id=sid, guild_id="1", channel_id="10") is True
        finally:
            await db.close()

    asyncio.run(_run())




def test_trend_wording_oggi_ieri_is_natural_without_explicit_range() -> None:
    pytest.importorskip("aiosqlite")
    from app.services.channel_summary import ChannelSummaryService
    from app.services.barcello import BarcelloResult

    svc = ChannelSummaryService(database=None, bot=None, summary_service=None, barcello_service=None)
    current = BarcelloResult(score=72, color="verde", trend="up", reasons=[], metrics={"negativity_hits": 2, "positive_hits": 8})
    previous = BarcelloResult(score=68, color="giallo", trend="down", reasons=[], metrics={"negativity_hits": 4, "positive_hits": 5})

    today = svc._build_trend_vs_previous_equivalent(
        bar_current=current,
        bar_previous=previous,
        current_start_local=datetime(2026, 3, 11, 0, 0),
        current_end_local=datetime(2026, 3, 11, 12, 0),
        period_label="oggi",
    )
    yesterday = svc._build_trend_vs_previous_equivalent(
        bar_current=current,
        bar_previous=previous,
        current_start_local=datetime(2026, 3, 10, 0, 0),
        current_end_local=datetime(2026, 3, 10, 23, 59),
        period_label="ieri",
    )

    assert "→" not in today
    assert "→" not in yesterday
    assert "rispetto a ieri" in today
    assert "rispetto al giorno precedente" in yesterday


def test_trend_wording_ultimi_keeps_explicit_previous_window() -> None:
    pytest.importorskip("aiosqlite")
    from app.services.channel_summary import ChannelSummaryService
    from app.services.barcello import BarcelloResult

    svc = ChannelSummaryService(database=None, bot=None, summary_service=None, barcello_service=None)
    current = BarcelloResult(score=45, color="giallo", trend="flat", reasons=[], metrics={"negativity_hits": 5, "positive_hits": 3})
    previous = BarcelloResult(score=50, color="verde", trend="up", reasons=[], metrics={"negativity_hits": 2, "positive_hits": 3})

    trend = svc._build_trend_vs_previous_equivalent(
        bar_current=current,
        bar_previous=previous,
        current_start_local=datetime(2026, 3, 11, 0, 0),
        current_end_local=datetime(2026, 3, 11, 6, 0),
        period_label="ultimi",
    )

    assert "→" in trend
    assert "rispetto a" in trend


def test_moment_line_renders_bold_barcello_score() -> None:
    pytest.importorskip("aiosqlite")
    from app.renderers.channel_summary_renderer import _moment_line
    from app.services.barcello import BarcelloResult
    from app.services.summary import SummaryItem

    line = _moment_line(
        moment=SummaryItem(ts="2026-03-11T08:45:00+00:00", text="Evento importante", message_ids=[]),
        guild_id=1,
        channel_id=2,
        message_index={},
        primary_id=None,
        barcello_status=BarcelloResult(score=70, color="verde", trend="up", reasons=[], metrics={}),
        multi_day=False,
    )

    assert "**70**" in line


def test_full_multiword_names_are_fully_bolded() -> None:
    pytest.importorskip("aiosqlite")
    from app.renderers.channel_summary_renderer import _bold_known_names

    text = "La Dany Sun 🌞 ha sbloccato la discussione con CRICETO MANNARO."
    out = _bold_known_names(text, ["La Dany Sun 🌞", "CRICETO MANNARO"])

    assert "**La Dany Sun 🌞**" in out
    assert "**CRICETO MANNARO**" in out


def test_who_interacted_prefers_full_known_display_name() -> None:
    pytest.importorskip("aiosqlite")
    from app.renderers.channel_summary_renderer import _bold_leading_actor

    line = "La Dany Sun 🌞 ha tenuto viva la chat con tono positivo."
    out = _bold_leading_actor(line, ["La Dany Sun 🌞"])

    assert out.startswith("**La Dany Sun 🌞** ha")


def test_summary_ai_prompt_switches_for_multi_day_windows() -> None:
    source = Path("app/services/summary.py").read_text()
    assert "multi_day_window = st.astimezone(ROME_TZ).date() != en.astimezone(ROME_TZ).date()" in source
    assert "MOMENTI SALIENTI (intervallo multi-giorno): usa descrizioni neutrali degli eventi" in source


def test_single_day_vs_multi_day_moment_cleanup_behavior() -> None:
    pytest.importorskip("aiosqlite")
    from app.services.channel_summary import ChannelSummaryService

    svc = ChannelSummaryService(database=None, bot=None, summary_service=None, barcello_service=None)
    single = svc._sanitize_moment_text("Di prima mattina, il confronto parte costruttivo.", multi_day=False)
    multi = svc._sanitize_moment_text("Di prima mattina, il confronto parte costruttivo.", multi_day=True)

    assert single.lower().startswith("di prima mattina")
    assert not multi.lower().startswith("di prima mattina")


def test_single_day_neutral_moment_gets_narrative_hook_by_timestamp_bucket() -> None:
    pytest.importorskip("aiosqlite")
    from app.services.channel_summary import ChannelSummaryService

    svc = ChannelSummaryService(database=None, bot=None, summary_service=None, barcello_service=None)
    normalized = svc._sanitize_moment_text(
        "si apre un confronto costruttivo sul planning",
        multi_day=False,
        moment_ts="2026-03-11T09:15:00+00:00",
        ordinal=0,
    )

    assert normalized.lower().startswith(("di prima mattina", "all'avvio della giornata", "la mattina"))


def test_single_day_last_moment_prefers_closure_hook() -> None:
    pytest.importorskip("aiosqlite")
    from app.services.channel_summary import ChannelSummaryService

    svc = ChannelSummaryService(database=None, bot=None, summary_service=None, barcello_service=None)
    normalized = svc._sanitize_moment_text(
        "la discussione si ricompone con un riepilogo condiviso",
        multi_day=False,
        moment_ts="2026-03-11T20:45:00+00:00",
        is_last=True,
        ordinal=4,
    )

    assert normalized.lower().startswith("in chiusura")


def test_multi_day_neutral_moment_does_not_gain_time_of_day_hook() -> None:
    pytest.importorskip("aiosqlite")
    from app.services.channel_summary import ChannelSummaryService

    svc = ChannelSummaryService(database=None, bot=None, summary_service=None, barcello_service=None)
    normalized = svc._sanitize_moment_text(
        "si consolida un filone su priorità e prossimi passi",
        multi_day=True,
        moment_ts="2026-03-11T16:00:00+00:00",
        ordinal=2,
    )

    assert not normalized.lower().startswith((
        "di prima mattina",
        "all'avvio della giornata",
        "la mattina",
        "durante la tarda mattinata",
        "verso mezzogiorno",
        "in piena giornata",
        "nel pomeriggio",
        "più tardi",
        "in serata",
        "sul finire della giornata",
        "in chiusura",
    ))


def test_single_day_narrative_hooks_can_vary_across_moments() -> None:
    pytest.importorskip("aiosqlite")
    from app.services.channel_summary import ChannelSummaryService

    svc = ChannelSummaryService(database=None, bot=None, summary_service=None, barcello_service=None)
    first = svc._sanitize_moment_text(
        "si riapre il thread tecnico",
        multi_day=False,
        moment_ts="2026-03-11T12:10:00+00:00",
        ordinal=0,
    )
    second = svc._sanitize_moment_text(
        "emerge una proposta di sintesi",
        multi_day=False,
        moment_ts="2026-03-11T12:45:00+00:00",
        ordinal=1,
    )

    assert first.split(",", 1)[0].lower() != second.split(",", 1)[0].lower()


def test_semantic_day_style_treats_ieri_as_single_day_even_if_dates_differ() -> None:
    pytest.importorskip("aiosqlite")
    from app.services.channel_summary import ChannelSummaryService

    svc = ChannelSummaryService(database=None, bot=None, summary_service=None, barcello_service=None)

    assert svc._is_single_day_style(
        period_label="ieri",
        start_local=datetime(2026, 3, 11, 0, 0),
        end_local=datetime(2026, 3, 12, 0, 0),
    ) is True


def test_timestamp_formatting_is_hhmm_for_single_day_style_and_ddmm_hhmm_for_multi_day() -> None:
    pytest.importorskip("aiosqlite")
    from app.renderers.channel_summary_renderer import format_time_link

    ts = "2026-03-11T08:45:00+00:00"

    single = format_time_link(1, 2, None, ts, multi_day=False)
    multi = format_time_link(1, 2, None, ts, multi_day=True)

    assert single == "**09:45**"
    assert multi == "**11/03 09:45**"


def test_channel_summary_name_bolding_handles_full_name_with_emoji_and_punctuation() -> None:
    pytest.importorskip("aiosqlite")
    from app.services.channel_summary import ChannelSummaryService

    svc = ChannelSummaryService(database=None, bot=None, summary_service=None, barcello_service=None)

    out = svc._bold_display_name("In serata, La Dany Sun 🌞: rilancia il confronto.", "La Dany Sun 🌞")

    assert "**La Dany Sun 🌞**" in out
    assert "La Dany" not in out.replace("**La Dany Sun 🌞**", "")


def test_channel_summary_name_bolding_does_not_double_bold() -> None:
    pytest.importorskip("aiosqlite")
    from app.services.channel_summary import ChannelSummaryService

    svc = ChannelSummaryService(database=None, bot=None, summary_service=None, barcello_service=None)

    out = svc._bold_display_name("In serata, **Wiwi** aggiorna tutti.", "Wiwi")

    assert out.count("**Wiwi**") == 1


def test_single_day_sanitizer_removes_stacked_temporal_opening() -> None:
    pytest.importorskip("aiosqlite")
    from app.services.channel_summary import ChannelSummaryService

    svc = ChannelSummaryService(database=None, bot=None, summary_service=None, barcello_service=None)

    normalized = svc._sanitize_moment_text(
        "All'avvio della giornata, Durante la discussione, si allinea il piano",
        multi_day=False,
        moment_ts="2026-03-11T08:15:00+00:00",
        ordinal=0,
    )

    assert normalized.lower().startswith("all'avvio della giornata")
    assert "durante la discussione" not in normalized.lower()


def test_insufficient_data_skips_ai_and_renders_minimal_embed() -> None:
    pytest.importorskip("aiosqlite")
    from app.plugins.commands_modular.time_windows import TimeWindowResult
    from app.services.channel_summary import ChannelSummaryService

    class FakeChannel:
        name = "generale"

        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        async def send(self, **kwargs):  # type: ignore[no-untyped-def]
            self.sent.append(kwargs)

    class FakeBot:
        guilds: list[object] = []

        def __init__(self, channel: FakeChannel) -> None:
            self._channel = channel

        def get_channel(self, _id: int) -> FakeChannel:
            return self._channel

    class FakeDatabase:
        async def fetch_messages_in_range(self, **_kwargs):  # type: ignore[no-untyped-def]
            return [
                {"ts": "2026-03-11T09:00:00+00:00", "author_id": "10", "content": "ciao", "message_id": "m1"},
                {"ts": "2026-03-11T09:01:00+00:00", "author_id": "10", "content": "ok", "message_id": "m2"},
            ]

        async def fetch_user_display_name(self, **_kwargs):  # type: ignore[no-untyped-def]
            return "Utente"

        async def mark_daily_report_sent(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return None

    class FakeSummary:
        async def get_config(self):  # type: ignore[no-untyped-def]
            raise AssertionError("get_config should not be called with insufficient data")

        async def build_summary(self, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("AI/local summary path should not run with insufficient data")

    class FakeBarcello:
        async def compute_channel_range(self, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("barcello should be skipped with insufficient data")

    async def _run() -> None:
        channel = FakeChannel()
        svc = ChannelSummaryService(
            database=FakeDatabase(),
            bot=FakeBot(channel),
            summary_service=FakeSummary(),
            barcello_service=FakeBarcello(),
            ai_service=None,
        )
        window = TimeWindowResult(
            start_dt=datetime(2026, 3, 11, 0, 0),
            end_dt=datetime(2026, 3, 11, 23, 59),
            period_label="ieri",
            label_periodo="ieri",
        )
        ok = await svc.generate_and_send_for_channel("1", "2", manual=False, window=window)
        assert ok is True
        assert len(channel.sent) == 1
        payload = channel.sent[0]
        assert "embed" in payload
        embed = payload["embed"]
        assert embed is not None
        assert "Dati non sufficienti alla generazione del resoconto." in (embed.description or "")
        assert embed.footer.text == "Servizio offerto dal vostro Barcellometro di fiducia"

    asyncio.run(_run())


def test_insufficient_data_embed_has_no_detailed_sections() -> None:
    pytest.importorskip("aiosqlite")
    from app.renderers.channel_summary_renderer import build_channel_summary_insufficient_data_embed

    embed = build_channel_summary_insufficient_data_embed(
        channel_name="generale",
        window_header="**🗓️ Ieri. Mercoledì, 11 Marzo 2026**",
    )

    assert embed.title == "📓 RESOCONTO CANALE — #generale"
    assert "Dati non sufficienti" in (embed.description or "")
    assert len(embed.fields) == 0


def test_sufficient_data_keeps_normal_channel_summary_flow() -> None:
    pytest.importorskip("aiosqlite")
    from app.plugins.commands_modular.time_windows import TimeWindowResult
    from app.services.barcello import BarcelloResult
    from app.services.channel_summary import ChannelSummaryService
    from app.services.summary import SummaryItem, SummaryQuote, SummaryResult

    class FakeChannel:
        name = "generale"

        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        async def send(self, **kwargs):  # type: ignore[no-untyped-def]
            self.sent.append(kwargs)

    class FakeBot:
        guilds: list[object] = []

        def __init__(self, channel: FakeChannel) -> None:
            self._channel = channel

        def get_channel(self, _id: int) -> FakeChannel:
            return self._channel

    class FakeDatabase:
        def __init__(self) -> None:
            self._rows = [
                {"ts": f"2026-03-11T09:{i:02d}:00+00:00", "author_id": str((i % 3) + 1), "content": f"msg {i}", "message_id": f"m{i}", "reply_to_message_id": None, "mentions_json": "[]"}
                for i in range(10)
            ]

        async def fetch_messages_in_range(self, **_kwargs):  # type: ignore[no-untyped-def]
            return self._rows

        async def fetch_user_display_name(self, **kwargs):  # type: ignore[no-untyped-def]
            return f"U{kwargs.get('user_id')}"

        async def fetch_message_by_id(self, **kwargs):  # type: ignore[no-untyped-def]
            mid = kwargs.get("message_id")
            for row in self._rows:
                if row["message_id"] == mid:
                    return row
            return None

        async def resolve_message_ids_for_timestamp(self, **_kwargs):  # type: ignore[no-untyped-def]
            return []

    class FakeSummary:
        def __init__(self) -> None:
            self.called = False

        async def get_config(self):  # type: ignore[no-untyped-def]
            return {}

        async def build_summary(self, **_kwargs):  # type: ignore[no-untyped-def]
            self.called = True
            return SummaryResult(
                themes=["progetti"],
                moments=[SummaryItem(ts="2026-03-11T09:01:00+00:00", text="Si allineano le priorità", author_id="1", message_ids=["m1"])],
                quotes=[SummaryQuote(ts="2026-03-11T09:02:00+00:00", text="\"Restiamo focalizzati\"", author_id="2", message_ids=["m2"])],
                dynamics=[SummaryItem(ts="2026-03-11T09:03:00+00:00", text="Confronto collaborativo", author_id="3", message_ids=["m3"])],
                degrade=[],
                invigorate=[],
                advice=["Proseguire con check-in brevi"],
                metrics={},
                ai_status={"enabled": False, "reason": "disabled"},
                vibe_line="Il clima è stato costruttivo.",
                proverbio="Chi va piano va sano e va lontano.",
                who_interacted_today=["U1 ha facilitato il confronto."],
            )

    class FakeBarcello:
        async def compute_channel_range(self, **_kwargs):  # type: ignore[no-untyped-def]
            return BarcelloResult(score=72, color="verde", trend="up", reasons=[], metrics={"negativity_hits": 1, "positive_hits": 5})

    async def _run() -> None:
        channel = FakeChannel()
        summary = FakeSummary()
        svc = ChannelSummaryService(
            database=FakeDatabase(),
            bot=FakeBot(channel),
            summary_service=summary,
            barcello_service=FakeBarcello(),
            ai_service=None,
        )
        window = TimeWindowResult(
            start_dt=datetime(2026, 3, 11, 0, 0),
            end_dt=datetime(2026, 3, 11, 23, 59),
            period_label="oggi",
            label_periodo="oggi",
        )
        ok = await svc.generate_and_send_for_channel("1", "2", manual=False, window=window)
        assert ok is True
        assert summary.called is True
        assert len(channel.sent) == 1
        payload = channel.sent[0]
        assert "embeds" in payload
        embeds = payload["embeds"]
        assert isinstance(embeds, list)
        assert len(embeds) >= 2

    asyncio.run(_run())


def test_channel_summary_renderer_supports_aura_page_append() -> None:
    source = Path("app/renderers/channel_summary_renderer.py").read_text()
    assert "aura_embed: discord.Embed | None = None" in source
    assert "aura_embed.title = f\"🗒️ DETTAGLI (Pag {total}/{total})\"" in source


def test_channel_summary_overrides_third_embed_title_to_aura_details() -> None:
    source = Path("app/services/channel_summary.py").read_text()
    assert 'embeds[2].title = "🗒️ DETTAGLI PUNTI AURA (Pag 2/2)"' in source


def test_channel_summary_builds_channel_scoped_aura_with_previous_window() -> None:
    source = Path("app/services/channel_summary.py").read_text()
    assert "fetch_aura_channel_ledger_report(guild_id, channel_id" in source
    assert "fetch_aura_channel_top_users(guild_id, channel_id" in source
    assert "fetch_aura_channel_mission_stats(guild_id, channel_id" in source
    assert "prev_start_local, prev_end_local = self._previous_equivalent_window" in source


def test_database_has_channel_scoped_aura_queries() -> None:
    source = Path("app/services/database.py").read_text()
    assert "async def fetch_aura_channel_ledger_report" in source
    assert "WHERE guild_id = ? AND channel_id = ? AND ts >= ? AND ts <= ?" in source
    assert "async def fetch_aura_channel_top_users" in source
