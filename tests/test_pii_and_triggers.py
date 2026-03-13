from datetime import datetime, timedelta
import json
import sys
import types
from types import SimpleNamespace
import asyncio
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

if "discord" not in sys.modules:
    discord_stub = types.ModuleType("discord")
    discord_stub.Interaction = object
    discord_stub.Message = object
    discord_stub.Guild = object
    discord_stub.Member = object
    discord_stub.Client = object
    sys.modules["discord"] = discord_stub

discord_stub = sys.modules["discord"]

if not hasattr(discord_stub, "Color"):
    class _FakeColor:
        @staticmethod
        def from_str(value: str):
            return value

        @staticmethod
        def green():
            return 1

        @staticmethod
        def gold():
            return 2

        @staticmethod
        def red():
            return 3

        @staticmethod
        def dark_grey():
            return 4

        @staticmethod
        def blurple():
            return 5

    discord_stub.Color = _FakeColor

if not hasattr(discord_stub, "Embed"):
    class _FakeEmbed:
        def __init__(self, description: str = "", timestamp=None, **kwargs) -> None:
            self.description = description
            self.timestamp = timestamp
            self.title = kwargs.get("title")
            self.color = kwargs.get("color")
            self.fields: list[dict[str, object]] = []

        def set_footer(self, text: str) -> None:
            self.footer = text

        def add_field(self, *, name: str, value: str, inline: bool = False) -> None:
            self.fields.append({"name": name, "value": value, "inline": inline})

    discord_stub.Embed = _FakeEmbed

if "aiosqlite" not in sys.modules:
    aiosqlite_stub = types.ModuleType("aiosqlite")
    aiosqlite_stub.Connection = object
    aiosqlite_stub.connect = object
    sys.modules["aiosqlite"] = aiosqlite_stub

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.AsyncOpenAI = object
    sys.modules["openai"] = openai_stub

from app.services.triggers import TriggerEngineService, is_out_of_scope_question, is_sensitive_question
from app.utils.pii import contains_pii, redact_pii


def test_redact_pii_email_phone() -> None:
    text, had = redact_pii("Scrivimi a mario@example.com o al +39 333 1234567")
    assert had is True
    assert "[REDACTED_EMAIL]" in text
    assert "[REDACTED_PHONE]" in text


def test_contains_pii() -> None:
    assert contains_pii("IT60X0542811101000000123456")


def test_discord_mentions_are_not_pii() -> None:
    assert contains_pii("ciao <@123456789012345678>") is False
    assert contains_pii("<#123456789012345678>") is False


def test_valid_credit_card_detected_and_redacted() -> None:
    card = "4111 1111 1111 1111"
    assert contains_pii(f"La carta è {card}") is True
    redacted, had = redact_pii(f"La carta è {card}")
    assert had is True
    assert "[REDACTED_CARD]" in redacted


def test_qna_scope_and_sensitive_heuristics() -> None:
    assert is_out_of_scope_question("cosa dicono nel canale privato?")
    assert is_sensitive_question("qual è il numero di telefono?")


def test_infer_time_range_days_ago_is_single_day_window() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    start_dt, end_dt, label = service.infer_time_range("Cosa ha detto 2 giorni fa?")
    assert label == "2 giorni fa"
    assert end_dt - start_dt == timedelta(days=1)


def test_infer_time_range_altro_ieri_is_single_day_window() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    start_dt, end_dt, label = service.infer_time_range("Cosa ha detto l'altro ieri?")
    assert label == "l'altro ieri"
    assert end_dt - start_dt == timedelta(days=1)


def test_infer_time_range_hours_ago_window() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    start_dt, end_dt, label = service.infer_time_range("Cosa ha detto 3 ore fa?")
    assert label == "3 ore fa"
    assert end_dt - start_dt == timedelta(hours=3)




def test_infer_time_range_ieri_uses_full_previous_local_day() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    start_dt, end_dt, label = service.infer_time_range("Cosa ha detto ieri?")
    assert label == "ieri"

    rome = ZoneInfo("Europe/Rome")
    now_local = datetime.now(rome)
    today_start_local = datetime.combine(now_local.date(), datetime.min.time(), tzinfo=rome)
    expected_start = (today_start_local - timedelta(days=1)).astimezone(start_dt.tzinfo)
    expected_end = today_start_local.astimezone(end_dt.tzinfo)

    assert start_dt == expected_start
    assert end_dt == expected_end

def test_infer_time_range_mese_scorso_boundaries() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    start_dt, end_dt, label = service.infer_time_range("Cosa è successo mese scorso?")
    assert label == "mese scorso"

    rome = ZoneInfo("Europe/Rome")
    now_local = datetime.now(rome)
    current_month_start_local = datetime.combine(now_local.date().replace(day=1), datetime.min.time(), tzinfo=rome)
    prev_month_last_day = current_month_start_local - timedelta(days=1)
    prev_month_start_local = current_month_start_local.replace(year=prev_month_last_day.year, month=prev_month_last_day.month)

    assert start_dt == prev_month_start_local.astimezone(start_dt.tzinfo)
    assert end_dt == current_month_start_local.astimezone(end_dt.tzinfo)


def test_decorate_proof_links_formats_discord_jump_urls() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    answer = "- Punto [prova](https://discord.com/channels/1/2/3)"
    evidence = [
        {
            "jump_url": "https://discord.com/channels/1/2/3",
            "created_at_iso": "2026-02-14T19:00:00+00:00",
        }
    ]

    decorated = service._decorate_proof_links(answer, evidence)
    assert "[🧾 14/02 20:00](https://discord.com/channels/1/2/3)" in decorated


def test_decorate_proof_links_keeps_unknown_links() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    answer = "- Punto [prova](https://discord.com/channels/1/2/999)"
    evidence = [
        {
            "jump_url": "https://discord.com/channels/1/2/3",
            "created_at_iso": "2026-02-14T19:00:00+00:00",
        }
    ]

    decorated = service._decorate_proof_links(answer, evidence)
    assert decorated == answer


def test_decorate_proof_links_fixes_spaced_markdown_parentheses() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    answer = "Fonte: [🧾 14/02 14:26] (https://discord.com/channels/1/2/3)"
    evidence = [{"jump_url": "https://discord.com/channels/1/2/3", "created_at_iso": "2026-02-14T13:26:00+00:00", "content": "confermato", "author_name": "Luca", "author_id": "1"}]

    decorated = service._decorate_proof_links(answer, evidence)
    assert "[🧾 14/02 14:26](https://discord.com/channels/1/2/3)" in decorated


def test_decorate_proof_links_rewrites_naked_proof_url() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    answer = "prova (https://discord.com/channels/1/2/3)"
    evidence = [{"jump_url": "https://discord.com/channels/1/2/3", "created_at_iso": "2026-02-14T13:26:00+00:00", "content": "confermato", "author_name": "Luca", "author_id": "1"}]

    decorated = service._decorate_proof_links(answer, evidence)
    assert decorated == "[🧾 14/02 14:26](https://discord.com/channels/1/2/3)"


def test_decorate_proof_links_removes_broken_spacing_patterns() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    answer = "Test [🧾 14/02 14:26] ( https://discord.com/channels/1/2/3 )"
    evidence = [{"jump_url": "https://discord.com/channels/1/2/3", "created_at_iso": "2026-02-14T13:26:00+00:00", "content": "confermato", "author_name": "Luca", "author_id": "1"}]

    decorated = service._decorate_proof_links(answer, evidence)
    assert "] (http" not in decorated
    assert "]\n(http" not in decorated
    assert "[🧾 14/02 14:26](https://discord.com/channels/1/2/3)" in decorated


def test_decorate_proof_links_removes_newlines_and_spaces_inside_link_url() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    answer = "Fonte: [🧾 14/02 14:26](https://discord.com/channels/1/\n2/3 )"
    evidence = [{"jump_url": "https://discord.com/channels/1/2/3", "created_at_iso": "2026-02-14T13:26:00+00:00", "content": "confermato", "author_name": "Luca", "author_id": "1"}]

    decorated = service._decorate_proof_links(answer, evidence)
    assert "\n" not in decorated.split("(", 1)[1].split(")", 1)[0]
    assert "[🧾 14/02 14:26](https://discord.com/channels/1/2/3)" in decorated


def test_extract_target_speaker_raw() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    assert service._extract_target_speaker("è vero che Dany Sun ☀️ ha detto che potevo sfogarmi?") == "Dany Sun"


def test_bulletize_answer_filters_evidence_by_target_author() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    answer = "• Ha detto che potevi sfogarti quando eri giù."
    evidence = [
        {
            "message_id": "1",
            "channel_id": "2",
            "author_id": "10",
            "author_name": "Daniele",
            "created_at_iso": "2026-02-14T13:00:00+00:00",
            "content": "non c'entra niente",
            "jump_url": "https://discord.com/channels/1/2/3",
        },
        {
            "message_id": "2",
            "channel_id": "2",
            "author_id": "11",
            "author_name": "Daniela 🌸",
            "created_at_iso": "2026-02-14T14:00:00+00:00",
            "content": "ti ho detto che potevi sfogarti quando eri giù",
            "jump_url": "https://discord.com/channels/1/2/4",
        },
    ]

    out = service._bulletize_answer("è vero che Daniela ha detto che potevo sfogarmi?", answer, evidence)
    assert "https://discord.com/channels/1/2/4" in out
    assert "https://discord.com/channels/1/2/3" not in out


def test_bulletize_answer_returns_no_direct_evidence_when_target_missing() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    answer = "• Ha detto che potevi sfogarti."
    evidence = [
        {
            "message_id": "1",
            "channel_id": "2",
            "author_id": "10",
            "author_name": "Marco",
            "created_at_iso": "2026-02-14T13:00:00+00:00",
            "content": "messaggio non correlato a questa domanda",
            "jump_url": "https://discord.com/channels/1/2/3",
        }
    ]

    out = service._bulletize_answer("cosa ha detto Daniela?", answer, evidence)
    assert out == "Non risultano messaggi o attività rilevanti per questa richiesta nel periodo indicato."


def test_filter_evidence_by_target_matches_decorated_name() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    evidence = [
        {
            "author_name": "Dany Sun ☀️",
            "author_id": "11",
            "jump_url": "https://discord.com/channels/1/2/4",
            "created_at_iso": "2026-02-14T14:00:00+00:00",
            "content": "ti ho detto che potevi sfogarti quando eri giù",
        }
    ]

    filtered = service._filter_evidence_by_target(evidence, "Dany")
    assert len(filtered) == 1


def test_bulletize_answer_no_target_evidence_has_no_links() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    answer = "• Dicevano della live senza censura alle 20"
    evidence = [
        {
            "message_id": "1",
            "channel_id": "2",
            "author_id": "10",
            "author_name": "Marco",
            "created_at_iso": "2026-02-14T13:00:00+00:00",
            "content": "stasera live senza censura alle 20, si può sfogare tutto",
            "jump_url": "https://discord.com/channels/1/2/3",
        }
    ]

    out = service._bulletize_answer("è vero che Daniela ha detto live senza censura alle 20?", answer, evidence)
    assert out == "Non risultano messaggi o attività rilevanti per questa richiesta nel periodo indicato."
    assert "https://discord.com/channels/1/2/3" not in out


def test_select_barcello_template_prefers_mood_and_time_override() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    cfg = {
        "templates": {"VERDE->GIALLO": "base"},
        "moods": {
            "drama": {
                "templates": {"VERDE->GIALLO": "mood"},
                "time": {"night": {"templates": {"VERDE->GIALLO": "night"}}},
            }
        },
    }
    selected = service._select_barcello_template(cfg, "1", "drama", "night", "t1", "VERDE->GIALLO")
    assert selected == "night"


def test_select_barcello_template_prefers_channel_override() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    cfg = {
        "templates": {"VERDE->GIALLO": "base"},
        "moods": {"drama": {"templates": {"VERDE->GIALLO": "global-mood"}}},
        "channels": {
            "42": {
                "moods": {"drama": {"templates": {"VERDE->GIALLO": "channel-mood"}}},
            }
        },
    }
    selected = service._select_barcello_template(cfg, "42", "drama", "night", "t1", "VERDE->GIALLO")
    assert selected == "channel-mood"


def test_resolve_template_value_handles_deterministic_list_choice() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    selected_a = service._resolve_template_value(["a", "b", "c"], seed_parts=("g", "c", "k", "m", "t", "d", "x"))
    selected_b = service._resolve_template_value(["a", "b", "c"], seed_parts=("g", "c", "k", "m", "t", "d", "x"))
    assert selected_a == selected_b
    assert selected_a in {"a", "b", "c"}


def _run_poll_with_config(config: dict[str, object]) -> tuple[AsyncMock, AsyncMock]:
    database = Mock()
    database.list_enabled_trigger_channels = AsyncMock(return_value=[{"guild_id": "1", "channel_id": "2"}])
    database.fetchone = AsyncMock(return_value={"count": 30})
    database.get_barcello_trigger_state = AsyncMock(return_value={"last_color": "VERDE", "last_score": 10})
    database.get_trigger_state = AsyncMock(return_value={})
    database.upsert_barcello_trigger_state = AsyncMock()
    database.set_trigger_state = AsyncMock()

    barcello = Mock()
    barcello.get_current_status = AsyncMock(return_value={"color": "GIALLO", "score": 20})

    service = TriggerEngineService(database, barcello, Mock(), Mock(), community_insights=Mock())

    class FakeMessageable:
        async def send(self, embed=None):
            return None

    class FakeBot:
        def get_channel(self, channel_id: int):
            _ = channel_id
            return FakeMessageable()

    service._bot = FakeBot()

    triggers_discord = sys.modules["app.services.triggers"].discord
    if not hasattr(triggers_discord, "abc"):
        triggers_discord.abc = types.SimpleNamespace(Messageable=FakeMessageable)
    else:
        triggers_discord.abc.Messageable = FakeMessageable
    if not hasattr(triggers_discord, "Embed"):
        class FakeEmbed:
            def __init__(self, title=None, description=None, color=None):
                self.title = title
                self.description = description
                self.color = color

            def set_footer(self, *, text=None):
                self.footer = text
        triggers_discord.Embed = FakeEmbed
    if not hasattr(triggers_discord, "Color"):
        class FakeColor:
            @staticmethod
            def green():
                return 1

            @staticmethod
            def gold():
                return 2

            @staticmethod
            def red():
                return 3

            @staticmethod
            def dark_grey():
                return 4

            @staticmethod
            def blurple():
                return 5
        triggers_discord.Color = FakeColor

    with patch("app.services.triggers.load_json_file", return_value=config):
        asyncio.run(service._poll_barcello())

    return database.upsert_barcello_trigger_state, database.set_trigger_state


def test_poll_barcello_no_crash_with_min_score_delta_in_config() -> None:
    _, set_trigger_state = _run_poll_with_config(
        {
            "window_minutes": 60,
            "min_messages": 1,
            "min_score_delta_for_notify": 2,
            "templates": {"VERDE->GIALLO": "x"},
        }
    )
    assert set_trigger_state.await_count == 1


def test_poll_barcello_no_crash_without_min_score_delta_in_config_and_stored_color_defined() -> None:
    _, set_trigger_state = _run_poll_with_config(
        {
            "window_minutes": 60,
            "min_messages": 1,
            "templates": {"VERDE->GIALLO": "x"},
        }
    )
    daily_payload = set_trigger_state.await_args_list[0].args[3]
    assert daily_payload["counts"].get("GIALLO") == 1


def test_daily_random_mood_sets_state_with_today_date() -> None:
    database = Mock()
    database.get_trigger_state = AsyncMock(return_value={})
    database.set_trigger_state = AsyncMock()
    service = TriggerEngineService(database, Mock(), Mock(), Mock(), community_insights=Mock())

    cfg = {
        "mood_daily_random": True,
        "mood_daily_random_time_local": "06:00",
        "mood_daily_random_avoid_repeat": True,
        "moods": {"a": {}, "b": {}},
    }
    now_rome = datetime(2026, 2, 20, 7, 0, tzinfo=ZoneInfo("Europe/Rome"))

    asyncio.run(service._maybe_set_daily_random_mood("1", "2", cfg, now_rome))

    assert database.set_trigger_state.await_count == 1
    payload = database.set_trigger_state.await_args.args[3]
    assert payload["date"] == "2026-02-20"
    assert payload["mode"] == "daily_random"
    assert payload["mood"] in {"a", "b"}


def test_daily_random_mood_does_not_change_twice_same_day() -> None:
    database = Mock()
    database.get_trigger_state = AsyncMock(return_value={"mood": "a", "date": "2026-02-20", "mode": "daily_random"})
    database.set_trigger_state = AsyncMock()
    service = TriggerEngineService(database, Mock(), Mock(), Mock(), community_insights=Mock())

    cfg = {
        "mood_daily_random": True,
        "mood_daily_random_time_local": "06:00",
        "moods": {"a": {}, "b": {}},
    }
    now_rome = datetime(2026, 2, 20, 8, 0, tzinfo=ZoneInfo("Europe/Rome"))

    asyncio.run(service._maybe_set_daily_random_mood("1", "2", cfg, now_rome))

    assert database.set_trigger_state.await_count == 0


def test_daily_random_mood_avoid_repeat_from_yesterday() -> None:
    database = Mock()
    database.get_trigger_state = AsyncMock(return_value={"mood": "a", "date": "2026-02-19", "mode": "daily_random"})
    database.set_trigger_state = AsyncMock()
    service = TriggerEngineService(database, Mock(), Mock(), Mock(), community_insights=Mock())

    cfg = {
        "mood_daily_random": True,
        "mood_daily_random_time_local": "06:00",
        "mood_daily_random_avoid_repeat": True,
        "moods": {"a": {}, "b": {}},
    }
    now_rome = datetime(2026, 2, 20, 9, 0, tzinfo=ZoneInfo("Europe/Rome"))

    asyncio.run(service._maybe_set_daily_random_mood("1", "2", cfg, now_rome))

    payload = database.set_trigger_state.await_args.args[3]
    assert payload["mood"] == "b"


def test_poll_barcello_uses_channel_window_override() -> None:
    database = Mock()
    database.list_enabled_trigger_channels = AsyncMock(return_value=[{"guild_id": "1", "channel_id": "2"}])
    database.fetchone = AsyncMock(return_value={"count": 30})
    database.get_barcello_trigger_state = AsyncMock(return_value={"last_color": "VERDE", "last_score": 10})
    database.get_trigger_state = AsyncMock(return_value={})
    database.upsert_barcello_trigger_state = AsyncMock()
    database.set_trigger_state = AsyncMock()

    barcello = Mock()
    barcello.get_current_status = AsyncMock(return_value={"color": "GIALLO", "score": 20})

    service = TriggerEngineService(database, barcello, Mock(), Mock(), community_insights=Mock())

    class FakeMessageable:
        async def send(self, embed=None):
            return None

    class FakeBot:
        def get_channel(self, channel_id: int):
            _ = channel_id
            return FakeMessageable()

    service._bot = FakeBot()

    triggers_discord = sys.modules["app.services.triggers"].discord
    if not hasattr(triggers_discord, "abc"):
        triggers_discord.abc = types.SimpleNamespace(Messageable=FakeMessageable)
    else:
        triggers_discord.abc.Messageable = FakeMessageable
    if not hasattr(triggers_discord, "Embed"):
        class FakeEmbed:
            def __init__(self, title=None, description=None, color=None):
                self.title = title
                self.description = description
                self.color = color

            def set_footer(self, *, text=None):
                self.footer = text
        triggers_discord.Embed = FakeEmbed
    if not hasattr(triggers_discord, "Color"):
        class FakeColor:
            @staticmethod
            def green():
                return 1

            @staticmethod
            def gold():
                return 2

            @staticmethod
            def red():
                return 3

            @staticmethod
            def dark_grey():
                return 4

            @staticmethod
            def blurple():
                return 5
        triggers_discord.Color = FakeColor

    config = {
        "window_minutes": 60,
        "min_messages": 1,
        "templates": {"VERDE->GIALLO": "x"},
        "channel_overrides": {"2": {"window_minutes": 25}},
    }
    with patch("app.services.triggers.load_json_file", return_value=config):
        asyncio.run(service._poll_barcello())

    assert barcello.get_current_status.await_args.kwargs["window_minutes"] == 25


def _build_barcello_poll_service_for_logging(database: Mock, barcello: Mock) -> TriggerEngineService:
    service = TriggerEngineService(database, barcello, Mock(), Mock(), community_insights=Mock())

    class FakeMessageable:
        async def send(self, embed=None):
            return None

    class FakeBot:
        def get_channel(self, channel_id: int):
            _ = channel_id
            return FakeMessageable()

    service._bot = FakeBot()

    triggers_discord = sys.modules["app.services.triggers"].discord
    if not hasattr(triggers_discord, "abc"):
        triggers_discord.abc = types.SimpleNamespace(Messageable=FakeMessageable)
    else:
        triggers_discord.abc.Messageable = FakeMessageable
    if not hasattr(triggers_discord, "Embed"):
        class FakeEmbed:
            def __init__(self, title=None, description=None, color=None):
                self.title = title
                self.description = description
                self.color = color

            def set_footer(self, *, text=None):
                self.footer = text
        triggers_discord.Embed = FakeEmbed
    if not hasattr(triggers_discord, "Color"):
        class FakeColor:
            @staticmethod
            def green():
                return 1

            @staticmethod
            def gold():
                return 2

            @staticmethod
            def red():
                return 3

            @staticmethod
            def dark_grey():
                return 4

            @staticmethod
            def blurple():
                return 5

        triggers_discord.Color = FakeColor

    return service


def test_poll_barcello_override_logs_only_changes_between_ticks(tmp_path, caplog) -> None:
    database = Mock()
    database.list_enabled_trigger_channels = AsyncMock(return_value=[
        {"guild_id": "1", "channel_id": "2"},
        {"guild_id": "1", "channel_id": "3"},
    ])
    database.fetchone = AsyncMock(return_value={"count": 30})
    database.get_barcello_trigger_state = AsyncMock(return_value={"last_color": "VERDE", "last_score": 10})
    database.get_trigger_state = AsyncMock(return_value={})
    database.upsert_barcello_trigger_state = AsyncMock()
    database.set_trigger_state = AsyncMock()

    barcello = Mock()
    barcello.get_current_status = AsyncMock(return_value={"color": "GIALLO", "score": 20})
    service = _build_barcello_poll_service_for_logging(database, barcello)

    cfg_path = tmp_path / "barcello_trigger.json"
    cfg_path.write_text(json.dumps({
        "window_minutes": 60,
        "min_messages": 1,
        "templates": {"VERDE->GIALLO": "x"},
        "channel_overrides": {"2": {"window_minutes": 25}, "3": {"window_minutes": 30}},
    }), encoding="utf-8")
    service._barcello_trigger_cfg_path = str(cfg_path)

    with caplog.at_level("INFO", logger="app.services.triggers"):
        asyncio.run(service._poll_barcello())
        first_tick_logs = [r for r in caplog.records if "barcello window override applied" in r.message]
        assert len(first_tick_logs) == 2

        caplog.clear()
        asyncio.run(service._poll_barcello())
        second_tick_logs = [r for r in caplog.records if "barcello window override applied" in r.message]
        assert len(second_tick_logs) == 0


def test_poll_barcello_override_logs_only_channels_with_window_change(tmp_path, caplog) -> None:
    database = Mock()
    database.list_enabled_trigger_channels = AsyncMock(return_value=[
        {"guild_id": "1", "channel_id": "2"},
        {"guild_id": "1", "channel_id": "3"},
    ])
    database.fetchone = AsyncMock(return_value={"count": 30})
    database.get_barcello_trigger_state = AsyncMock(return_value={"last_color": "VERDE", "last_score": 10})
    database.get_trigger_state = AsyncMock(return_value={})
    database.upsert_barcello_trigger_state = AsyncMock()
    database.set_trigger_state = AsyncMock()

    barcello = Mock()
    barcello.get_current_status = AsyncMock(return_value={"color": "GIALLO", "score": 20})
    service = _build_barcello_poll_service_for_logging(database, barcello)

    cfg_path = tmp_path / "barcello_trigger.json"
    cfg1 = {
        "window_minutes": 60,
        "min_messages": 1,
        "templates": {"VERDE->GIALLO": "x"},
        "channel_overrides": {"2": {"window_minutes": 25}, "3": {"window_minutes": 30}},
    }
    cfg_path.write_text(json.dumps(cfg1), encoding="utf-8")
    service._barcello_trigger_cfg_path = str(cfg_path)
    asyncio.run(service._poll_barcello())

    cfg2 = {
        "window_minutes": 60,
        "min_messages": 1,
        "templates": {"VERDE->GIALLO": "x"},
        "channel_overrides": {"2": {"window_minutes": 40}, "3": {"window_minutes": 30}},
    }
    cfg_path.write_text(json.dumps(cfg2), encoding="utf-8")

    with caplog.at_level("INFO", logger="app.services.triggers"):
        asyncio.run(service._poll_barcello())

    logs = [r.message for r in caplog.records if "barcello window override applied" in r.message]
    assert len(logs) == 1
    assert "channel_id=2" in logs[0]
    assert "window=40" in logs[0]


def test_ask_general_llm_uses_assistant_prompt_and_returns_text() -> None:
    ai_client = Mock()
    ai_client.responses.create = AsyncMock(return_value=SimpleNamespace(output_text="Risposta generale"))
    ai_service = Mock()
    ai_service.is_enabled.return_value = True
    ai_service.client.return_value = ai_client
    ai_service.get_model.return_value = "gpt-4o-mini"
    ai_service.ask_general = AsyncMock(return_value="Risposta generale")

    service = TriggerEngineService(Mock(), Mock(), Mock(), ai_service, community_insights=Mock())
    out = asyncio.run(service._ask_general_llm("meteo Cerignola"))

    assert out == "Risposta generale"
    ai_service.ask_general.assert_awaited_once()


def test_handle_qna_question_global_bypasses_retrieval() -> None:
    database = Mock()
    database.get_trigger_enabled = AsyncMock(return_value=True)
    database.get_usage = AsyncMock(return_value=0)
    database.increment_usage = AsyncMock()

    entitlements = Mock()
    entitlements.resolve_profile = AsyncMock(return_value="role1")

    service = TriggerEngineService(database, Mock(), entitlements, Mock(), community_insights=Mock())
    service._get_qna_daily_limits = AsyncMock(return_value={"role1": 3, "role2": 5, "role3": 8})
    service._resolve_qna_limit = AsyncMock(return_value=3)
    service._ask_general_answer = AsyncMock(return_value="Risposta global")
    service._handle_qna = AsyncMock()
    service._build_qna_embed = Mock(return_value=Mock())

    response = Mock()
    response.is_done = Mock(return_value=False)
    response.defer = AsyncMock()
    response.send_message = AsyncMock()

    followup = Mock()
    followup.send = AsyncMock()

    interaction = SimpleNamespace(
        guild_id=10,
        channel_id=20,
        user=SimpleNamespace(id=30, mention="<@30>"),
        response=response,
        followup=followup,
    )

    asyncio.run(service.handle_qna_question(interaction, "Domanda generale", scope_override="global"))

    service._ask_general_answer.assert_awaited_once()
    service._handle_qna.assert_not_called()
    followup.send.assert_awaited_once()


def test_build_qna_embed_layout_contains_question_and_answer() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    embed = service._build_qna_embed(
        "Luca",
        "quanti minuti?",
        "3 ore sono 180 minuti.",
        response_origin="remote_ai",
        model_name="gpt-4o-mini",
    )
    assert embed.title == "❓BOTTA & RISPOSTA"
    assert embed.color == "#9B59B6"
    assert "✋ **Luca chiede:**" in (embed.description or "")
    assert "**👇 Risposta:**" in (embed.description or "")
    assert "180" in (embed.description or "")


def test_build_qna_embed_followup_layout_contains_only_answer() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    embed = service._build_qna_embed(
        "Luca",
        "e poi?",
        "Risposta contestuale",
        response_origin="remote_ai",
        model_name="gpt-4o-mini",
        is_followup=True,
    )

    description = embed.description or ""
    assert description.startswith("**👇 Risposta:**")
    assert "chiede:" not in description
    assert "Luca" not in description.split("\n", 1)[0]

def test_format_qna_answer_text_evidence_mode_adds_proof_links() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    answer = "• Confermato [prova](https://discord.com/channels/1/2/3)"
    evidence = [{"jump_url": "https://discord.com/channels/1/2/3", "created_at_iso": "2026-02-14T13:26:00+00:00", "content": "confermato", "author_name": "Luca", "author_id": "1"}]
    formatted = service._format_qna_answer_text("cosa è stato confermato?", answer, evidence, scope="channel_qna", mode="evidence")
    assert "[🧾" in formatted
    assert "https://discord.com/channels/1/2/3" in formatted


def test_route_qna_general_llm_bypasses_channel_trigger_check() -> None:
    database = Mock()
    database.get_trigger_enabled = AsyncMock(return_value=False)
    database.get_usage = AsyncMock(return_value=0)
    database.increment_usage = AsyncMock()

    entitlements = Mock()
    entitlements.resolve_profile = AsyncMock(return_value="role1")

    service = TriggerEngineService(database, Mock(), entitlements, Mock(), community_insights=Mock())
    service._get_qna_daily_limits = AsyncMock(return_value={"role1": 3, "role2": 5, "role3": 8})
    service._resolve_qna_limit = AsyncMock(return_value=3)
    service._ask_general_answer = AsyncMock(return_value="Risposta utile")
    service._handle_qna = AsyncMock()
    service._build_qna_embed = Mock(return_value=Mock())

    response = Mock()
    response.is_done = Mock(return_value=False)
    response.defer = AsyncMock()
    response.send_message = AsyncMock()

    followup = Mock()
    followup.send = AsyncMock()

    interaction = SimpleNamespace(
        guild_id=10,
        channel_id=20,
        user=SimpleNamespace(id=30, mention="<@30>"),
        response=response,
        followup=followup,
    )

    asyncio.run(service.route_qna(interaction, "che sono i cammelli", scope="general_llm"))

    database.get_trigger_enabled.assert_not_called()
    service._handle_qna.assert_not_called()
    service._ask_general_answer.assert_awaited_once()
    assert "content" not in (followup.send.await_args.kwargs or {})


def test_route_qna_general_llm_stores_anchor_session() -> None:
    database = Mock()
    database.get_usage = AsyncMock(return_value=0)
    database.increment_usage = AsyncMock()

    entitlements = Mock()
    entitlements.resolve_profile = AsyncMock(return_value="role1")

    service = TriggerEngineService(database, Mock(), entitlements, Mock(), community_insights=Mock())
    service._get_qna_daily_limits = AsyncMock(return_value={"role1": 3, "role2": 5, "role3": 8})
    service._resolve_qna_limit = AsyncMock(return_value=3)
    service._ask_general_answer = AsyncMock(return_value="Risposta utile")
    service._build_qna_embed = Mock(return_value=Mock())

    response = Mock()
    response.is_done = Mock(return_value=False)
    response.defer = AsyncMock()

    followup = Mock()
    followup.send = AsyncMock(return_value=SimpleNamespace(id=999))

    interaction = SimpleNamespace(
        guild_id=10,
        channel_id=20,
        user=SimpleNamespace(id=30, mention="<@30>"),
        response=response,
        followup=followup,
    )

    asyncio.run(service.route_qna(interaction, "domanda", scope="general_llm"))

    assert service._qna_sessions.get((10, 20, 999)) is not None


def test_handle_message_qna_reply_session_hit_reanchors() -> None:
    database = Mock()
    database.get_trigger_enabled = AsyncMock(return_value=True)
    database.get_usage = AsyncMock(return_value=0)
    database.increment_usage = AsyncMock()

    service = TriggerEngineService(database, Mock(), Mock(), Mock(), community_insights=Mock())
    service._ask_general_answer = AsyncMock(return_value="Risposta contestuale")
    service._handle_qna = AsyncMock()
    service._qna_sessions.set(
        (10, 20, 500),
        SimpleNamespace(scope="general_llm", history=[{"role": "user", "content": "prima domanda"}], created_at=datetime.now(), last_used_at=datetime.now()),
    )

    captured: dict[str, object] = {}

    async def _reply(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(id=700)

    message = SimpleNamespace(
        guild=SimpleNamespace(id=10),
        channel=SimpleNamespace(id=20),
        author=SimpleNamespace(id=111),
        content="e poi?",
        reference=SimpleNamespace(message_id=500),
        reply=_reply,
    )

    asyncio.run(service.handle_message_qna(message))

    service._ask_general_answer.assert_awaited_once()
    service._handle_qna.assert_not_called()
    assert "embed" in captured.get("kwargs", {})
    assert captured["kwargs"].get("mention_author") is False
    assert len(captured.get("args", ())) == 0
    assert service._qna_sessions.get((10, 20, 700)) is not None


def test_trim_qna_history_limits_and_starts_with_user() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    history = [{"role": "assistant", "content": "a0"}] + [
        {"role": "user" if i % 2 == 0 else "assistant", "content": str(i)} for i in range(30)
    ]
    trimmed = service._trim_qna_history(history, max_messages=16)
    assert len(trimmed) <= 16
    assert trimmed[0]["role"] == "user"


def test_needs_web_search_classifier() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    assert service._needs_web_search("che tempo fa domani a Torino?") is True
    assert service._needs_web_search("quanti minuti ci sono in 3 ore?") is False


def test_ask_general_answer_uses_web_when_needed() -> None:
    ai_service = Mock()
    ai_service.is_enabled.return_value = True
    ai_service.client.return_value = Mock()
    ai_service.get_model.return_value = "gpt-4o-mini"
    ai_service.ask_general_with_web = AsyncMock(return_value="Meteo con fonti")
    ai_service.ask_general = AsyncMock(return_value="offline")

    service = TriggerEngineService(Mock(), Mock(), Mock(), ai_service, community_insights=Mock())
    out = asyncio.run(service._ask_general_answer("meteo domani Torino", history=[{"role": "user", "content": "meteo domani Torino"}]))

    assert out == "Meteo con fonti"
    ai_service.ask_general_with_web.assert_awaited_once()
    ai_service.ask_general.assert_not_called()


def test_build_qna_embed_footer_variants() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    remote = service._build_qna_embed("q", "q?", "risposta", response_origin="remote_ai", model_name="gpt-4o-mini")
    local = service._build_qna_embed("q", "q?", "risposta", response_origin="local_backend")
    error = service._build_qna_embed("q", "q?", "errore", response_origin="error")

    assert getattr(remote, "footer", "") == "Dati elaborati con gpt-4o-mini · Barcellometro 1.0"
    assert getattr(local, "footer", "") == "Dati elaborati in loco · Barcellometro 1.0"
    assert getattr(error, "footer", "") == "Barcellometro 1.0"


def test_format_for_discord_embed_splits_long_general_text_with_bullets_and_emoji() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    long_text = (
        "L'acquario oggi mostra segnali interessanti con alcune variazioni nel comportamento generale del gruppo. "
        "Ci sono dinamiche positive che vale la pena seguire con attenzione nelle prossime ore. "
        "Può essere utile concentrarsi sui punti chiave e mantenere il focus sugli obiettivi pratici. "
        "Inoltre, conviene verificare i dati principali e confrontarli con il trend recente prima di decidere."
    ) * 3
    out = service.format_for_discord_embed(long_text, "general_llm")

    assert "\n" in out
    assert "•" in out
    emoji_count = sum(out.count(ch) for ch in ["💛", "✨", "🔎", "🐹", "📌", "🧠"])
    assert emoji_count >= 3
    assert "**" in out


def test_normalize_discord_formatting_forces_multiline_bullets() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    raw = "✨ - **Energie Altissime**: bene - **Comunicazione al Top**: ok - **Creatività in Crescita**: wow"

    out = service.normalize_discord_formatting(raw)

    assert "\n- **Energie Altissime**" in out
    assert "\n- **Comunicazione al Top**" in out
    assert "\n- **Creatività in Crescita**" in out


def test_format_qna_answer_text_plain_mode_normalizes_single_line_llm_output() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    raw = "✨ - **Energie Altissime**: bene - **Comunicazione al Top**: ok"

    formatted = service._format_qna_answer_text("q", raw, [], scope="general_llm", mode="plain")

    assert "\n- **Energie Altissime**" in formatted
    assert "\n- **Comunicazione al Top**" in formatted


def test_handle_qna_returns_semantic_plain_and_cache_v2() -> None:
    async def _run() -> None:
        database = Mock()
        database.get_cache = AsyncMock(return_value=None)
        database.set_cache = AsyncMock()
        service = TriggerEngineService(database, Mock(), Mock(), Mock(), community_insights=Mock())
        service._qna_query_engine = Mock()
        service._qna_query_engine.answer = AsyncMock(return_value="Risposta semantica")

        out = await service._handle_qna(scope="channel", guild_id="1", channel_id="2", question="di che ha parlato @BritneySpritz ieri?")

        assert out is not None
        assert out.get("answer_mode") == "semantic_plain"
        cache_key = database.set_cache.await_args.args[0]
        assert ":semantic_v3:" in cache_key

    asyncio.run(_run())


def test_route_qna_channel_semantic_plain_renders_plain_mode() -> None:
    async def _run() -> None:
        database = Mock()
        database.get_trigger_enabled = AsyncMock(return_value=True)
        database.get_usage = AsyncMock(return_value=0)
        database.increment_usage = AsyncMock()

        entitlements = Mock()
        entitlements.resolve_profile = AsyncMock(return_value="role1")

        service = TriggerEngineService(database, Mock(), entitlements, Mock(), community_insights=Mock())
        service._get_qna_daily_limits = AsyncMock(return_value={"role1": 3, "role2": 5, "role3": 8})
        service._resolve_qna_limit = AsyncMock(return_value=3)
        service._decide_qna_scope = AsyncMock(return_value="channel")
        service._handle_qna = AsyncMock(
            return_value={
                "can_answer": True,
                "answer": "Risposta semantica pronta",
                "evidence_pack": [{"jump_url": "https://discord.com/channels/1/2/3"}],
                "answer_mode": "semantic_plain",
            }
        )

        called: dict[str, object] = {}

        def _fmt(question, text, evidence, *, scope, mode):
            called["mode"] = mode
            called["evidence"] = evidence
            return text

        service._format_qna_answer_text = Mock(side_effect=_fmt)
        service._build_qna_embed = Mock(return_value=Mock())

        response = Mock()
        response.is_done = Mock(return_value=False)
        response.defer = AsyncMock()

        followup = Mock()
        followup.send = AsyncMock(return_value=SimpleNamespace(id=900))

        interaction = SimpleNamespace(
            guild_id=10,
            channel_id=20,
            user=SimpleNamespace(id=30, mention="<@30>", display_name="Luca", name="Luca"),
            response=response,
            followup=followup,
        )

        await service.route_qna(interaction, "di che ha parlato @BritneySpritz ieri?", scope="channel_qna")

        assert called.get("mode") == "plain"
        assert called.get("evidence") == []

    asyncio.run(_run())


def test_strip_leading_answer_label_variants() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    assert service._strip_leading_answer_label("Risposta\nciao") == "ciao"
    assert service._strip_leading_answer_label("Risposta: ciao") == "ciao"
    assert service._strip_leading_answer_label("**Risposta**\nciao") == "ciao"
    assert service._strip_leading_answer_label("**Risposta:** ciao") == "ciao"
    assert service._strip_leading_answer_label("👇 Risposta:\nciao") == "ciao"


def test_build_qna_embed_removes_answer_label_duplication() -> None:
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    embed = service._build_qna_embed(
        "Luca",
        "di che ha parlato lela ieri?",
        "Risposta:\nHa parlato di Sanremo.",
        response_origin="local_backend",
    )
    description = embed.description or ""
    assert description.count("**👇 Risposta:**") == 1
    assert "\nRisposta" not in description
