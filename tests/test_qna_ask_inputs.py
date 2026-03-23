from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def ask_module(import_fresh):
    return import_fresh("app.plugins.commands_modular.ask")


@pytest.mark.parametrize(
    ("canale", "generale", "expected_scope", "expected_text"),
    [
        ("ciao", None, "channel_qna", "ciao"),
        (None, "mondo", "general_llm", "mondo"),
    ],
)
def test_parse_qna_input_valid(ask_module, canale: str | None, generale: str | None, expected_scope: str, expected_text: str) -> None:
    err, scope, text, _, _ = ask_module.parse_qna_input(canale, generale)
    assert err is None
    assert scope == expected_scope
    assert text == expected_text


def test_parse_qna_input_rejects_both_values(ask_module) -> None:
    err, scope, text, has_canale, has_generale = ask_module.parse_qna_input("a", "b")
    assert "Compila un solo campo" in str(err)
    assert scope is None
    assert text is None
    assert has_canale is True
    assert has_generale is True


def test_parse_qna_input_rejects_no_values(ask_module) -> None:
    err, scope, text, has_canale, has_generale = ask_module.parse_qna_input(None, None)
    assert "Compila uno dei due campi" in str(err)
    assert scope is None
    assert text is None
    assert has_canale is False
    assert has_generale is False


def test_handle_ask_like_stato_canale(ask_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        trigger_engine = SimpleNamespace(
            get_qna_quota_for_member=AsyncMock(
                return_value={"tier": "role1", "limit": 1, "used": 0, "remaining": 1, "resets_at_iso": "2026-01-01T00:00:00+00:00"}
            ),
            route_qna=AsyncMock(),
        )
        send_standard_response = AsyncMock()
        monkeypatch.setattr(ask_module, "send_standard_response", send_standard_response)
        ctx = SimpleNamespace(trigger_engine=trigger_engine, footer=None)
        interaction = SimpleNamespace(guild_id=1, channel_id=2, user=SimpleNamespace(id=3))

        await ask_module._handle_ask_like(interaction, ctx, "stato", None)

        trigger_engine.route_qna.assert_not_called()
        kwargs = send_standard_response.await_args.kwargs
        assert kwargs["top_level"] == "qna"
        assert kwargs["subcommand_path"] == "qna status"
        assert kwargs["visual_top_level"] == "qna"
        assert ("tier", "role1") in kwargs["lines"]
        assert ("rimanenti_oggi", 1) in kwargs["lines"]

    asyncio.run(_run())


def test_handle_ask_like_stato_generale(ask_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        trigger_engine = SimpleNamespace(
            get_qna_quota_for_member=AsyncMock(
                return_value={"tier": "role2", "limit": 2, "used": 1, "remaining": 1, "resets_at_iso": "2026-01-01T00:00:00+00:00"}
            ),
            route_qna=AsyncMock(),
        )
        send_standard_response = AsyncMock()
        monkeypatch.setattr(ask_module, "send_standard_response", send_standard_response)
        ctx = SimpleNamespace(trigger_engine=trigger_engine, footer=None)
        interaction = SimpleNamespace(guild_id=1, channel_id=2, user=SimpleNamespace(id=3))

        await ask_module._handle_ask_like(interaction, ctx, None, "StAtO")

        trigger_engine.route_qna.assert_not_called()
        kwargs = send_standard_response.await_args.kwargs
        assert kwargs["top_level"] == "qna"
        assert kwargs["subcommand_path"] == "qna status"
        assert kwargs["visual_top_level"] == "qna"
        assert ("tier", "role2") in kwargs["lines"]

    asyncio.run(_run())


def test_handle_ask_like_dispatches_scope_override(ask_module) -> None:
    async def _run() -> None:
        trigger_engine = SimpleNamespace(get_qna_quota_for_member=AsyncMock(), route_qna=AsyncMock())
        ctx = SimpleNamespace(trigger_engine=trigger_engine, footer=None)
        interaction = SimpleNamespace(guild_id=1, channel_id=2, user=SimpleNamespace(id=3))

        await ask_module._handle_ask_like(interaction, ctx, "Domanda canale", None)
        trigger_engine.route_qna.assert_awaited_once_with(interaction, "Domanda canale", scope="channel_qna")

    asyncio.run(_run())


def test_handle_ask_like_dispatches_global_scope_override(ask_module) -> None:
    async def _run() -> None:
        trigger_engine = SimpleNamespace(get_qna_quota_for_member=AsyncMock(), route_qna=AsyncMock())
        ctx = SimpleNamespace(trigger_engine=trigger_engine, footer=None)
        interaction = SimpleNamespace(guild_id=1, channel_id=2, user=SimpleNamespace(id=3))

        await ask_module._handle_ask_like(interaction, ctx, None, "Domanda generale")
        trigger_engine.route_qna.assert_awaited_once_with(interaction, "Domanda generale", scope="general_llm")

    asyncio.run(_run())
