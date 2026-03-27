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
    def __init__(self, *, allowed: bool = True, profile: str = "base") -> None:
        self.allowed = allowed
        self.profile = profile

    async def get_command_profile_config(self, user, command_name: str) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "messages": {"dm_text": "Serve almeno PLUS per usare /barcello."},
            "capabilities": [],
            "output": {},
        }

    async def resolve_profile_with_role_id(self, user) -> tuple[str, int | None]:
        return self.profile, None

    async def is_feature_allowed(self, user, feature: str) -> bool:
        return False


def _ctx_for_result(result: BarcelloResult, *, allowed: bool = True, profile: str = "base") -> SimpleNamespace:
    trigger_engine = SimpleNamespace(run_barcello_trigger_now=AsyncMock(return_value={"evaluated": True, "notified": True, "reason": "ok"}))
    return SimpleNamespace(
        footer=None,
        entitlements=_FakeEntitlements(allowed=allowed, profile=profile),
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
