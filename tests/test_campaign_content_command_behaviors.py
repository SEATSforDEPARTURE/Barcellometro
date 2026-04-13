import asyncio
import importlib.util
import sys
import types
from datetime import timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest


@pytest.fixture
def messaggi_module(monkeypatch):
    commands_modular_pkg = types.ModuleType("app.plugins.commands_modular")
    commands_modular_pkg.__path__ = [str(Path(__file__).resolve().parents[1] / "app" / "plugins" / "commands_modular")]
    monkeypatch.setitem(sys.modules, "app.plugins.commands_modular", commands_modular_pkg)

    ctx_stub = types.ModuleType("app.plugins.commands_modular.ctx")
    ctx_stub.CommandContext = object
    monkeypatch.setitem(sys.modules, "app.plugins.commands_modular.ctx", ctx_stub)

    permissions_stub = types.ModuleType("app.plugins.commands_modular.permissions")
    permissions_stub.check_permission = AsyncMock(return_value=True)
    monkeypatch.setitem(sys.modules, "app.plugins.commands_modular.permissions", permissions_stub)

    helpers_stub = types.ModuleType("app.plugins.commands_modular.command_helpers")
    helpers_stub.add_group_once = lambda parent, subgroup, logger: parent.add_command(subgroup)
    helpers_stub.count_child_commands = lambda parent: len(getattr(parent, "commands", []))
    monkeypatch.setitem(sys.modules, "app.plugins.commands_modular.command_helpers", helpers_stub)

    scheduler_stub = types.ModuleType("app.services.scheduler_utils")
    scheduler_stub.calculate_initial_next_run = lambda now, ora_inizio, every, timezone: now
    scheduler_stub.calculate_next_run_after_send = lambda now, every, timezone: now
    scheduler_stub.calculate_next_summary_schedule_run_utc = lambda *args, **kwargs: None
    scheduler_stub.ROME_TZ = object()
    monkeypatch.setitem(sys.modules, "app.services.scheduler_utils", scheduler_stub)

    command_embeds_stub = types.ModuleType("app.shared.discord.command_embeds")
    command_embeds_stub.CommandEmbedSection = lambda *args, **kwargs: {"args": args, "kwargs": kwargs}
    command_embeds_stub.CommandKind = str
    command_embeds_stub.send_standard_response = AsyncMock()
    monkeypatch.setitem(sys.modules, "app.shared.discord.command_embeds", command_embeds_stub)

    module_path = Path(__file__).resolve().parents[1] / "app" / "plugins" / "commands_modular" / "messaggi.py"
    spec = importlib.util.spec_from_file_location("messaggi_module_for_tests", module_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class _FakeDb:
    def __init__(self) -> None:
        self.message_campaign = None
        self.service_campaign = None
        self.service_campaign_by_id = None
        self.service_campaigns = []
        self.created_service_payload = None

    async def get_message_campaign(self, guild_id: str, campaign_id: int):
        _ = guild_id, campaign_id
        return self.message_campaign

    async def get_campaign_content_config(self, guild_id: str, campaign_id: int):
        _ = guild_id, campaign_id
        return self.service_campaign_by_id

    async def get_campaign_content_config_by_service(self, guild_id: str, channel_id: str, service_type: str):
        _ = guild_id, channel_id
        if self.service_campaign and self.service_campaign.get("service_type") == service_type:
            return self.service_campaign
        return None

    async def list_campaign_content_configs_by_service(self, guild_id: str, *, service_type: str, channel_id: str | None = None, include_disabled: bool = True):
        _ = guild_id, include_disabled
        rows = [row for row in self.service_campaigns if row.get("service_type") == service_type]
        if channel_id is not None:
            rows = [row for row in rows if str(row.get("channel_id")) == str(channel_id)]
        return rows

    async def create_campaign_content_config(self, **kwargs):
        self.created_service_payload = kwargs
        return 999

    async def get_message_channel_status(self, guild_id: str, channel_id: str):
        _ = guild_id, channel_id
        return True


class _FakeScheduler:
    def __init__(self) -> None:
        self.preview_campaign_text = AsyncMock(return_value=("ciao", None, None))
        self.send_campaign_embed = AsyncMock()
        self._campaign_content_service = SimpleNamespace(
            execute_news_service=AsyncMock(),
            execute_weather_service=AsyncMock(),
            execute_horoscope_service=AsyncMock(),
        )


class _FakeChannel(discord.abc.Messageable):
    async def _get_channel(self):
        return self

    async def send(self, *args, **kwargs):
        return SimpleNamespace(id=1)


class _FakeResponse:
    def __init__(self) -> None:
        self.send_message = AsyncMock()
        self.is_done = lambda: False


class _FakeInteraction:
    def __init__(self) -> None:
        self.guild_id = 1
        self.channel_id = 10
        self.channel = _FakeChannel()
        self.user = SimpleNamespace(id=55)
        self.response = _FakeResponse()


def _get_subgroup(group: discord.app_commands.Group, name: str):
    return next(cmd for cmd in group.commands if isinstance(cmd, discord.app_commands.Group) and cmd.name == name)


def _get_command_callback(group: discord.app_commands.Group, name: str):
    return next(cmd.callback for cmd in group.commands if cmd.name == name)


def test_custom_run_reports_not_found_when_campaign_missing(messaggi_module) -> None:
    async def _run() -> None:
        db = _FakeDb()
        scheduler = _FakeScheduler()
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone=timezone.utc, footer=object())

        group = discord.app_commands.Group(name="campaigns", description="x")
        messaggi_module.register_messaggi(group, ctx)
        custom_group = _get_subgroup(group, "custom")
        callback = _get_command_callback(custom_group, "run")
        interaction = _FakeInteraction()
        await callback(interaction, id=99)

        messaggi_module.send_standard_response.assert_awaited_once_with(
            interaction,
            top_level="campaigns",
            subcommand_path="campaigns custom run",
            visual_top_level="campaigns",
            subtitle_args=[99],
            lines=[("warning", "Custom schedule not found.")],
            sections=None,
            kind="warning",
            footer_service=ctx.footer,
        )

    asyncio.run(_run())


def test_weather_run_dispatches_editorial_service(messaggi_module) -> None:
    async def _run() -> None:
        db = _FakeDb()
        db.service_campaigns = [{"id": 7, "service_type": "WEATHER", "channel_id": "10"}]
        scheduler = _FakeScheduler()
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone=timezone.utc, footer=object())

        group = discord.app_commands.Group(name="campaigns", description="x")
        messaggi_module.register_messaggi(group, ctx)
        weather_group = _get_subgroup(group, "weather")
        callback = _get_command_callback(weather_group, "run")
        interaction = _FakeInteraction()
        await callback(interaction)

        messaggi_module.send_standard_response.assert_awaited_once_with(
            interaction,
            top_level="campaigns",
            subcommand_path="campaigns weather run",
            visual_top_level="campaigns",
            subtitle_args=None,
            lines=[("schedule_id", 7), ("channel", "<#10>"), ("result", "running")],
            sections=None,
            kind="success",
            footer_service=ctx.footer,
        )
        scheduler._campaign_content_service.execute_weather_service.assert_awaited_once_with(db.service_campaigns[0])
        scheduler._campaign_content_service.execute_news_service.assert_not_called()
        scheduler._campaign_content_service.execute_horoscope_service.assert_not_called()

    asyncio.run(_run())


def test_service_runs_dispatch_by_service_type(messaggi_module) -> None:
    async def _run() -> None:
        for subgroup_name, service_type, attr_name in [
            ("weather", "WEATHER", "execute_weather_service"),
            ("news", "NEWS", "execute_news_service"),
            ("horoscope", "HOROSCOPE", "execute_horoscope_service"),
        ]:
            db = _FakeDb()
            db.service_campaigns = [{"id": 3, "service_type": service_type, "channel_id": "10"}]
            scheduler = _FakeScheduler()
            ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone="Europe/Rome", footer=object())
            group = discord.app_commands.Group(name="campaigns", description="x")

            messaggi_module.send_standard_response.reset_mock()
            messaggi_module.register_messaggi(group, ctx)
            subgroup = _get_subgroup(group, subgroup_name)
            callback = _get_command_callback(subgroup, "run")
            interaction = _FakeInteraction()
            await callback(interaction)

            getattr(scheduler._campaign_content_service, attr_name).assert_awaited_once_with(db.service_campaigns[0])

    asyncio.run(_run())


def test_service_run_by_id_uses_exact_schedule(messaggi_module) -> None:
    async def _run() -> None:
        db = _FakeDb()
        db.service_campaign_by_id = {"id": 91, "service_type": "NEWS", "channel_id": "77"}
        scheduler = _FakeScheduler()
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone=timezone.utc, footer=object())
        group = discord.app_commands.Group(name="campaigns", description="x")

        messaggi_module.register_messaggi(group, ctx)
        news_group = _get_subgroup(group, "news")
        callback = _get_command_callback(news_group, "run")
        interaction = _FakeInteraction()
        await callback(interaction, id=91)

        scheduler._campaign_content_service.execute_news_service.assert_awaited_once_with(db.service_campaign_by_id)

    asyncio.run(_run())


def test_service_run_by_id_rejects_wrong_service_type(messaggi_module) -> None:
    async def _run() -> None:
        db = _FakeDb()
        db.service_campaign_by_id = {"id": 12, "service_type": "NEWS", "channel_id": "10"}
        scheduler = _FakeScheduler()
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone=timezone.utc, footer=object())
        group = discord.app_commands.Group(name="campaigns", description="x")

        messaggi_module.register_messaggi(group, ctx)
        weather_group = _get_subgroup(group, "weather")
        callback = _get_command_callback(weather_group, "run")
        interaction = _FakeInteraction()
        await callback(interaction, id=12)

        scheduler._campaign_content_service.execute_weather_service.assert_not_called()
        messaggi_module.send_standard_response.assert_awaited_once()
        assert messaggi_module.send_standard_response.await_args.kwargs["kind"] == "error"

    asyncio.run(_run())


def test_service_run_without_id_is_not_ambiguous_when_multiple_rows(messaggi_module) -> None:
    async def _run() -> None:
        db = _FakeDb()
        db.service_campaigns = [
            {"id": 3, "service_type": "HOROSCOPE", "channel_id": "10"},
            {"id": 4, "service_type": "HOROSCOPE", "channel_id": "10"},
        ]
        scheduler = _FakeScheduler()
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone=timezone.utc, footer=object())
        group = discord.app_commands.Group(name="campaigns", description="x")

        messaggi_module.register_messaggi(group, ctx)
        horoscope_group = _get_subgroup(group, "horoscope")
        callback = _get_command_callback(horoscope_group, "run")
        interaction = _FakeInteraction()
        await callback(interaction)

        scheduler._campaign_content_service.execute_horoscope_service.assert_not_called()
        assert messaggi_module.send_standard_response.await_args.kwargs["kind"] == "error"

    asyncio.run(_run())


def test_news_schedule_add_validates_and_normalizes_sources_and_categories(messaggi_module) -> None:
    async def _run() -> None:
        db = _FakeDb()
        scheduler = _FakeScheduler()
        scheduler.is_valid_embed_color = lambda _: True
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone=timezone.utc, footer=object())
        group = discord.app_commands.Group(name="campaigns", description="x")

        messaggi_module.register_messaggi(group, ctx)
        news_group = _get_subgroup(group, "news")
        callback = _get_command_callback(news_group, "schedule_add")
        interaction = _FakeInteraction()
        await callback(
            interaction,
            sources="ANSA, ansa, repubblica",
            categories="Tech, tech, politica",
        )

        assert db.created_service_payload is not None
        assert db.created_service_payload["sources_json"] == '["ansa", "repubblica"]'
        assert db.created_service_payload["categories_json"] == "tecnologia,politica"

    asyncio.run(_run())


def test_news_schedule_add_accepts_display_labels_and_persists_canonical_values(messaggi_module) -> None:
    async def _run() -> None:
        db = _FakeDb()
        scheduler = _FakeScheduler()
        scheduler.is_valid_embed_color = lambda _: True
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone=timezone.utc, footer=object())
        group = discord.app_commands.Group(name="campaigns", description="x")

        messaggi_module.register_messaggi(group, ctx)
        news_group = _get_subgroup(group, "news")
        callback = _get_command_callback(news_group, "schedule_add")
        interaction = _FakeInteraction()
        await callback(
            interaction,
            sources="ansa.it, repubblica.it, https://www.corriere.it",
            categories="Curiosità, Politica, Tech",
        )

        assert db.created_service_payload is not None
        assert db.created_service_payload["sources_json"] == '["ansa", "repubblica", "corriere"]'
        assert db.created_service_payload["categories_json"] == "curiosita,politica,tecnologia"

    asyncio.run(_run())


def test_news_run_uses_scheduler_backed_next_run_resolver() -> None:
    source = Path(__file__).resolve().parents[1].joinpath("app/services/campaign_content_service.py").read_text()
    assert "_resolve_next_news_scheduled_run" in source
    assert "next_scheduled_run_at" in source


def test_news_schedule_add_persists_extras_json(messaggi_module) -> None:
    async def _run() -> None:
        db = _FakeDb()
        scheduler = _FakeScheduler()
        scheduler.is_valid_embed_color = lambda _: True
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone=timezone.utc, footer=object())
        group = discord.app_commands.Group(name="campaigns", description="x")

        messaggi_module.register_messaggi(group, ctx)
        news_group = _get_subgroup(group, "news")
        callback = _get_command_callback(news_group, "schedule_add")
        interaction = _FakeInteraction()
        await callback(interaction, extras="barzelletta, meme, barzelletta")

        assert db.created_service_payload is not None
        assert db.created_service_payload["extras_json"] == '["barzelletta", "meme"]'

    asyncio.run(_run())


def test_news_schedule_add_rejects_unsupported_sources(messaggi_module) -> None:
    async def _run() -> None:
        db = _FakeDb()
        scheduler = _FakeScheduler()
        scheduler.is_valid_embed_color = lambda _: True
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone="Europe/Rome", footer=object())
        group = discord.app_commands.Group(name="campaigns", description="x")

        messaggi_module.register_messaggi(group, ctx)
        news_group = _get_subgroup(group, "news")
        callback = _get_command_callback(news_group, "schedule_add")
        interaction = _FakeInteraction()
        await callback(interaction, sources="unsupported")

        assert db.created_service_payload is None
        assert messaggi_module.send_standard_response.await_args.kwargs["kind"] == "error"

    asyncio.run(_run())


def test_guided_sources_autocomplete_contextual_and_no_duplicates(messaggi_module) -> None:
    choices = messaggi_module._compose_guided_csv_suggestions(
        "ansa.it, rep",
        allowed_values=messaggi_module.NEWS_SOURCE_CHOICES,
        preferred_labels=messaggi_module.NEWS_SOURCE_LABELS,
        aliases=messaggi_module.NEWS_SOURCE_ALIASES,
    )
    values = [choice.value for choice in choices]
    assert "ansa.it" not in values
    assert "ansa.it, repubblica.it" in values
    assert all(", " in value for value in values)


def test_guided_categories_autocomplete_uses_last_token_only(messaggi_module) -> None:
    choices = messaggi_module._compose_guided_csv_suggestions(
        "esteri, pol",
        allowed_values=messaggi_module.NEWS_CATEGORY_CHOICES,
        preferred_labels=messaggi_module.NEWS_CATEGORY_LABELS,
        aliases=messaggi_module.NEWS_CATEGORY_ALIASES,
        normalizer=messaggi_module._fold_token,
    )
    values = [choice.value for choice in choices]
    assert "Mondo, Politica" in values
    assert all(value.startswith("Mondo, ") for value in values)


def test_guided_autocomplete_selected_values_are_excluded(messaggi_module) -> None:
    choices = messaggi_module._compose_guided_csv_suggestions(
        "Spettacolo, cr",
        allowed_values=messaggi_module.NEWS_CATEGORY_CHOICES,
        preferred_labels=messaggi_module.NEWS_CATEGORY_LABELS,
        aliases=messaggi_module.NEWS_CATEGORY_ALIASES,
        normalizer=messaggi_module._fold_token,
    )
    names = [choice.name for choice in choices]
    assert "Spettacolo" not in names
    assert "Cronaca" in names


def test_guided_choice_values_rebuild_full_csv_for_sources(messaggi_module) -> None:
    choices = messaggi_module._compose_guided_csv_suggestions(
        "ansa.it, rep",
        allowed_values=messaggi_module.NEWS_SOURCE_CHOICES,
        preferred_labels=messaggi_module.NEWS_SOURCE_LABELS,
        aliases=messaggi_module.NEWS_SOURCE_ALIASES,
    )
    match = next(choice for choice in choices if choice.name == "repubblica.it")
    assert match.value == "ansa.it, repubblica.it"


def test_guided_selecting_second_category_preserves_first_in_csv_value(messaggi_module) -> None:
    choices = messaggi_module._compose_guided_csv_suggestions(
        "Spettacolo, cr",
        allowed_values=messaggi_module.NEWS_CATEGORY_CHOICES,
        preferred_labels=messaggi_module.NEWS_CATEGORY_LABELS,
        aliases=messaggi_module.NEWS_CATEGORY_ALIASES,
        normalizer=messaggi_module._fold_token,
    )
    match = next(choice for choice in choices if choice.name == "Cronaca")
    assert match.value == "Spettacolo, Cronaca"


def test_guided_selecting_second_source_preserves_first_in_csv_value(messaggi_module) -> None:
    choices = messaggi_module._compose_guided_csv_suggestions(
        "ansa.it, rep",
        allowed_values=messaggi_module.NEWS_SOURCE_CHOICES,
        preferred_labels=messaggi_module.NEWS_SOURCE_LABELS,
        aliases=messaggi_module.NEWS_SOURCE_ALIASES,
    )
    match = next(choice for choice in choices if choice.name == "repubblica.it")
    assert match.value == "ansa.it, repubblica.it"


def test_parse_guided_sources_normalizes_aliases_and_dedupes(messaggi_module) -> None:
    normalized, invalid = messaggi_module._parse_guided_csv_values(
        "ANSA.IT, ansa, https://www.repubblica.it, repubblica",
        allowed=messaggi_module.NEWS_SOURCE_CHOICES,
        aliases=messaggi_module.NEWS_SOURCE_ALIASES,
    )
    assert invalid == []
    assert normalized == ["ansa", "repubblica"]


def test_parse_guided_categories_normalizes_casing_spaces_and_accents(messaggi_module) -> None:
    normalized, invalid = messaggi_module._parse_guided_csv_values(
        "  Curiosità, curiosita,  POLITICA ",
        allowed=messaggi_module.NEWS_CATEGORY_CHOICES,
        aliases=messaggi_module.NEWS_CATEGORY_ALIASES,
        normalizer=messaggi_module._fold_token,
    )
    assert invalid == []
    assert normalized == ["curiosita", "politica"]


def test_guided_categories_suggestions_are_canonicalized_without_duplicate_aliases(messaggi_module) -> None:
    choices = messaggi_module._compose_guided_csv_suggestions(
        "cur",
        allowed_values=messaggi_module.NEWS_CATEGORY_CHOICES,
        preferred_labels=messaggi_module.NEWS_CATEGORY_LABELS,
        aliases=messaggi_module.NEWS_CATEGORY_ALIASES,
        normalizer=messaggi_module._fold_token,
    )
    names = [choice.name for choice in choices]
    assert names.count("Curiosità") == 1
    assert "Curiosita" not in names


def test_parse_guided_values_rejects_unsupported_tokens(messaggi_module) -> None:
    normalized, invalid = messaggi_module._parse_guided_csv_values(
        "ansa, not-supported",
        allowed=messaggi_module.NEWS_SOURCE_CHOICES,
        aliases=messaggi_module.NEWS_SOURCE_ALIASES,
    )
    assert normalized == ["ansa"]
    assert invalid == ["not-supported"]


def test_news_schedule_add_command_exposes_autocomplete() -> None:
    source = Path("app/plugins/commands_modular/messaggi.py").read_text(encoding="utf-8")
    assert "@app_commands.autocomplete(sources=_news_sources_autocomplete, categories=_news_categories_autocomplete, extras=_news_extras_autocomplete)" in source


def test_weather_and_horoscope_schedule_commands_expose_guided_autocomplete() -> None:
    source = Path("app/plugins/commands_modular/messaggi.py").read_text(encoding="utf-8")
    assert "@app_commands.autocomplete(categories=_weather_areas_autocomplete)" in source
    assert "@app_commands.autocomplete(categories=_horoscope_signs_autocomplete)" in source


def test_weather_schedule_add_normalizes_selected_areas(messaggi_module) -> None:
    async def _run() -> None:
        db = _FakeDb()
        scheduler = _FakeScheduler()
        scheduler.is_valid_embed_color = lambda _: True
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone=timezone.utc, footer=object())
        group = discord.app_commands.Group(name="campaigns", description="x")
        messaggi_module.register_messaggi(group, ctx)
        weather_group = _get_subgroup(group, "weather")
        callback = _get_command_callback(weather_group, "schedule_add")
        await callback(_FakeInteraction(), categories="Nord, centro, Nord")
        assert db.created_service_payload["categories_json"] == "nord,centro"

    asyncio.run(_run())


def test_horoscope_schedule_add_rejects_unsupported_signs(messaggi_module) -> None:
    async def _run() -> None:
        db = _FakeDb()
        scheduler = _FakeScheduler()
        scheduler.is_valid_embed_color = lambda _: True
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone=timezone.utc, footer=object())
        group = discord.app_commands.Group(name="campaigns", description="x")
        messaggi_module.register_messaggi(group, ctx)
        horoscope_group = _get_subgroup(group, "horoscope")
        callback = _get_command_callback(horoscope_group, "schedule_add")
        await callback(_FakeInteraction(), categories="Ariete, SegnoInventato")
        assert db.created_service_payload is None
        assert messaggi_module.send_standard_response.await_args.kwargs["kind"] == "error"

    asyncio.run(_run())


def test_custom_run_keeps_existing_behavior_for_message_campaign(messaggi_module) -> None:
    async def _run() -> None:
        db = _FakeDb()
        db.message_campaign = {"id": 11, "type": "CUSTOM", "text": "hello", "mood_mode": "AUTO"}
        scheduler = _FakeScheduler()
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone="Europe/Rome", footer=object())
        group = discord.app_commands.Group(name="campaigns", description="x")

        messaggi_module.register_messaggi(group, ctx)
        custom_group = _get_subgroup(group, "custom")
        callback = _get_command_callback(custom_group, "run")
        interaction = _FakeInteraction()
        await callback(interaction, id=11)

        messaggi_module.send_standard_response.assert_awaited_once_with(
            interaction,
            top_level="campaigns",
            subcommand_path="campaigns custom run",
            visual_top_level="campaigns",
            subtitle_args=[11],
            lines=[("schedule_id", 11), ("result", "running")],
            sections=None,
            kind="success",
            footer_service=ctx.footer,
        )
        scheduler.preview_campaign_text.assert_awaited_once_with(db.message_campaign, channel_id_override="10")
        scheduler.send_campaign_embed.assert_awaited_once()

    asyncio.run(_run())


def test_custom_run_checks_permission_candidates_in_order(messaggi_module) -> None:
    async def _run() -> None:
        db = _FakeDb()
        db.message_campaign = {"id": 12, "type": "CUSTOM", "text": "hello", "mood_mode": "AUTO"}
        scheduler = _FakeScheduler()
        ctx = SimpleNamespace(database=db, message_scheduler=scheduler, timezone="Europe/Rome", footer=object())
        group = discord.app_commands.Group(name="campaigns", description="x")

        messaggi_module.check_permission.reset_mock()
        messaggi_module.check_permission.side_effect = [False, True]

        messaggi_module.register_messaggi(group, ctx)
        custom_group = _get_subgroup(group, "custom")
        callback = _get_command_callback(custom_group, "run")
        interaction = _FakeInteraction()
        await callback(interaction, id=12)

        assert [call.args[1] for call in messaggi_module.check_permission.await_args_list] == [
            "campaigns.custom.run",
            "campaigns.custom.entry_run",
        ]
        messaggi_module.send_standard_response.assert_awaited_once_with(
            interaction,
            top_level="campaigns",
            subcommand_path="campaigns custom run",
            visual_top_level="campaigns",
            subtitle_args=[12],
            lines=[("schedule_id", 12), ("result", "running")],
            sections=None,
            kind="success",
            footer_service=ctx.footer,
        )
        scheduler.preview_campaign_text.assert_awaited_once_with(db.message_campaign, channel_id_override="10")

    asyncio.run(_run())
