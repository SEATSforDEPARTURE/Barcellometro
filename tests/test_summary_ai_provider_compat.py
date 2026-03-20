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

from app.services.content_summary_service import DEFAULT_SUMMARY_CONFIG, SummaryService


class _Row:
    def __init__(self, data: dict[str, object]) -> None:
        self._data = data

    def __getitem__(self, key: str):
        return self._data[key]


class _Db:
    def __init__(self) -> None:
        self._rows: dict[str, _Row] = {}

    async def get_setting(self, _key: str):
        return None

    async def fetch_nearest_message_id_in_range(self, **_kwargs):
        return None

    async def message_exists_in_channel(self, *, channel_id: str, message_id: str) -> bool:
        _ = channel_id
        _ = message_id
        return True

    async def fetch_message_by_id(self, *, channel_id: str, message_id: str):
        _ = channel_id
        return self._rows.get(message_id)


class _Ai:
    def __init__(self, model_cfg: str, output: str, *, fallback_model_cfg: str | None = None, runtime_model_cfg: str | None = None) -> None:
        self._model_cfg = model_cfg
        self._fallback_model_cfg = fallback_model_cfg
        self._runtime_model_cfg = runtime_model_cfg or model_cfg
        self.ask_for_task = AsyncMock(return_value=output)

    def get_model(self, task: str):
        if task == "summary":
            return self._model_cfg
        return None

    def get_fallback_model(self, task: str):
        if task == "summary":
            return self._fallback_model_cfg
        return None

    def get_runtime_model(self, task: str):
        if task == "summary":
            return self._runtime_model_cfg
        return None

    def client(self):
        raise AssertionError("legacy OpenAI client should not be used")




class _AiRaises(_Ai):
    def __init__(self, model_cfg: str, exc: Exception, *, fallback_model_cfg: str | None = None, runtime_model_cfg: str | None = None) -> None:
        self._model_cfg = model_cfg
        self._fallback_model_cfg = fallback_model_cfg
        self._runtime_model_cfg = runtime_model_cfg or model_cfg
        self.ask_for_task = AsyncMock(side_effect=exc)


class _FakeRateLimitError(RuntimeError):
    pass

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
        assert result.ai_status["configured_model"] == "ollama:qwen2.5:1.5b"
        assert result.ai_status["configured_display_model"] == "qwen2.5"

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
        assert out == "Oggi il barcello è stato sano 🙂."
        ai.ask_for_task.assert_not_awaited()

    asyncio.run(_run())


def test_call_ai_ollama_uses_lite_schema_and_smaller_payload() -> None:
    async def _run() -> None:
        ai = _Ai("ollama:qwen2.5:7b", '{"themes":[],"moments":[],"advice":[]}')
        svc = SummaryService(database=_Db(), ai_service=ai)
        messages = [
            {
                "ts": f"2026-01-01T10:{idx:02d}:00+00:00",
                "author_id": "u1",
                "content": f"msg {idx}",
                "meta": {},
                "message_id": f"m{idx}",
            }
            for idx in range(60)
        ]

        await svc._call_ai(
            messages=messages,
            include_names=False,
            tier="role1",
            barcello_metrics={},
            config=DEFAULT_SUMMARY_CONFIG,
        )

        args = ai.ask_for_task.await_args.args
        system_prompt = args[2]
        payload = json.loads(args[1])
        assert "Struttura JSON minima richiesta" in system_prompt
        assert "quotes/dynamics/degrade_list/invigorate_list" in system_prompt
        assert "i=message_id" in system_prompt
        assert len(payload["messages"]) <= 40
        assert payload["messages"][0]["x"] == "msg 0"
        assert "content" not in payload["messages"][0]
        assert "meta" not in payload["messages"][0]

    asyncio.run(_run())


def test_call_ai_openai_keeps_full_schema() -> None:
    async def _run() -> None:
        ai = _Ai("openai:gpt-4o-mini", '{"themes":[],"moments":[],"advice":[]}')
        svc = SummaryService(database=_Db(), ai_service=ai)
        await svc._call_ai(
            messages=_minimal_messages(),
            include_names=False,
            tier="role1",
            barcello_metrics={},
            config=DEFAULT_SUMMARY_CONFIG,
        )
        system_prompt = ai.ask_for_task.await_args.args[2]
        assert "Struttura JSON: themes[], moments[], quotes[], dynamics[], degrade_list[], invigorate_list[], advice[]" in system_prompt

    asyncio.run(_run())


def test_ollama_summary_path_triggers_single_ai_inference() -> None:
    async def _run() -> None:
        ai_payload = json.dumps({"themes": ["x"], "moments": [], "quotes": [], "dynamics": [], "degrade_list": [], "invigorate_list": [], "advice": []})
        ai = _Ai("ollama:qwen2.5:7b", ai_payload)
        svc = SummaryService(database=_Db(), ai_service=ai)

        period = await svc.build_period_description(
            tier="role1",
            period_prefix="Oggi",
            score=70,
            color="verde",
            metrics={},
            trend=None,
            ai_allowed=True,
            config=DEFAULT_SUMMARY_CONFIG,
        )
        assert period == "Oggi il barcello è stato sano 🙂."

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
        assert result.ai_status["used_ai_output"] is True
        ai.ask_for_task.assert_awaited_once()

    asyncio.run(_run())


def test_build_summary_recovers_json_inside_fences_and_extra_text() -> None:
    async def _run() -> None:
        ai_payload = """Ecco il risultato:
```json
{
  "themes": ["test"],
  "moments": [{"ts": "2026-01-01T10:00:00+00:00", "summary_text": "momento", "refs": []}],
  "quotes": [],
  "dynamics": [],
  "degrade_list": [],
  "invigorate_list": [],
  "advice": []
}
```
Grazie!"""
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
        assert result.ai_status["reason"] == "ok"
        assert result.ai_status["called"] is True
        assert result.ai_status["display_model"] == "qwen2.5"
        assert result.ai_status["used_ai_output"] is True
        assert result.ai_status["used_model"] == "ollama:qwen2.5:1.5b"
        assert result.ai_status["used_display_model"] == "qwen2.5"

    asyncio.run(_run())


def test_build_summary_invalid_json_keeps_model_and_marks_called() -> None:
    async def _run() -> None:
        svc = SummaryService(database=_Db(), ai_service=_Ai("ollama:qwen2.5:1.5b", "risposta non json"))
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
        assert result.ai_status["reason"] == "invalid_json"
        assert result.ai_status["called"] is True
        assert result.ai_status["provider"] == "ollama"
        assert result.ai_status["model"] == "ollama:qwen2.5:1.5b"
        assert result.ai_status["display_model"] == "qwen2.5"
        assert result.ai_status["used_ai_output"] is False
        assert result.ai_status["used_model"] is None
        assert result.ai_status["used_display_model"] is None

    asyncio.run(_run())


def test_build_summary_exception_marks_ai_as_not_used() -> None:
    async def _run() -> None:
        svc = SummaryService(database=_Db(), ai_service=_AiRaises("ollama:qwen2.5:7b", RuntimeError("boom")))
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
        assert result.ai_status["reason"] == "exception:RuntimeError"
        assert result.ai_status["called"] is True
        assert result.ai_status["used_ai_output"] is False
        assert result.ai_status["used_model"] is None
        assert result.ai_status["used_display_model"] is None

    asyncio.run(_run())


def test_build_summary_rate_limit_keeps_local_fallback_and_single_call() -> None:
    async def _run() -> None:
        ai = _AiRaises("openai:gpt-4o-mini", _FakeRateLimitError("429 Too Many Requests"))
        svc = SummaryService(database=_Db(), ai_service=ai)
        period = await svc.build_period_description(
            tier="role1",
            period_prefix="Oggi",
            score=75,
            color="verde",
            metrics={},
            trend=None,
            ai_allowed=True,
            config=DEFAULT_SUMMARY_CONFIG,
        )
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
        assert period == "Oggi il barcello è stato sano 🙂."
        assert result.ai_status["reason"] == "exception:_FakeRateLimitError"
        assert result.ai_status["used_ai_output"] is False
        assert result.moments
        ai.ask_for_task.assert_awaited_once()

    asyncio.run(_run())


def test_call_ai_compacts_payload_but_keeps_relevant_rendering_inputs() -> None:
    async def _run() -> None:
        ai = _Ai(
            "openai:gpt-4o-mini",
            '{"themes":[],"moments":[],"quotes":[],"dynamics":[],"degrade_list":[],"invigorate_list":[],"advice":[]}',
        )
        svc = SummaryService(database=_Db(), ai_service=ai)
        very_long_text = " ".join(["contenuto"] * 120)
        messages = [
            {
                "ts": "2026-01-01T10:00:00+00:00",
                "author_id": "u1",
                "content": very_long_text,
                "meta": {"kind": "message", "in_call": False, "unused": "noise"},
                "message_id": "12345678901234567",
            },
            {
                "ts": "2026-01-01T10:01:00+00:00",
                "author_id": "u1",
                "content": very_long_text,
                "meta": {"kind": "message", "in_call": False},
                "message_id": "12345678901234568",
            },
        ]

        await svc._call_ai(
            messages=messages,
            include_names=False,
            tier="role1",
            barcello_metrics={
                "message_count": 2,
                "window_minutes": 60,
                "msg_per_min": 0.03,
                "burst_ratio": 0.7,
                "unused_metric": "x" * 200,
            },
            config=DEFAULT_SUMMARY_CONFIG,
            summary_context={"period_label": "oggi", "nonce": "abc", "unused": "x" * 200},
        )

        payload = json.loads(ai.ask_for_task.await_args.args[1])
        assert list(payload["metrics"].keys()) == ["message_count", "window_minutes", "msg_per_min", "burst_ratio"]
        assert payload["summary_context"] == {"period_label": "oggi", "nonce": "abc"}
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["i"] == "12345678901234567"
        assert len(payload["messages"][0]["x"]) < len(very_long_text)

    asyncio.run(_run())


def test_sanitize_ai_payload_accepts_row_without_get_for_ts_resolution() -> None:
    async def _run() -> None:
        db = _Db()
        db._rows["12345678901234567"] = _Row({"ts": "2026-01-01T10:00:00+00:00", "author_id": "u1", "content": "ciao"})
        svc = SummaryService(database=db, ai_service=None)
        payload = {
            "moments": [
                {
                    "summary_text": "momento valido",
                    "primary_ref": "12345678901234567",
                    "refs": [],
                    "message_ids": [],
                }
            ]
        }
        messages: list[dict[str, object]] = []
        await svc._sanitize_ai_payload(
            payload,
            messages,
            include_names=False,
            channel_id="c",
            start_ts="2026-01-01T00:00:00+00:00",
            end_ts="2026-01-01T23:59:59+00:00",
        )
        assert payload["moments"][0]["text"] == "momento valido"

    asyncio.run(_run())


def test_build_summary_ai_payload_with_refs_survives_row_post_sanitize() -> None:
    async def _run() -> None:
        db = _Db()
        db._rows["12345678901234567"] = _Row({"ts": "2026-01-01T10:00:00+00:00", "author_id": "u1", "content": "quote"})
        ai_payload = json.dumps(
            {
                "themes": ["test"],
                "moments": [{"summary_text": "momento", "primary_ref": "12345678901234567", "refs": [], "message_ids": []}],
                "quotes": [{"quote_text": "frase", "primary_ref": "12345678901234567", "refs": [], "message_ids": []}],
                "dynamics": [],
                "degrade_list": [],
                "invigorate_list": [],
                "advice": [],
            }
        )
        svc = SummaryService(database=db, ai_service=_Ai("ollama:qwen2.5:1.5b", ai_payload))
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
            messages=[
                {
                    "ts": "2026-01-01T10:00:00+00:00",
                    "author_id": "u1",
                    "content": "ciao team",
                    "meta": {},
                    "message_id": "12345678901234567",
                }
            ],
        )
        assert result.ai_status["reason"] == "ok"
        assert result.ai_status["used_ai_output"] is True
        assert result.moments and result.moments[0].ts == "2026-01-01T10:00:00+00:00"

    asyncio.run(_run())


def test_summary_accepts_json_inside_code_fence_from_ollama() -> None:
    async def _run() -> None:
        ai_payload = """```json
{
  "themes": ["test"],
  "moments": [{"ts": "2026-01-01T10:00:00+00:00", "summary_text": "momento", "primary_ref": "12345678901234567", "refs": []}],
  "advice": []
}
```"""
        db = _Db()
        db._rows["12345678901234567"] = _Row({"ts": "2026-01-01T10:00:00+00:00", "author_id": "u1", "content": "ciao"})
        svc = SummaryService(database=db, ai_service=_Ai("ollama:llama3.2:3b", ai_payload))
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
            messages=[{"ts": "2026-01-01T10:00:00+00:00", "author_id": "u1", "content": "ciao", "meta": {}, "message_id": "12345678901234567"}],
        )
        assert result.ai_status["used_ai_output"] is True
        assert result.ai_status["used_model"] == "ollama:llama3.2:3b"

    asyncio.run(_run())


def test_summary_extracts_json_when_model_wraps_text_around_it() -> None:
    async def _run() -> None:
        ai_payload = """Risultato finale:
{"themes":["test"],"moments":[{"ts":"2026-01-01T10:00:00+00:00","summary_text":"momento","primary_ref":"12345678901234567","refs":[]}],"advice":[]}
Grazie"""
        db = _Db()
        db._rows["12345678901234567"] = _Row({"ts": "2026-01-01T10:00:00+00:00", "author_id": "u1", "content": "ciao"})
        svc = SummaryService(database=db, ai_service=_Ai("ollama:llama3.2:3b", ai_payload))
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
            messages=[{"ts": "2026-01-01T10:00:00+00:00", "author_id": "u1", "content": "ciao", "meta": {}, "message_id": "12345678901234567"}],
        )
        assert result.ai_status["used_ai_output"] is True
        assert result.moments and result.moments[0].text == "momento"

    asyncio.run(_run())


def test_summary_uses_compact_schema_for_fallback_model() -> None:
    async def _run() -> None:
        ai = _Ai(
            "openai:gpt-4o-mini",
            '{"themes":[],"moments":[],"advice":[]}',
            fallback_model_cfg="ollama:llama3.2:3b",
            runtime_model_cfg="ollama:llama3.2:3b",
        )
        svc = SummaryService(database=_Db(), ai_service=ai)
        await svc._call_ai(
            messages=_minimal_messages(),
            include_names=False,
            tier="role1",
            barcello_metrics={},
            config=DEFAULT_SUMMARY_CONFIG,
        )
        kwargs = ai.ask_for_task.await_args.kwargs
        assert kwargs["fallback_persona_system"] is not None
        assert "Struttura JSON minima richiesta" in kwargs["fallback_persona_system"]

    asyncio.run(_run())


def test_summary_compact_schema_is_transformed_to_standard_render_output() -> None:
    async def _run() -> None:
        ai_payload = json.dumps({
            "themes": ["test"],
            "moments": [{"ts": "2026-01-01T10:00:00+00:00", "summary_text": "momento ai", "refs": []}],
            "advice": ["tenete il tono costruttivo"],
        })
        svc = SummaryService(database=_Db(), ai_service=_Ai("ollama:llama3.2:3b", ai_payload))
        result = await svc.build_summary(
            guild_id="g",
            channel_id="c",
            start_ts="2026-01-01T00:00:00+00:00",
            end_ts="2026-01-01T23:59:59+00:00",
            tier="role2",
            include_names=False,
            ai_allowed=True,
            evidence_mode=False,
            voice_context=False,
            config=DEFAULT_SUMMARY_CONFIG,
            barcello_metrics={},
            max_message_ts="2026-01-01T10:00:00+00:00",
            messages=_minimal_messages(),
        )
        assert result.ai_status["used_ai_output"] is True
        assert result.moments
        assert result.quotes == []
        assert result.advice == ["tenete il tono costruttivo"]

    asyncio.run(_run())


def test_riassunto_single_ai_call_still_preserved() -> None:
    async def _run() -> None:
        ai_payload = json.dumps({"themes": ["x"], "moments": [], "advice": []})
        ai = _Ai("ollama:llama3.2:3b", ai_payload)
        svc = SummaryService(database=_Db(), ai_service=ai)
        await svc.build_period_description(
            tier="role1",
            period_prefix="Oggi",
            score=70,
            color="verde",
            metrics={},
            trend=None,
            ai_allowed=True,
            config=DEFAULT_SUMMARY_CONFIG,
        )
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
        assert result.ai_status["used_ai_output"] is True
        ai.ask_for_task.assert_awaited_once()

    asyncio.run(_run())


def test_riassunto_fallback_ollama_output_is_used_when_valid() -> None:
    async def _run() -> None:
        ai = _Ai(
            "openai:gpt-4o-mini",
            '{"themes":["x"],"moments":[{"ts":"2026-01-01T10:00:00+00:00","summary_text":"momento fallback","refs":[]}],"advice":[]}',
            fallback_model_cfg="ollama:llama3.2:3b",
            runtime_model_cfg="ollama:llama3.2:3b",
        )
        svc = SummaryService(database=_Db(), ai_service=ai)
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
        assert result.ai_status["used_ai_output"] is True
        assert result.ai_status["used_model"] == "ollama:llama3.2:3b"
        assert result.ai_status["fallback"] is True

    asyncio.run(_run())


def test_invalid_json_still_falls_back_safely_if_unrecoverable() -> None:
    async def _run() -> None:
        svc = SummaryService(database=_Db(), ai_service=_Ai("ollama:llama3.2:3b", "non json {oops"))
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
        assert result.ai_status["used_ai_output"] is False
        assert result.ai_status["reason"] == "invalid_json"
        assert result.moments

    asyncio.run(_run())
