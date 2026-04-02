from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
from app.plugins.commands_modular.time_windows import TimeWindowResult

from app.services.barcello_service import BarcelloResult
from app.services.footer import get_footer_meta


class _FakeTree:
    def __init__(self) -> None:
        self.commands: list[discord.app_commands.Command] = []

    def add_command(self, command, *, guild=None) -> None:
        self.commands.append(command)


class _FakeEntitlements:
    def __init__(self, *, allowed: bool = True, profile: str = "base", output: dict[str, object] | None = None) -> None:
        self.allowed = allowed
        self.profile = profile
        self.output = output or {}

    async def get_command_profile_config(self, user, command_name: str) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "messages": {"dm_text": "Serve almeno PLUS per usare /barcello."},
            "capabilities": [],
            "output": self.output,
        }

    async def resolve_profile_with_role_id(self, user) -> tuple[str, int | None]:
        return self.profile, None

    async def is_feature_allowed(self, user, feature: str) -> bool:
        return False


def _ctx_for_result(
    result: BarcelloResult,
    *,
    allowed: bool = True,
    profile: str = "base",
    output: dict[str, object] | None = None,
) -> SimpleNamespace:
    trigger_engine = SimpleNamespace(run_barcello_trigger_now=AsyncMock(return_value={"evaluated": True, "notified": True, "reason": "ok"}))
    return SimpleNamespace(
        footer=None,
        entitlements=_FakeEntitlements(allowed=allowed, profile=profile, output=output),
        barcello_service=SimpleNamespace(
            compute_channel=AsyncMock(return_value=result),
            compute_channel_range=AsyncMock(return_value=result),
            compute_pair=AsyncMock(return_value=result),
            compute_pair_range=AsyncMock(return_value=result),
        ),
        barcello_calibration_service=SimpleNamespace(run_calibration=AsyncMock(return_value={"updated": False, "samples": 0, "summary": ""})),
        database=SimpleNamespace(
            get_setting=AsyncMock(return_value=None),
            get_trigger_enabled=AsyncMock(return_value=False),
            set_trigger_enabled=AsyncMock(),
            create_trigger_barcello_schedule=AsyncMock(return_value=1),
            get_trigger_barcello_schedule=AsyncMock(return_value=None),
            list_trigger_barcello_schedules=AsyncMock(return_value=[]),
            update_trigger_barcello_schedule=AsyncMock(return_value=True),
            delete_trigger_barcello_schedule=AsyncMock(return_value=True),
            upsert_trigger_barcello_quiet_hours=AsyncMock(),
            get_trigger_barcello_quiet_hours=AsyncMock(return_value=None),
            delete_trigger_barcello_quiet_hours=AsyncMock(return_value=True),
        ),
        config=SimpleNamespace(ignore_bots=True, openai_api_key=""),
        ai=None,
        trigger_engine=trigger_engine,
        timezone=None,
    )


def _top_level_command(tree: _FakeTree, name: str):
    for command in tree.commands:
        if command.name == name:
            return command
    raise AssertionError(f"Command {name} not registered")


def _group_command(group: discord.app_commands.Group, name: str):
    for command in group.commands:
        if command.name == name:
            return command
    raise AssertionError(f"Command {name} not registered in group {group.name}")


def _triggers_barcello_command(triggers_group: discord.app_commands.Group, name: str):
    for command in triggers_group.commands:
        if command.name != "barcello":
            continue
        for child in command.commands:
            if child.name == name:
                return child
    raise AssertionError(f"Triggers barcello command {name} not found")


def _interaction(*, qualified_name: str) -> SimpleNamespace:
    response = SimpleNamespace(is_done=lambda: False, defer=AsyncMock())
    followup = SimpleNamespace(send=AsyncMock())
    user = SimpleNamespace(
        id=42,
        bot=False,
        roles=[],
        guild_permissions=SimpleNamespace(administrator=False),
    )
    return SimpleNamespace(
        guild_id=100,
        channel_id=200,
        channel=SimpleNamespace(name="general"),
        guild=None,
        user=user,
        response=response,
        followup=followup,
        command=SimpleNamespace(qualified_name=qualified_name),
        data={"name": qualified_name.split()[0]},
    )


@pytest.fixture
def barcello_module(import_fresh):
    return import_fresh("app.plugins.commands_modular.barcello")


def test_register_barcello_registers_summary_and_alias_namespaces(barcello_module) -> None:
    triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
    dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
    barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
    tree = _FakeTree()

    barcello_module.register_barcello(
        triggers_group,
        dmchannelsummary_group,
        barcello_alias_group,
        tree,
        None,
        _ctx_for_result(BarcelloResult(score=75, color="verde")),
    )

    assert tree.commands == []
    assert isinstance(barcello_alias_group, discord.app_commands.Group)
    assert any(command.name == "barcello" for command in triggers_group.commands)
    assert {child.name for child in next(command for command in triggers_group.commands if command.name == "barcello").commands} == {
        "on",
        "off",
        "status",
        "run",
        "calibrate",
        "schedule_add",
        "schedule_edit",
        "schedule_remove",
        "schedule_show",
        "schedule_list",
        "quiet_set",
        "quiet_show",
        "quiet_reset",
    }
    summary_barcello = _group_command(dmchannelsummary_group, "barcello")
    assert {child.name for child in summary_barcello.commands} == {"on", "off", "status", "today", "yesterday", "last", "range"}
    assert {child.name for child in barcello_alias_group.commands} == {"oggi", "ieri", "ultimi", "intervallo"}
    assert all(child.name != "barcello" for child in barcello_alias_group.commands)


def test_dmchannelsummary_barcello_toggles_use_canonical_permission_namespace(
    barcello_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        ctx = _ctx_for_result(BarcelloResult(score=75, color="verde"))
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        check_permission = AsyncMock(return_value=True)
        send_standard_response = AsyncMock()
        monkeypatch.setattr(barcello_module, "check_permission", check_permission)
        monkeypatch.setattr(barcello_module, "send_standard_response", send_standard_response)

        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        summary_barcello = _group_command(dmchannelsummary_group, "barcello")
        on_callback = _group_command(summary_barcello, "on").callback
        status_callback = _group_command(summary_barcello, "status").callback

        await on_callback(_interaction(qualified_name="dmchannelsummary barcello on"))
        await status_callback(_interaction(qualified_name="dmchannelsummary barcello status"))

        assert check_permission.await_args_list[0].args[1] == "admin.dmchannelsummary.barcello.on"
        assert check_permission.await_args_list[1].args[1] == "admin.dmchannelsummary.barcello.status"
        assert send_standard_response.await_args_list[0].kwargs["subcommand_path"] == "dmchannelsummary barcello on"
        assert send_standard_response.await_args_list[1].kwargs["subcommand_path"] == "dmchannelsummary barcello status"

    asyncio.run(_run())


def test_user_facing_barcello_uses_standardized_dm_flow_and_non_admin_permission(
    barcello_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        result = BarcelloResult(
            score=78,
            color="verde",
            window_start_ts="2026-03-21T10:00:00+00:00",
            window_end_ts="2026-03-21T10:30:00+00:00",
            metrics={"message_count": 42, "cache_hit": False},
        )
        ctx = _ctx_for_result(result)
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        send_standard_response = AsyncMock()
        send_dm_or_followup = AsyncMock(return_value=True)
        check_permission = AsyncMock(return_value=True)
        monkeypatch.setattr(barcello_module, "send_standard_response", send_standard_response)
        monkeypatch.setattr(barcello_module, "send_dm_or_followup", send_dm_or_followup)
        monkeypatch.setattr(barcello_module, "check_permission", check_permission)
        monkeypatch.setattr(barcello_module, "get_setting", AsyncMock(return_value="30"))

        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _group_command(barcello_alias_group, "oggi").callback

        await callback(_interaction(qualified_name="barcello oggi"))

        check_permission.assert_awaited_once()
        assert check_permission.await_args.args[1] == "barcello"
        send_dm_or_followup.assert_awaited_once()
        dm_kwargs = send_dm_or_followup.await_args.kwargs
        assert dm_kwargs["default_service_name"] == "barcello"
        assert len(dm_kwargs["embeds"]) == 2
        assert all(get_footer_meta(embed).service_name == "barcello" for embed in dm_kwargs["embeds"])
        notice_kwargs = send_standard_response.await_args.kwargs
        assert notice_kwargs["subcommand_path"] == "barcello oggi"
        assert notice_kwargs["kind"] == "success"
        assert notice_kwargs["lines"] == [("result", "Ti ho inviato un DM")]

    asyncio.run(_run())


def test_triggers_barcello_run_uses_canonical_permission_namespace(
    barcello_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        result = BarcelloResult(
            score=65,
            color="giallo",
            window_start_ts="2026-03-21T10:00:00+00:00",
            window_end_ts="2026-03-21T10:30:00+00:00",
            metrics={"message_count": 30, "cache_hit": False},
        )
        ctx = _ctx_for_result(result)
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        send_standard_response = AsyncMock()
        monkeypatch.setattr(barcello_module, "send_standard_response", send_standard_response)
        send_dm_or_followup = AsyncMock(return_value=True)
        monkeypatch.setattr(barcello_module, "send_dm_or_followup", send_dm_or_followup)
        check_permission = AsyncMock(return_value=True)
        monkeypatch.setattr(barcello_module, "check_permission", check_permission)

        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _triggers_barcello_command(triggers_group, "run").callback

        await callback(_interaction(qualified_name="triggers barcello run"), window_minutes=30)

        check_permission.assert_awaited_once()
        assert check_permission.await_args.args[1] == "admin.triggers.barcello.run"
        ctx.trigger_engine.run_barcello_trigger_now.assert_awaited_once_with(
            "100",
            "200",
            window_minutes=30,
            force_publish=True,
            user1_id=None,
            user2_id=None,
        )
        send_dm_or_followup.assert_not_awaited()
        assert send_standard_response.await_args.kwargs["subcommand_path"] == "triggers barcello run"
        assert send_standard_response.await_args.kwargs["kind"] == "info"

    asyncio.run(_run())


def test_triggers_barcello_run_reports_channel_post_when_trigger_notifies(
    barcello_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        result = BarcelloResult(score=65, color="giallo", metrics={"message_count": 30, "cache_hit": False})
        ctx = _ctx_for_result(result)
        ctx.trigger_engine.run_barcello_trigger_now = AsyncMock(return_value={"evaluated": True, "notified": True, "reason": "ok"})
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        send_standard_response = AsyncMock()
        monkeypatch.setattr(barcello_module, "send_standard_response", send_standard_response)
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))

        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _triggers_barcello_command(triggers_group, "run").callback

        await callback(_interaction(qualified_name="triggers barcello run"), window_minutes=15)

        assert send_standard_response.await_args.kwargs["kind"] == "info"
        assert "pubblicato nel canale" in send_standard_response.await_args.kwargs["lines"][0][1]

    asyncio.run(_run())


def test_triggers_barcello_run_requires_both_pair_users(
    barcello_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        result = BarcelloResult(score=65, color="giallo", metrics={"message_count": 30, "cache_hit": False})
        ctx = _ctx_for_result(result)
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        send_standard_response = AsyncMock()
        monkeypatch.setattr(barcello_module, "send_standard_response", send_standard_response)
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))

        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _triggers_barcello_command(triggers_group, "run").callback

        await callback(
            _interaction(qualified_name="triggers barcello run"),
            user1=SimpleNamespace(id=111, bot=False),
            user2=None,
            window_minutes=15,
        )

        ctx.trigger_engine.run_barcello_trigger_now.assert_not_awaited()
        assert send_standard_response.await_args.kwargs["kind"] == "info"
        assert "specificare sia user1 che user2" in send_standard_response.await_args.kwargs["lines"][0][1]

    asyncio.run(_run())


def test_user_facing_barcello_no_data_sends_single_report_embed(
    barcello_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        result = BarcelloResult(score=50, color="giallo", metrics={"message_count": 0, "cache_hit": False})
        ctx = _ctx_for_result(result)
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        monkeypatch.setattr(barcello_module, "send_standard_response", AsyncMock())
        send_dm_or_followup = AsyncMock(return_value=True)
        monkeypatch.setattr(barcello_module, "send_dm_or_followup", send_dm_or_followup)
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))

        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _group_command(barcello_alias_group, "oggi").callback

        await callback(_interaction(qualified_name="barcello oggi"))

        send_dm_or_followup.assert_awaited_once()
        embeds = send_dm_or_followup.await_args.kwargs["embeds"]
        assert len(embeds) == 1
        assert get_footer_meta(embeds[0]).service_name == "barcello"

    asyncio.run(_run())


def test_user_facing_barcello_warns_when_dm_delivery_fails(
    barcello_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        result = BarcelloResult(
            score=72,
            color="verde",
            window_start_ts="2026-03-21T10:00:00+00:00",
            window_end_ts="2026-03-21T10:30:00+00:00",
            metrics={"message_count": 33, "cache_hit": False},
        )
        ctx = _ctx_for_result(result)
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        send_standard_response = AsyncMock()
        monkeypatch.setattr(barcello_module, "send_standard_response", send_standard_response)
        monkeypatch.setattr(barcello_module, "send_dm_or_followup", AsyncMock(return_value=False))
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))

        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _group_command(barcello_alias_group, "oggi").callback

        await callback(_interaction(qualified_name="barcello oggi"))

        notice_kwargs = send_standard_response.await_args.kwargs
        assert notice_kwargs["subcommand_path"] == "barcello oggi"
        assert notice_kwargs["kind"] == "warning"
        assert notice_kwargs["lines"] == [("warning", "Non riesco a inviarti DM. Ti mostro il report qui in privato.")]

    asyncio.run(_run())


def test_alias_and_canonical_report_commands_share_the_same_report_pipeline(
    barcello_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        result = BarcelloResult(
            score=80,
            color="verde",
            window_start_ts="2026-03-21T10:00:00+00:00",
            window_end_ts="2026-03-21T10:30:00+00:00",
            metrics={"message_count": 50, "cache_hit": False},
        )
        ctx = _ctx_for_result(result)
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        monkeypatch.setattr(barcello_module, "send_standard_response", AsyncMock())
        monkeypatch.setattr(barcello_module, "send_dm_or_followup", AsyncMock(return_value=True))
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(
            barcello_module,
            "resolve_oggi_window",
            lambda: TimeWindowResult(
                start_dt=datetime(2026, 3, 21, 0, 0, tzinfo=timezone.utc),
                end_dt=datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc),
                period_label="oggi",
                label_periodo="oggi",
            ),
        )

        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        summary_barcello = _group_command(dmchannelsummary_group, "barcello")
        today_callback = _group_command(summary_barcello, "today").callback
        oggi_callback = _group_command(barcello_alias_group, "oggi").callback

        await today_callback(_interaction(qualified_name="dmchannelsummary barcello today"))
        await oggi_callback(_interaction(qualified_name="barcello oggi"))

        assert ctx.barcello_service.compute_channel_range.await_count == 2
        first_call = ctx.barcello_service.compute_channel_range.await_args_list[0]
        second_call = ctx.barcello_service.compute_channel_range.await_args_list[1]

        first_start = first_call.kwargs.get("start_ts", first_call.args[2])
        first_end = first_call.kwargs.get("end_ts", first_call.args[3])
        second_start = second_call.kwargs.get("start_ts", second_call.args[2])
        second_end = second_call.kwargs.get("end_ts", second_call.args[3])
        assert first_start == second_start
        assert first_end == second_end

    asyncio.run(_run())


@pytest.mark.parametrize(
    ("color", "driver", "direction", "expected_tokens"),
    [
        ("verde", "active_recovery", "improving", ["**migliorando**", "**equilibrati**"]),
        ("verde", "passive_recovery", "improving", ["**assenza di attività**"]),
        ("verde", "playful_activity", "stable", ["**vivace**", "**sana**"]),
        ("giallo", "venting", "worsening", ["**nervosismo**"]),
        ("giallo", "stable_balance", "stable", ["**stabile**"]),
        ("rosso", "directed_conflict", "worsening", ["**attacco diretto**"]),
        ("rosso", "deescalation", "improving", ["**de-escalation**"]),
        ("nero", "escalation", "worsening", ["**escalation**"]),
        ("giallo", "rising_tension", "worsening", ["**tensione**"]),
        ("verde", "unknown", "mystery", ["segnali **misti**"]),
    ],
)
def test_trend_section_is_two_bullets_and_uses_driver_catalog(
    barcello_module,
    monkeypatch: pytest.MonkeyPatch,
    color: str,
    driver: str,
    direction: str,
    expected_tokens: list[str],
) -> None:
    async def _run() -> None:
        result = BarcelloResult(
            score=75,
            color=color,
            window_start_ts="2026-03-21T10:00:00+00:00",
            window_end_ts="2026-03-21T10:30:00+00:00",
            metrics={"message_count": 42, "cache_hit": False, "msg_per_min": 3.0, "burst_ratio": 1.2},
            trend={
                "direction": direction,
                "delta": 6 if direction == "improving" else -6 if direction == "worsening" else 0,
                "dominant_driver": driver,
                "minutes_since_same_state": 17,
                "message_count_current_window": 42,
                "message_count_previous_window": 40,
            },
        )
        ctx = _ctx_for_result(
            result,
            output={"show_trend": True, "show_motivation": False, "show_advice": False, "show_mod_metrics": False},
        )
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        monkeypatch.setattr(barcello_module, "send_standard_response", AsyncMock())
        send_dm_or_followup = AsyncMock(return_value=True)
        monkeypatch.setattr(barcello_module, "send_dm_or_followup", send_dm_or_followup)
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(barcello_module, "get_setting", AsyncMock(return_value="30"))

        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _group_command(barcello_alias_group, "oggi").callback
        await callback(_interaction(qualified_name="barcello oggi"))

        embeds = send_dm_or_followup.await_args.kwargs["embeds"]
        details_embed = embeds[1]
        trend_field = next(field for field in details_embed.fields if "TREND" in field.name.upper())
        trend_lines = [line for line in trend_field.value.splitlines() if line.strip()]
        assert len(trend_lines) == 2
        assert trend_lines[0] == "• L'ultima volta in questo stato è stata **17 minuti fa**."
        for token in expected_tokens:
            assert token in trend_lines[1]
        assert any("PUNTI SALUTE" in field.name.upper() for field in embeds[0].fields)

    asyncio.run(_run())


def test_triggers_barcello_schedule_add_success(barcello_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        ctx = _ctx_for_result(BarcelloResult(score=75, color="verde"))
        ctx.database.create_trigger_barcello_schedule = AsyncMock(return_value=44)
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        send_standard_response = AsyncMock()
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(barcello_module, "send_standard_response", send_standard_response)
        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _triggers_barcello_command(triggers_group, "schedule_add").callback

        await callback(_interaction(qualified_name="triggers barcello schedule_add"), publish_at="02/04/2026 18:30", every=15, embed_title="Titolo")

        ctx.database.create_trigger_barcello_schedule.assert_awaited_once()
        args = ctx.database.create_trigger_barcello_schedule.await_args.kwargs
        assert args["guild_id"] == "100"
        assert args["channel_id"] == "200"
        assert args["every_minutes"] == 15
        assert args["embed_title"] == "Titolo"
        assert send_standard_response.await_args.kwargs["kind"] == "success"

    asyncio.run(_run())


def test_triggers_barcello_schedule_add_success_without_every_or_embed_title(
    barcello_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        ctx = _ctx_for_result(BarcelloResult(score=75, color="verde"))
        ctx.database.create_trigger_barcello_schedule = AsyncMock(return_value=45)
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        send_standard_response = AsyncMock()
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(barcello_module, "send_standard_response", send_standard_response)

        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _triggers_barcello_command(triggers_group, "schedule_add").callback

        await callback(_interaction(qualified_name="triggers barcello schedule_add"), publish_at="02/04/2026 18:30")

        args = ctx.database.create_trigger_barcello_schedule.await_args.kwargs
        assert args["every_minutes"] == 0
        assert args["embed_title"] is None
        assert send_standard_response.await_args.kwargs["kind"] == "success"

    asyncio.run(_run())


def test_triggers_barcello_schedule_add_success_without_embed_title(barcello_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        ctx = _ctx_for_result(BarcelloResult(score=75, color="verde"))
        ctx.database.create_trigger_barcello_schedule = AsyncMock(return_value=46)
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(barcello_module, "send_standard_response", AsyncMock())

        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _triggers_barcello_command(triggers_group, "schedule_add").callback
        await callback(_interaction(qualified_name="triggers barcello schedule_add"), publish_at="02/04/2026 18:30", every=15)

        args = ctx.database.create_trigger_barcello_schedule.await_args.kwargs
        assert args["every_minutes"] == 15
        assert args["embed_title"] is None

    asyncio.run(_run())


def test_triggers_barcello_schedule_add_every_zero_is_one_shot(barcello_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        ctx = _ctx_for_result(BarcelloResult(score=75, color="verde"))
        ctx.database.create_trigger_barcello_schedule = AsyncMock(return_value=47)
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(barcello_module, "send_standard_response", AsyncMock())

        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _triggers_barcello_command(triggers_group, "schedule_add").callback
        await callback(_interaction(qualified_name="triggers barcello schedule_add"), publish_at="02/04/2026 18:30", every=0, embed_title="   ")

        args = ctx.database.create_trigger_barcello_schedule.await_args.kwargs
        assert args["every_minutes"] == 0
        assert args["embed_title"] is None

    asyncio.run(_run())


def test_triggers_barcello_schedule_add_invalid_publish_at(barcello_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        ctx = _ctx_for_result(BarcelloResult(score=75, color="verde"))
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        send_standard_response = AsyncMock()
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(barcello_module, "send_standard_response", send_standard_response)
        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _triggers_barcello_command(triggers_group, "schedule_add").callback

        await callback(_interaction(qualified_name="triggers barcello schedule_add"), publish_at="2026-04-02 18:30", every=15, embed_title=None)

        ctx.database.create_trigger_barcello_schedule.assert_not_awaited()
        assert "`publish_at` deve essere nel formato DD/MM/YYYY HH:MM." in send_standard_response.await_args.kwargs["lines"][0][1]

    asyncio.run(_run())


def test_triggers_barcello_schedule_add_invalid_every(barcello_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        ctx = _ctx_for_result(BarcelloResult(score=75, color="verde"))
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        send_standard_response = AsyncMock()
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(barcello_module, "send_standard_response", send_standard_response)
        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _triggers_barcello_command(triggers_group, "schedule_add").callback

        await callback(_interaction(qualified_name="triggers barcello schedule_add"), publish_at="02/04/2026 18:30", every=-1, embed_title=None)

        ctx.database.create_trigger_barcello_schedule.assert_not_awaited()
        assert "`every` deve essere un numero di minuti maggiore o uguale a 0." in send_standard_response.await_args.kwargs["lines"][0][1]

    asyncio.run(_run())


def test_triggers_barcello_schedule_edit_success_and_toggle_enabled(barcello_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        current = {
            "id": 3,
            "guild_id": "100",
            "channel_id": "200",
            "publish_at": "2026-04-02T16:30:00+00:00",
            "next_run_at": "2026-04-02T16:30:00+00:00",
            "every_minutes": 15,
            "enabled": 1,
            "embed_title": "Old",
        }
        updated = dict(current)
        updated["enabled"] = 0
        ctx = _ctx_for_result(BarcelloResult(score=75, color="verde"))
        ctx.database.get_trigger_barcello_schedule = AsyncMock(side_effect=[current, updated])
        ctx.database.update_trigger_barcello_schedule = AsyncMock(return_value=True)
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        send_standard_response = AsyncMock()
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(barcello_module, "send_standard_response", send_standard_response)
        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _triggers_barcello_command(triggers_group, "schedule_edit").callback

        await callback(
            _interaction(qualified_name="triggers barcello schedule_edit"),
            id=3,
            publish_at="02/04/2026 18:30",
            every=30,
            embed_title=" Nuovo ",
            enabled=False,
        )

        ctx.database.update_trigger_barcello_schedule.assert_awaited_once()
        kwargs = ctx.database.update_trigger_barcello_schedule.await_args.kwargs
        assert kwargs["enabled"] is False
        assert kwargs["every_minutes"] == 30
        assert kwargs["embed_title"] == "Nuovo"
        assert send_standard_response.await_args.kwargs["kind"] == "success"

    asyncio.run(_run())


def test_triggers_barcello_schedule_edit_updates_only_enabled(barcello_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        current = {
            "id": 3,
            "guild_id": "100",
            "channel_id": "200",
            "publish_at": "2026-04-02T16:30:00+00:00",
            "next_run_at": "2026-04-02T16:30:00+00:00",
            "every_minutes": 15,
            "enabled": 1,
            "embed_title": "Old",
        }
        updated = dict(current)
        updated["enabled"] = 0
        ctx = _ctx_for_result(BarcelloResult(score=75, color="verde"))
        ctx.database.get_trigger_barcello_schedule = AsyncMock(side_effect=[current, updated])
        ctx.database.update_trigger_barcello_schedule = AsyncMock(return_value=True)
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(barcello_module, "send_standard_response", AsyncMock())

        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _triggers_barcello_command(triggers_group, "schedule_edit").callback
        await callback(_interaction(qualified_name="triggers barcello schedule_edit"), id=3, enabled=False)

        kwargs = ctx.database.update_trigger_barcello_schedule.await_args.kwargs
        assert kwargs["enabled"] is False
        assert kwargs["publish_at"] is None
        assert kwargs["every_minutes"] is None
        assert kwargs["embed_title"] is None

    asyncio.run(_run())


def test_triggers_barcello_schedule_edit_updates_only_embed_title(barcello_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        current = {"id": 3, "guild_id": "100", "channel_id": "200", "publish_at": "2026-04-02T16:30:00+00:00", "embed_title": "Old"}
        updated = dict(current)
        updated["embed_title"] = "Nuovo titolo"
        ctx = _ctx_for_result(BarcelloResult(score=75, color="verde"))
        ctx.database.get_trigger_barcello_schedule = AsyncMock(side_effect=[current, updated])
        ctx.database.update_trigger_barcello_schedule = AsyncMock(return_value=True)
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(barcello_module, "send_standard_response", AsyncMock())

        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _triggers_barcello_command(triggers_group, "schedule_edit").callback
        await callback(_interaction(qualified_name="triggers barcello schedule_edit"), id=3, embed_title=" Nuovo titolo ")

        kwargs = ctx.database.update_trigger_barcello_schedule.await_args.kwargs
        assert kwargs["embed_title"] == "Nuovo titolo"
        assert kwargs["every_minutes"] is None
        assert kwargs["publish_at"] is None

    asyncio.run(_run())


def test_triggers_barcello_schedule_edit_updates_only_every(barcello_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        current = {
            "id": 3,
            "guild_id": "100",
            "channel_id": "200",
            "publish_at": "2026-04-02T16:30:00+00:00",
            "next_run_at": "2026-04-02T16:30:00+00:00",
            "every_minutes": 15,
            "enabled": 1,
            "embed_title": "Old",
        }
        updated = dict(current)
        updated["every_minutes"] = 30
        ctx = _ctx_for_result(BarcelloResult(score=75, color="verde"))
        ctx.database.get_trigger_barcello_schedule = AsyncMock(side_effect=[current, updated])
        ctx.database.update_trigger_barcello_schedule = AsyncMock(return_value=True)
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(barcello_module, "send_standard_response", AsyncMock())

        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _triggers_barcello_command(triggers_group, "schedule_edit").callback
        await callback(_interaction(qualified_name="triggers barcello schedule_edit"), id=3, every=30)

        kwargs = ctx.database.update_trigger_barcello_schedule.await_args.kwargs
        assert kwargs["every_minutes"] == 30
        assert kwargs["publish_at"] is None
        assert kwargs["embed_title"] is None

    asyncio.run(_run())


def test_triggers_barcello_schedule_edit_without_optional_fields_is_safe(barcello_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        current = {"id": 3, "guild_id": "100", "channel_id": "200", "publish_at": "2026-04-02T16:30:00+00:00", "embed_title": "Old"}
        ctx = _ctx_for_result(BarcelloResult(score=75, color="verde"))
        ctx.database.get_trigger_barcello_schedule = AsyncMock(side_effect=[current, current])
        ctx.database.update_trigger_barcello_schedule = AsyncMock(return_value=True)
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        send_standard_response = AsyncMock()
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(barcello_module, "send_standard_response", send_standard_response)

        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _triggers_barcello_command(triggers_group, "schedule_edit").callback
        await callback(_interaction(qualified_name="triggers barcello schedule_edit"), id=3)

        assert ctx.database.update_trigger_barcello_schedule.await_count == 1
        assert send_standard_response.await_args.kwargs["kind"] == "success"

    asyncio.run(_run())


def test_triggers_barcello_schedule_edit_blank_embed_title_clears_value(barcello_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        current = {"id": 3, "guild_id": "100", "channel_id": "200", "publish_at": "2026-04-02T16:30:00+00:00", "embed_title": "Old"}
        updated = dict(current)
        updated["embed_title"] = None
        ctx = _ctx_for_result(BarcelloResult(score=75, color="verde"))
        ctx.database.get_trigger_barcello_schedule = AsyncMock(side_effect=[current, updated])
        ctx.database.update_trigger_barcello_schedule = AsyncMock(return_value=True)
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(barcello_module, "send_standard_response", AsyncMock())

        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _triggers_barcello_command(triggers_group, "schedule_edit").callback
        await callback(_interaction(qualified_name="triggers barcello schedule_edit"), id=3, embed_title="   ")

        kwargs = ctx.database.update_trigger_barcello_schedule.await_args.kwargs
        assert kwargs["embed_title"] is None
        assert kwargs["clear_embed_title"] is True

    asyncio.run(_run())


def test_triggers_barcello_schedule_command_signature_optional_fields(barcello_module) -> None:
    ctx = _ctx_for_result(BarcelloResult(score=75, color="verde"))
    triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
    dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
    barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
    tree = _FakeTree()
    barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)

    add_parameters = {param.name: param for param in _triggers_barcello_command(triggers_group, "schedule_add").parameters}
    assert add_parameters["publish_at"].required is True
    assert add_parameters["every"].required is False
    assert add_parameters["embed_title"].required is False

    edit_parameters = {param.name: param for param in _triggers_barcello_command(triggers_group, "schedule_edit").parameters}
    assert edit_parameters["id"].required is True
    assert edit_parameters["publish_at"].required is False
    assert edit_parameters["every"].required is False
    assert edit_parameters["embed_title"].required is False
    assert edit_parameters["enabled"].required is False


def test_triggers_barcello_schedule_show_success_and_not_found(barcello_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        row = {
            "id": 7,
            "guild_id": "100",
            "channel_id": "200",
            "publish_at": "2026-04-02T16:30:00+00:00",
            "next_run_at": "2026-04-02T17:30:00+00:00",
            "every_minutes": 60,
            "enabled": 1,
            "last_run_at": "2026-04-02T15:30:00+00:00",
            "last_sent_at": "2026-04-02T15:30:00+00:00",
            "embed_title": None,
        }
        ctx = _ctx_for_result(BarcelloResult(score=75, color="verde"))
        ctx.database.get_trigger_barcello_schedule = AsyncMock(side_effect=[row, None])
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        send_standard_response = AsyncMock()
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(barcello_module, "send_standard_response", send_standard_response)
        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _triggers_barcello_command(triggers_group, "schedule_show").callback

        await callback(_interaction(qualified_name="triggers barcello schedule_show"), id=7)
        await callback(_interaction(qualified_name="triggers barcello schedule_show"), id=8)

        first_call = send_standard_response.await_args_list[0].kwargs
        assert first_call["kind"] == "info"
        assert first_call["sections"][0].lines[1] == ("Abilitata", "sì")
        second_call = send_standard_response.await_args_list[1].kwargs
        assert "Schedule Barcello non trovata in questo canale." in second_call["lines"][0][1]

    asyncio.run(_run())


def test_triggers_barcello_schedule_remove_success_and_not_found(barcello_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        row = {"id": 9, "guild_id": "100", "channel_id": "200"}
        ctx = _ctx_for_result(BarcelloResult(score=75, color="verde"))
        ctx.database.get_trigger_barcello_schedule = AsyncMock(side_effect=[row, None, row])
        ctx.database.delete_trigger_barcello_schedule = AsyncMock(side_effect=[True, False])
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        send_standard_response = AsyncMock()
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(barcello_module, "send_standard_response", send_standard_response)
        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _triggers_barcello_command(triggers_group, "schedule_remove").callback

        await callback(_interaction(qualified_name="triggers barcello schedule_remove"), id=9)
        await callback(_interaction(qualified_name="triggers barcello schedule_remove"), id=10)
        await callback(_interaction(qualified_name="triggers barcello schedule_remove"), id=11)

        assert send_standard_response.await_args_list[0].kwargs["kind"] == "success"
        assert "non trovata" in send_standard_response.await_args_list[1].kwargs["lines"][0][1]
        assert "non trovata" in send_standard_response.await_args_list[2].kwargs["lines"][0][1]

    asyncio.run(_run())


def test_triggers_barcello_schedule_list_empty_and_with_items_and_cross_channel_not_found(
    barcello_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        ctx = _ctx_for_result(BarcelloResult(score=75, color="verde"))
        ctx.database.list_trigger_barcello_schedules = AsyncMock(
            side_effect=[
                [],
                [
                    {
                        "id": 1,
                        "enabled": 1,
                        "publish_at": "2026-04-02T16:30:00+00:00",
                        "every_minutes": 0,
                        "next_run_at": "2026-04-02T16:30:00+00:00",
                        "embed_title": "",
                    }
                ],
            ]
        )
        ctx.database.get_trigger_barcello_schedule = AsyncMock(
            return_value={"id": 99, "guild_id": "100", "channel_id": "555"}
        )
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        send_standard_response = AsyncMock()
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(barcello_module, "send_standard_response", send_standard_response)
        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        list_callback = _triggers_barcello_command(triggers_group, "schedule_list").callback
        show_callback = _triggers_barcello_command(triggers_group, "schedule_show").callback

        await list_callback(_interaction(qualified_name="triggers barcello schedule_list"))
        await list_callback(_interaction(qualified_name="triggers barcello schedule_list"))
        await show_callback(_interaction(qualified_name="triggers barcello schedule_show"), id=99)

        assert send_standard_response.await_args_list[0].kwargs["kind"] == "warning"
        assert "Nessuna schedule Barcello configurata in questo canale." in send_standard_response.await_args_list[0].kwargs["sections"][0].lines[0]
        assert send_standard_response.await_args_list[1].kwargs["kind"] == "info"
        assert "ID 1 · enabled" in send_standard_response.await_args_list[1].kwargs["sections"][0].lines[0]
        assert "non trovata in questo canale" in send_standard_response.await_args_list[2].kwargs["lines"][0][1]

    asyncio.run(_run())


def test_triggers_barcello_quiet_set_success_and_invalid_format(barcello_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        ctx = _ctx_for_result(BarcelloResult(score=66, color="verde"))
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        send_standard_response = AsyncMock()
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(barcello_module, "send_standard_response", send_standard_response)

        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _triggers_barcello_command(triggers_group, "quiet_set").callback

        await callback(_interaction(qualified_name="triggers barcello quiet_set"), start="23:00", end="08:00")
        await callback(_interaction(qualified_name="triggers barcello quiet_set"), start="23", end="08:00")

        ctx.database.upsert_trigger_barcello_quiet_hours.assert_awaited_once_with(
            guild_id="100",
            channel_id="200",
            quiet_start="23:00",
            quiet_end="08:00",
        )
        messages = [call.kwargs["lines"] for call in send_standard_response.await_args_list]
        assert [("result", "Quiet hours Barcello aggiornate.")] in messages
        assert any(("dettaglio", "Formato non valido: usa HH:MM (es. 23:00).") in lines for lines in messages)

    asyncio.run(_run())


def test_triggers_barcello_quiet_show_empty_and_configured_and_reset(barcello_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        ctx = _ctx_for_result(BarcelloResult(score=66, color="verde"))
        ctx.database.get_trigger_barcello_quiet_hours = AsyncMock(
            side_effect=[None, {"quiet_start": "22:30", "quiet_end": "07:15", "updated_at": datetime.now(timezone.utc).isoformat()}]
        )
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        send_standard_response = AsyncMock()
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(barcello_module, "send_standard_response", send_standard_response)

        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        show_callback = _triggers_barcello_command(triggers_group, "quiet_show").callback
        reset_callback = _triggers_barcello_command(triggers_group, "quiet_reset").callback

        await show_callback(_interaction(qualified_name="triggers barcello quiet_show"))
        await show_callback(_interaction(qualified_name="triggers barcello quiet_show"))
        await reset_callback(_interaction(qualified_name="triggers barcello quiet_reset"))

        assert ctx.database.get_trigger_barcello_quiet_hours.await_count == 2
        ctx.database.delete_trigger_barcello_quiet_hours.assert_awaited_once_with("100", "200")
        configured = [
            call.kwargs
            for call in send_standard_response.await_args_list
            if call.kwargs.get("subcommand_path") == "triggers barcello quiet_show" and call.kwargs.get("sections")
        ][0]
        assert configured["sections"][0].lines[0] == ("start", "22:30")
        assert configured["sections"][0].lines[1] == ("end", "07:15")

    asyncio.run(_run())


def test_triggers_barcello_run_does_not_touch_scheduled_publish_anchor_from_command_layer(
    barcello_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        result = BarcelloResult(score=65, color="giallo", metrics={"message_count": 30, "cache_hit": False})
        ctx = _ctx_for_result(result)
        ctx.database.get_trigger_barcello_publish_anchor = AsyncMock()
        ctx.database.upsert_trigger_barcello_publish_anchor = AsyncMock()
        triggers_group = discord.app_commands.Group(name="triggers", description="triggers")
        dmchannelsummary_group = discord.app_commands.Group(name="dmchannelsummary", description="dmchannelsummary")
        barcello_alias_group = discord.app_commands.Group(name="barcello", description="barcello")
        tree = _FakeTree()
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(barcello_module, "send_standard_response", AsyncMock())

        barcello_module.register_barcello(triggers_group, dmchannelsummary_group, barcello_alias_group, tree, None, ctx)
        callback = _triggers_barcello_command(triggers_group, "run").callback
        await callback(_interaction(qualified_name="triggers barcello run"), window_minutes=15)

        ctx.database.get_trigger_barcello_publish_anchor.assert_not_awaited()
        ctx.database.upsert_trigger_barcello_publish_anchor.assert_not_awaited()

    asyncio.run(_run())
