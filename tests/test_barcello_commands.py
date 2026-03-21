from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

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
    return SimpleNamespace(
        footer=None,
        entitlements=_FakeEntitlements(allowed=allowed, profile=profile),
        barcello_service=SimpleNamespace(
            compute_channel=AsyncMock(return_value=result),
            compute_pair=AsyncMock(return_value=result),
        ),
        barcello_calibration_service=None,
        database=SimpleNamespace(get_setting=AsyncMock(return_value=None)),
        config=SimpleNamespace(ignore_bots=True, openai_api_key=""),
        ai=None,
        timezone=None,
    )


def _top_level_command(tree: _FakeTree, name: str):
    for command in tree.commands:
        if command.name == name:
            return command
    raise AssertionError(f"Command {name} not registered")


def _admin_barcello_command(admin_group: discord.app_commands.Group, name: str):
    for command in admin_group.commands:
        if command.name != "barcello":
            continue
        for child in command.commands:
            if child.name == name:
                return child
    raise AssertionError(f"Admin barcello command {name} not found")


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


def test_register_barcello_restores_top_level_command_and_keeps_admin_run(barcello_module) -> None:
    admin_group = discord.app_commands.Group(name="admin", description="admin")
    tree = _FakeTree()

    barcello_module.register_barcello(admin_group, tree, None, _ctx_for_result(BarcelloResult(score=75, color="verde")))

    assert any(command.name == "barcello" for command in tree.commands)
    assert any(command.name == "barcello" for command in admin_group.commands)
    assert any(child.name == "run" for child in next(command for command in admin_group.commands if command.name == "barcello").commands)


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
        admin_group = discord.app_commands.Group(name="admin", description="admin")
        tree = _FakeTree()
        send_standard_response = AsyncMock()
        send_dm_or_followup = AsyncMock(return_value=True)
        check_permission = AsyncMock(return_value=True)
        monkeypatch.setattr(barcello_module, "send_standard_response", send_standard_response)
        monkeypatch.setattr(barcello_module, "send_dm_or_followup", send_dm_or_followup)
        monkeypatch.setattr(barcello_module, "check_permission", check_permission)
        monkeypatch.setattr(barcello_module, "get_setting", AsyncMock(return_value="30"))

        barcello_module.register_barcello(admin_group, tree, None, ctx)
        callback = _top_level_command(tree, "barcello").callback

        await callback(_interaction(qualified_name="barcello"), window_minutes=30)

        check_permission.assert_awaited_once()
        assert check_permission.await_args.args[1] == "barcello"
        send_dm_or_followup.assert_awaited_once()
        dm_kwargs = send_dm_or_followup.await_args.kwargs
        assert dm_kwargs["default_service_name"] == "barcello"
        assert len(dm_kwargs["embeds"]) == 2
        assert all(get_footer_meta(embed).service_name == "barcello" for embed in dm_kwargs["embeds"])
        notice_kwargs = send_standard_response.await_args.kwargs
        assert notice_kwargs["subcommand_path"] == "barcello"
        assert notice_kwargs["kind"] == "success"
        assert notice_kwargs["lines"] == [("result", "Ti ho inviato un DM")]

    asyncio.run(_run())


def test_admin_barcello_run_keeps_admin_permission_namespace(
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
        admin_group = discord.app_commands.Group(name="admin", description="admin")
        tree = _FakeTree()
        monkeypatch.setattr(barcello_module, "send_standard_response", AsyncMock())
        monkeypatch.setattr(barcello_module, "send_dm_or_followup", AsyncMock(return_value=True))
        check_permission = AsyncMock(return_value=True)
        monkeypatch.setattr(barcello_module, "check_permission", check_permission)

        barcello_module.register_barcello(admin_group, tree, None, ctx)
        callback = _admin_barcello_command(admin_group, "run").callback

        await callback(_interaction(qualified_name="admin barcello run"), window_minutes=30)

        check_permission.assert_awaited_once()
        assert check_permission.await_args.args[1] == "admin.barcello.run"

    asyncio.run(_run())


def test_user_facing_barcello_no_data_sends_single_report_embed(
    barcello_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        result = BarcelloResult(score=50, color="giallo", metrics={"message_count": 0, "cache_hit": False})
        ctx = _ctx_for_result(result)
        admin_group = discord.app_commands.Group(name="admin", description="admin")
        tree = _FakeTree()
        monkeypatch.setattr(barcello_module, "send_standard_response", AsyncMock())
        send_dm_or_followup = AsyncMock(return_value=True)
        monkeypatch.setattr(barcello_module, "send_dm_or_followup", send_dm_or_followup)
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))

        barcello_module.register_barcello(admin_group, tree, None, ctx)
        callback = _top_level_command(tree, "barcello").callback

        await callback(_interaction(qualified_name="barcello"), window_minutes=30)

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
        admin_group = discord.app_commands.Group(name="admin", description="admin")
        tree = _FakeTree()
        send_standard_response = AsyncMock()
        monkeypatch.setattr(barcello_module, "send_standard_response", send_standard_response)
        monkeypatch.setattr(barcello_module, "send_dm_or_followup", AsyncMock(return_value=False))
        monkeypatch.setattr(barcello_module, "check_permission", AsyncMock(return_value=True))

        barcello_module.register_barcello(admin_group, tree, None, ctx)
        callback = _top_level_command(tree, "barcello").callback

        await callback(_interaction(qualified_name="barcello"), window_minutes=30)

        notice_kwargs = send_standard_response.await_args.kwargs
        assert notice_kwargs["subcommand_path"] == "barcello"
        assert notice_kwargs["kind"] == "warning"
        assert notice_kwargs["lines"] == [("warning", "Non riesco a inviarti DM. Ti mostro il report qui in privato.")]

    asyncio.run(_run())
