import asyncio
import sys
import types
from unittest.mock import AsyncMock, Mock

if "aiosqlite" not in sys.modules:
    aiosqlite_stub = types.ModuleType("aiosqlite")
    aiosqlite_stub.Connection = object
    aiosqlite_stub.connect = object
    sys.modules["aiosqlite"] = aiosqlite_stub

if "httpx" not in sys.modules:
    httpx_stub = types.ModuleType("httpx")

    class _AsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    httpx_stub.AsyncClient = _AsyncClient
    sys.modules["httpx"] = httpx_stub

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.AsyncOpenAI = object
    sys.modules["openai"] = openai_stub

from app.services.ai import AiService
from app.services.ai_utils import parse_model_string


def test_parse_model_string() -> None:
    assert parse_model_string("openai:gpt-4o-mini") == ("openai", "gpt-4o-mini")
    assert parse_model_string("ollama:qwen2.5:1.5b") == ("ollama", "qwen2.5:1.5b")
    assert parse_model_string("gpt-4o-mini") == ("openai", "gpt-4o-mini")


def test_generate_text_uses_fallback() -> None:
    service = AiService(Mock(), api_key="")
    service._model_map = {"summary": "openai:gpt-4o-mini"}
    service._fallback_model_map = {"summary": "ollama:qwen2.5:1.5b"}

    service._generate_text_with_provider = AsyncMock(side_effect=[RuntimeError("boom"), "ok-fallback"])

    out = asyncio.run(service.generate_text("summary", "prompt", "sys"))

    assert out == "ok-fallback"
    assert service._generate_text_with_provider.await_count == 2
