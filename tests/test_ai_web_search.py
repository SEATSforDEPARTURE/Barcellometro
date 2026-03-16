import asyncio
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

if "aiosqlite" not in sys.modules:
    aiosqlite_stub = types.ModuleType("aiosqlite")
    aiosqlite_stub.Connection = object
    aiosqlite_stub.connect = object
    sys.modules["aiosqlite"] = aiosqlite_stub

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.AsyncOpenAI = object
    sys.modules["openai"] = openai_stub

from app.services.ai import AiService


def test_ask_general_with_web_calls_responses_with_tool() -> None:
    service = AiService(Mock(), api_key="x")
    client = Mock()
    client.responses.create = AsyncMock(return_value=SimpleNamespace(output_text="ok"))
    service._enabled = True
    service._client = client
    service._model_map = {"summary": "gpt-4o-mini"}

    out = asyncio.run(
        service.ask_general_with_web(
            question="meteo domani a Torino",
            persona_system="Sei Barcellometro",
            history=[{"role": "user", "content": "meteo domani a Torino"}],
        )
    )

    assert out == "ok"
    kwargs = client.responses.create.await_args.kwargs
    assert kwargs["model"] == "gpt-4o-mini"
    assert kwargs["tools"] == [{"type": "web_search"}]
    assert kwargs["input"][0]["role"] == "system"


def test_load_settings_initializes_audio_summary_default() -> None:
    db = Mock()

    async def _get_setting(key: str):
        values = {
            "ai_enabled": "true",
            "ai_model.summary": "gpt-4.1-mini",
            "ai_model.transcription": "gpt-4o-transcribe",
            "ai_model.translation": "gpt-4o-mini",
        }
        return values.get(key)

    db.get_setting = AsyncMock(side_effect=_get_setting)
    db.set_setting = AsyncMock()
    service = AiService(db, api_key="")

    asyncio.run(service.load_settings())

    assert service.get_model("audio_summary") == "gpt-4o-mini"
    db.set_setting.assert_any_await("ai_model.audio_summary", "gpt-4o-mini")
