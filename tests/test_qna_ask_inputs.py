import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncio

import pytest

discord_stub = sys.modules.get("discord")
if discord_stub is None:
    discord_stub = types.ModuleType("discord")
    sys.modules["discord"] = discord_stub
if not hasattr(discord_stub, "Interaction"):
    discord_stub.Interaction = object
if not hasattr(discord_stub, "abc"):
    discord_stub.abc = types.SimpleNamespace(Snowflake=object)
if not hasattr(discord_stub, "app_commands"):
    app_commands_stub = types.ModuleType("app_commands")
    app_commands_stub.CommandTree = object
    app_commands_stub.describe = lambda **kwargs: (lambda func: func)
    discord_stub.app_commands = app_commands_stub

import importlib.util
from pathlib import Path

ctx_stub = types.ModuleType("app.plugins.commands_modular.ctx")
ctx_stub.CommandContext = object
sys.modules["app.plugins.commands_modular.ctx"] = ctx_stub

ask_path = Path(__file__).resolve().parents[1] / "app" / "plugins" / "commands_modular" / "ask.py"
spec = importlib.util.spec_from_file_location("ask_module_for_tests", ask_path)
ask_module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(ask_module)
_handle_ask_like = ask_module._handle_ask_like
parse_qna_input = ask_module.parse_qna_input


class DummyResponse:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bool]] = []

    async def send_message(self, text: str, ephemeral: bool = False) -> None:
        self.sent.append((text, ephemeral))


@pytest.mark.parametrize(
    ("canale", "generale", "expected_scope", "expected_text"),
    [
        ("ciao", None, "channel", "ciao"),
        (None, "mondo", "global", "mondo"),
    ],
)
def test_parse_qna_input_valid(canale: str | None, generale: str | None, expected_scope: str, expected_text: str) -> None:
    err, scope, text = parse_qna_input(canale, generale)
    assert err is None
    assert scope == expected_scope
    assert text == expected_text


def test_parse_qna_input_rejects_both_values() -> None:
    err, scope, text = parse_qna_input("a", "b")
    assert "Compila un solo campo" in str(err)
    assert scope is None
    assert text is None


def test_parse_qna_input_rejects_no_values() -> None:
    err, scope, text = parse_qna_input(None, None)
    assert "Compila uno dei due campi" in str(err)
    assert scope is None
    assert text is None


def test_handle_ask_like_stato_canale() -> None:
    trigger_engine = SimpleNamespace(
        get_qna_quota_for_member=AsyncMock(
            return_value={"tier": "role1", "limit": 1, "used": 0, "remaining": 1, "resets_at_iso": "2026-01-01T00:00:00+00:00"}
        ),
        handle_qna_question=AsyncMock(),
    )
    ctx = SimpleNamespace(trigger_engine=trigger_engine)
    interaction = SimpleNamespace(
        guild_id=1,
        channel_id=2,
        user=SimpleNamespace(id=3),
        response=DummyResponse(),
    )

    asyncio.run(_handle_ask_like(interaction, ctx, "stato", None))

    trigger_engine.handle_qna_question.assert_not_called()
    assert interaction.response.sent
    assert interaction.response.sent[0][1] is True


def test_handle_ask_like_stato_generale() -> None:
    trigger_engine = SimpleNamespace(
        get_qna_quota_for_member=AsyncMock(
            return_value={"tier": "role2", "limit": 2, "used": 1, "remaining": 1, "resets_at_iso": "2026-01-01T00:00:00+00:00"}
        ),
        handle_qna_question=AsyncMock(),
    )
    ctx = SimpleNamespace(trigger_engine=trigger_engine)
    interaction = SimpleNamespace(
        guild_id=1,
        channel_id=2,
        user=SimpleNamespace(id=3),
        response=DummyResponse(),
    )

    asyncio.run(_handle_ask_like(interaction, ctx, None, "StAtO"))

    trigger_engine.handle_qna_question.assert_not_called()
    assert interaction.response.sent
    assert interaction.response.sent[0][1] is True


def test_handle_ask_like_dispatches_scope_override() -> None:
    trigger_engine = SimpleNamespace(get_qna_quota_for_member=AsyncMock(), handle_qna_question=AsyncMock())
    ctx = SimpleNamespace(trigger_engine=trigger_engine)
    interaction = SimpleNamespace(guild_id=1, channel_id=2, user=SimpleNamespace(id=3), response=DummyResponse())

    asyncio.run(_handle_ask_like(interaction, ctx, "Domanda canale", None))
    trigger_engine.handle_qna_question.assert_awaited_once_with(interaction, "Domanda canale", scope_override="channel")


def test_handle_ask_like_dispatches_global_scope_override() -> None:
    trigger_engine = SimpleNamespace(get_qna_quota_for_member=AsyncMock(), handle_qna_question=AsyncMock())
    ctx = SimpleNamespace(trigger_engine=trigger_engine)
    interaction = SimpleNamespace(guild_id=1, channel_id=2, user=SimpleNamespace(id=3), response=DummyResponse())

    asyncio.run(_handle_ask_like(interaction, ctx, None, "Domanda generale"))
    trigger_engine.handle_qna_question.assert_awaited_once_with(interaction, "Domanda generale", scope_override="global")
