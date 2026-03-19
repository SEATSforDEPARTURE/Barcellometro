import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import discord

from tests._sqlite_stub import ensure_sqlite_stub

ensure_sqlite_stub()

from app.services.database import DatabaseService
from app.services.footer import get_footer_meta
from app.services.message_scheduler import (
    MessageSchedulerService,
    select_round_robin_campaign,
    select_text_for_mood,
    should_skip_for_daily_cap,
    should_skip_for_idle,
    split_embed_pages,
)
from app.services.scheduler_utils import (
    calculate_initial_next_run,
    calculate_next_run_after_send,
    is_in_quiet_hours,
)
from app.plugins.commands_modular.messaggi import validate_campaign_texts


def test_next_run_calculation() -> None:
    tz = ZoneInfo("Europe/Rome")
    now = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    next_run = calculate_initial_next_run(now, "10:00", 60, tz)
    assert next_run == datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)

    now_late = datetime(2024, 1, 1, 10, 30, tzinfo=timezone.utc)
    next_run_late = calculate_initial_next_run(now_late, "10:00", 120, tz)
    assert next_run_late == datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc)


def test_next_run_after_send_without_jitter() -> None:
    now = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert calculate_next_run_after_send(now, 15, 0) == datetime(2024, 1, 1, 12, 15, tzinfo=timezone.utc)


def test_idle_skip() -> None:
    now = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    last_activity_recent = now - timedelta(minutes=5)
    last_activity_old = now - timedelta(minutes=20)
    assert should_skip_for_idle(
        last_activity=last_activity_recent,
        only_if_idle_minutes=10,
        now_utc=now,
    )
    assert not should_skip_for_idle(
        last_activity=last_activity_old,
        only_if_idle_minutes=10,
        now_utc=now,
    )


def test_is_in_quiet_hours() -> None:
    assert is_in_quiet_hours(datetime(2024, 1, 1, 2, 0).time(), "01:00", "08:30")
    assert not is_in_quiet_hours(datetime(2024, 1, 1, 10, 0).time(), "01:00", "08:30")
    assert is_in_quiet_hours(datetime(2024, 1, 1, 23, 0).time(), "22:00", "07:00")
    assert is_in_quiet_hours(datetime(2024, 1, 1, 6, 30).time(), "22:00", "07:00")
    assert not is_in_quiet_hours(datetime(2024, 1, 1, 12, 0).time(), "22:00", "07:00")


def test_daily_cap_skip() -> None:
    assert should_skip_for_daily_cap(6, 6)
    assert not should_skip_for_daily_cap(5, 6)


def test_round_robin_selection() -> None:
    now = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    campaigns = [
        {"id": 1, "next_run_at": now.isoformat()},
        {"id": 2, "next_run_at": now.isoformat()},
        {"id": 3, "next_run_at": now.isoformat()},
    ]
    selected = select_round_robin_campaign(campaigns, 2, now)
    assert selected["id"] == 3
    selected_wrap = select_round_robin_campaign(campaigns, 3, now)
    assert selected_wrap["id"] == 1

    campaigns[2]["next_run_at"] = (now + timedelta(minutes=10)).isoformat()
    selected_fallback = select_round_robin_campaign(campaigns, 2, now)
    assert selected_fallback["id"] == 1


def test_barcello_text_selection() -> None:
    text, reason, _ = select_text_for_mood(
        mood_mode="AUTO",
        base_text="base",
        text_green=None,
        text_yellow=None,
        text_red="red",
        text_black="black",
        barcello_color="RED",
    )
    assert text == "red"
    assert reason == "barcello_red"

    text, reason, _ = select_text_for_mood(
        mood_mode="AUTO",
        base_text="base",
        text_green=None,
        text_yellow=None,
        text_red=None,
        text_black="black",
        barcello_color="RED",
    )
    assert text == "base"
    assert reason == "barcello_red"

    text, reason, _ = select_text_for_mood(
        mood_mode="RED_ONLY",
        base_text="base",
        text_green=None,
        text_yellow=None,
        text_red=None,
        text_black=None,
        barcello_color="GREEN",
    )
    assert text == "base"
    assert reason == "barcello_red"

    text, reason, _ = select_text_for_mood(
        mood_mode="AUTO",
        base_text=None,
        text_green=None,
        text_yellow=None,
        text_red=None,
        text_black="black",
        barcello_color="BLACK",
    )
    assert text == "black"
    assert reason == "barcello_black"


def test_validate_campaign_texts() -> None:
    error = validate_campaign_texts(
        text=None,
        text_green=None,
        text_yellow=None,
        text_red=None,
        text_black=None,
        mood_mode="AUTO",
    )
    assert error is not None

    error = validate_campaign_texts(
        text=None,
        text_green="ciao",
        text_yellow=None,
        text_red=None,
        text_black=None,
        mood_mode="AUTO",
    )
    assert error is None

    error = validate_campaign_texts(
        text=None,
        text_green=None,
        text_yellow=None,
        text_red=None,
        text_black="ciao",
        mood_mode="IGNORE_BARCELLO",
    )
    assert error is not None


def test_db_crud_campaigns() -> None:
    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()

        await db.set_message_channel_enabled("guild1", "channel1", True)
        assert await db.get_message_channel_status("guild1", "channel1") is True

        campaign_id = await db.create_message_campaign(
            guild_id="guild1",
            channel_id="channel1",
            campaign_type="CUSTOM",
            name=None,
            text="Hello world",
            text_green=None,
            text_yellow=None,
            text_red=None,
            text_black=None,
            enabled=True,
            start_time_local="10:00",
            interval_minutes=60,
            jitter_seconds=0,
            only_if_idle_minutes=0,
            mood_mode="AUTO",
            next_run_at=datetime.now(timezone.utc).isoformat(),
            created_by="user1",
        )
        campaigns = await db.list_message_campaigns("guild1", include_disabled=True)
        assert len(campaigns) == 1
        assert campaigns[0]["id"] == campaign_id

        await db.set_message_campaign_enabled("guild1", campaign_id, False)
        campaign = await db.get_message_campaign("guild1", campaign_id)
        assert campaign is not None
        assert campaign["enabled"] == 0

        await db.soft_delete_message_campaign("guild1", campaign_id)
        campaigns_after = await db.list_message_campaigns("guild1", include_disabled=True)
        assert campaigns_after == []

        await db.close()

    asyncio.run(_run())


def test_split_embed_pages_prefers_newlines() -> None:
    text = "riga1\nriga2\nriga3"
    pages = split_embed_pages(text, limit=8)
    assert pages == ["riga1\n", "riga2\n", "riga3"]


def test_split_embed_pages_hard_split_long_line() -> None:
    text = "x" * 11
    pages = split_embed_pages(text, limit=4)
    assert pages == ["xxxx", "xxxx", "xxx"]


def test_split_embed_pages_empty_text() -> None:
    assert split_embed_pages("", limit=10) == [""]


def test_send_campaign_embed_multi_page() -> None:
    class DummyChannel:
        def __init__(self) -> None:
            self.sent = []

        async def send(self, **kwargs):
            self.sent.append(kwargs)

    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()
        scheduler = MessageSchedulerService(db, bot=None)  # type: ignore[arg-type]
        channel = DummyChannel()
        campaign = {"id": 7, "name": "Campagna prova", "embed_color": "#112233"}
        text = ("a" * 3900) + "\n" + ("b" * 30)
        await scheduler.send_campaign_embed(channel, campaign, text)
        assert len(channel.sent) == 1
        embeds = channel.sent[0]["embeds"]
        assert len(embeds) == 2
        assert embeds[0].title == "Campagna prova • PAG 1/2"
        assert embeds[1].title == "Campagna prova • PAG 2/2"
        assert get_footer_meta(embeds[0]) is not None
        assert get_footer_meta(embeds[0]).service_name == "campagne_timer"
        assert embeds[0].colour.value == 0x112233
        await db.close()

    asyncio.run(_run())


def test_send_campaign_embed_ai_prompt_uses_prompt_footer_service() -> None:
    class DummyChannel:
        def __init__(self) -> None:
            self.sent = []

        async def send(self, **kwargs):
            self.sent.append(kwargs)

    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()
        scheduler = MessageSchedulerService(db, bot=None)  # type: ignore[arg-type]
        channel = DummyChannel()
        campaign = {"id": 8, "name": "Prompt test", "type": "AI_PROMPT"}
        await scheduler.send_campaign_embed(channel, campaign, "ciao")

        embeds = channel.sent[0]["embeds"]
        meta = get_footer_meta(embeds[0])
        assert meta is not None
        assert meta.service_name == "campagne_prompt"
        assert meta.contributors == []
        assert meta.used_local_processing is True
        await db.close()

    asyncio.run(_run())


def test_send_campaign_embed_ai_prompt_supports_model_contributor_footer() -> None:
    class DummyChannel:
        def __init__(self) -> None:
            self.sent = []

        async def send(self, **kwargs):
            self.sent.append(kwargs)

    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()
        scheduler = MessageSchedulerService(db, bot=None)  # type: ignore[arg-type]
        channel = DummyChannel()
        campaign = {"id": 18, "name": "Prompt test", "type": "AI_PROMPT"}
        await scheduler.send_campaign_embed(
            channel,
            campaign,
            "ciao",
            footer_contributors=["qwen2.5"],
            used_local_processing=False,
        )

        embeds = channel.sent[0]["embeds"]
        meta = get_footer_meta(embeds[0])
        assert meta is not None
        assert meta.service_name == "campagne_prompt"
        assert meta.contributors == ["qwen2.5"]
        assert meta.used_local_processing is False
        await db.close()

    asyncio.run(_run())


def test_process_campaign_one_shot_disables_after_successful_send() -> None:
    class DummyChannel(discord.abc.Messageable):
        async def _get_channel(self):
            return self

        async def send(self, **kwargs):
            return None

    class DummyBot:
        def __init__(self) -> None:
            self.channel = DummyChannel()

        def get_channel(self, _channel_id: int):
            return self.channel

        async def fetch_channel(self, _channel_id: int):
            return self.channel

    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()
        now = datetime.now(timezone.utc)
        campaign_id = await db.create_message_campaign(
            guild_id="1",
            channel_id="123",
            campaign_type="CUSTOM",
            name="oneshot",
            text="hello",
            text_green=None,
            text_yellow=None,
            text_red=None,
            text_black=None,
            enabled=True,
            start_time_local="10:00",
            interval_minutes=0,
            jitter_seconds=0,
            only_if_idle_minutes=0,
            mood_mode="IGNORE_BARCELLO",
            next_run_at=now.isoformat(),
            created_by="u1",
        )
        scheduler = MessageSchedulerService(db, bot=DummyBot())  # type: ignore[arg-type]
        campaign = await db.get_message_campaign("1", campaign_id)
        assert campaign is not None

        await scheduler._process_campaign(dict(campaign), now)

        stored = await db.get_message_campaign("1", campaign_id)
        assert stored is not None
        assert int(stored["enabled"]) == 0
        assert stored["last_sent_at"] is not None
        await db.close()

    asyncio.run(_run())


def test_send_campaign_embed_ai_prompt_defaults_title_when_name_missing() -> None:
    class DummyChannel:
        def __init__(self) -> None:
            self.sent = []

        async def send(self, **kwargs):
            self.sent.append(kwargs)

    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()
        scheduler = MessageSchedulerService(db, bot=None)  # type: ignore[arg-type]
        channel = DummyChannel()
        campaign = {"id": 19, "name": "   ", "type": "AI_PROMPT", "embed_title": None}
        await scheduler.send_campaign_embed(channel, campaign, "ciao")

        embeds = channel.sent[0]["embeds"]
        assert embeds[0].title == "🤔 CURIOSITÀ"
        await db.close()

    asyncio.run(_run())


def test_process_campaign_ai_prompt_one_shot_deletes_after_successful_send() -> None:
    class DummyChannel(discord.abc.Messageable):
        async def _get_channel(self):
            return self

        async def send(self, **kwargs):
            return None

    class DummyBot:
        def __init__(self) -> None:
            self.channel = DummyChannel()

        def get_channel(self, _channel_id: int):
            return self.channel

        async def fetch_channel(self, _channel_id: int):
            return self.channel

        def get_guild(self, _guild_id: int):
            return SimpleNamespace(name="Guild test")

    class DummyAiService:
        def is_enabled(self) -> bool:
            return True

        def client(self):
            return object()

        def get_runtime_model(self, _task: str) -> str:
            return "ollama:qwen2.5"

        def get_model_display_name(self, _task: str) -> str:
            return "qwen2.5"

        def get_model_config(self, _task: str) -> str:
            return "ollama:qwen2.5"

        async def ask_for_task(self, _task: str, _prompt: str, _system: str) -> str:
            return "generated text"

        async def ask_for_task_with_web(self, _task: str, _prompt: str, _system: str) -> str:
            return "generated text"

    async def _run() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()
        now = datetime.now(timezone.utc)
        campaign_id = await db.create_message_campaign(
            guild_id="g1",
            channel_id="123",
            campaign_type="AI_PROMPT",
            name="",
            text="hello",
            text_green=None,
            text_yellow=None,
            text_red=None,
            text_black=None,
            enabled=True,
            start_time_local="10:00",
            interval_minutes=0,
            jitter_seconds=0,
            only_if_idle_minutes=0,
            mood_mode="IGNORE_BARCELLO",
            next_run_at=now.isoformat(),
            created_by="u1",
        )
        scheduler = MessageSchedulerService(db, bot=DummyBot(), ai_service=DummyAiService())  # type: ignore[arg-type]
        campaign = await db.get_message_campaign("g1", campaign_id)
        assert campaign is not None

        await scheduler._process_campaign(dict(campaign), now)

        rows = await db.list_message_campaigns("1", include_disabled=True)
        assert all(int(row["id"]) != campaign_id for row in rows)
        await db.close()

    asyncio.run(_run())
