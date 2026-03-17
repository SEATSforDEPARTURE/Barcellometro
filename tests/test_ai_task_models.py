import asyncio
import sys
import types
from unittest.mock import AsyncMock

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


class _Db:
    def __init__(self) -> None:
        self.settings: dict[str, str] = {}

    async def get_setting(self, key: str):
        return self.settings.get(key)

    async def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value


class _FakeResponses:
    def __init__(self) -> None:
        self.create = AsyncMock(return_value=types.SimpleNamespace(output_text="ok"))


class _FakeClient:
    def __init__(self) -> None:
        self.responses = _FakeResponses()


def test_supported_tasks_include_campaign_tasks() -> None:
    assert "campaign_editorial" in AiService.SUPPORTED_MODEL_TASKS
    assert "campaign_prompt" in AiService.SUPPORTED_MODEL_TASKS


def test_load_maps_include_campaign_tasks_and_fallback() -> None:
    async def _run() -> None:
        db = _Db()
        service = AiService(db, api_key="")
        models = await service._load_model_map()
        fallback = await service._load_fallback_model_map()
        assert "campaign_editorial" in models
        assert "campaign_prompt" in models
        assert "campaign_editorial" in fallback
        assert "campaign_prompt" in fallback

    asyncio.run(_run())


def test_ask_general_delegates_to_summary_task() -> None:
    async def _run() -> None:
        db = _Db()
        service = AiService(db, api_key="")
        service._enabled = True
        service._model_map = {"summary": "openai:gpt-4o-mini", "campaign_prompt": "openai:gpt-4o-mini"}
        service._fallback_model_map = {}
        service._client = _FakeClient()

        await service.ask_general("q", "sys")
        kwargs = service._client.responses.create.await_args.kwargs
        assert kwargs["model"] == "gpt-4o-mini"
        assert service.status()["metrics"]["last_used_task"] == "summary"

    asyncio.run(_run())


def test_ask_for_task_uses_campaign_prompt_model() -> None:
    async def _run() -> None:
        db = _Db()
        service = AiService(db, api_key="")
        service._enabled = True
        service._model_map = {"summary": "openai:gpt-4o-mini", "campaign_prompt": "openai:gpt-4.1-mini"}
        service._fallback_model_map = {}
        service._client = _FakeClient()

        await service.ask_for_task("campaign_prompt", "q", "sys")
        kwargs = service._client.responses.create.await_args.kwargs
        assert kwargs["model"] == "gpt-4.1-mini"
        assert service.status()["metrics"]["last_used_task"] == "campaign_prompt"

    asyncio.run(_run())


def test_ask_for_task_supports_ollama_primary_model() -> None:
    async def _run() -> None:
        db = _Db()
        service = AiService(db, api_key="")
        service._enabled = True
        service._model_map = {"summary": "openai:gpt-4o-mini", "campaign_prompt": "ollama:qwen2.5:1.5b"}
        service._fallback_model_map = {}
        service._client = _FakeClient()
        service._ollama.generate_text = AsyncMock(return_value="ollama-ok")

        out = await service.ask_for_task("campaign_prompt", "q", "sys")

        assert out == "ollama-ok"
        service._ollama.generate_text.assert_awaited_once()
        assert service.status()["metrics"]["last_used_model"] == "ollama:qwen2.5:1.5b"

    asyncio.run(_run())


def test_ask_for_task_uses_fallback_model_when_primary_fails() -> None:
    async def _run() -> None:
        db = _Db()
        service = AiService(db, api_key="")
        service._enabled = True
        service._model_map = {"summary": "openai:gpt-4o-mini", "campaign_prompt": "openai:gpt-4.1-mini"}
        service._fallback_model_map = {"campaign_prompt": "ollama:qwen2.5:1.5b"}
        service._client = _FakeClient()
        service._client.responses.create = AsyncMock(side_effect=RuntimeError("boom"))
        service._ollama.generate_text = AsyncMock(return_value="fallback-ok")

        out = await service.ask_for_task("campaign_prompt", "q", "sys")

        assert out == "fallback-ok"
        service._ollama.generate_text.assert_awaited_once()
        assert service.status()["metrics"]["last_used_model"] == "ollama:qwen2.5:1.5b"

    asyncio.run(_run())


def test_ask_for_task_uses_campaign_editorial_model() -> None:
    async def _run() -> None:
        db = _Db()
        service = AiService(db, api_key="")
        service._enabled = True
        service._model_map = {"summary": "openai:gpt-4o-mini", "campaign_editorial": "ollama:qwen2.5:1.5b"}
        service._fallback_model_map = {}
        service._client = _FakeClient()
        service._ollama.generate_text = AsyncMock(return_value="editorial-ok")

        out = await service.ask_for_task("campaign_editorial", "q", "sys")

        assert out == "editorial-ok"
        service._ollama.generate_text.assert_awaited_once()
        assert service.status()["metrics"]["last_used_model"] == "ollama:qwen2.5:1.5b"

    asyncio.run(_run())
