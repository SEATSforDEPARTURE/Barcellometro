import asyncio
import json
import sys
import types
from unittest.mock import AsyncMock

if "aiosqlite" not in sys.modules:
    aiosqlite_stub = types.ModuleType("aiosqlite")
    aiosqlite_stub.Connection = object
    aiosqlite_stub.connect = object
    sys.modules["aiosqlite"] = aiosqlite_stub

from app.services.summary import DEFAULT_SUMMARY_CONFIG, SummaryService


class _Db:
    async def get_setting(self, _key: str):
        return None


class _Ai:
    def __init__(self, model_cfg: str, output: str) -> None:
        self._model_cfg = model_cfg
        self.ask_for_task = AsyncMock(return_value=output)

    def get_model(self, task: str):
        if task == "summary":
            return self._model_cfg
        return None

    def client(self):
        raise AssertionError("legacy OpenAI client should not be used")


def _minimal_messages() -> list[dict[str, object]]:
    return [
        {
            "ts": "2026-01-01T10:00:00+00:00",
            "author_id": "u1",
            "content": "ciao team",
            "meta": {},
            "message_id": "m1",
        }
    ]


def test_build_summary_with_ollama_without_openai_client() -> None:
    async def _run() -> None:
        ai_payload = json.dumps(
            {
                "themes": ["test"],
                "moments": [{"ts": "2026-01-01T10:00:00+00:00", "summary_text": "momento", "refs": []}],
                "quotes": [],
                "dynamics": [],
                "degrade_list": [],
                "invigorate_list": [],
                "advice": [],
            }
        )
        svc = SummaryService(database=_Db(), ai_service=_Ai("ollama:qwen2.5:1.5b", ai_payload))
        result = await svc.build_summary(
            guild_id="g",
            channel_id="c",
            start_ts="2026-01-01T00:00:00+00:00",
            end_ts="2026-01-01T23:59:59+00:00",
            tier="role1",
            include_names=False,
            ai_allowed=True,
            evidence_mode=False,
            voice_context=False,
            config=DEFAULT_SUMMARY_CONFIG,
            barcello_metrics={},
            max_message_ts="2026-01-01T10:00:00+00:00",
            messages=_minimal_messages(),
        )
        assert result.ai_status["provider"] == "ollama"
        assert result.ai_status["model"] == "ollama:qwen2.5:1.5b"

    asyncio.run(_run())


def test_build_period_description_works_without_openai_client() -> None:
    async def _run() -> None:
        ai = _Ai("ollama:qwen2.5:1.5b", "Oggi il barcello è stato stabile 🙂")
        svc = SummaryService(database=_Db(), ai_service=ai)
        out = await svc.build_period_description(
            tier="role1",
            period_prefix="Oggi",
            score=75,
            color="verde",
            metrics={},
            trend=None,
            ai_allowed=True,
            config=DEFAULT_SUMMARY_CONFIG,
        )
        assert out is not None
        ai.ask_for_task.assert_awaited_once()

    asyncio.run(_run())
