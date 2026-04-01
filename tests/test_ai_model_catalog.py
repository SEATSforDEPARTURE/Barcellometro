import asyncio
import sys
import types

if "httpx" not in sys.modules:
    httpx_stub = types.ModuleType("httpx")

    class _AsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *_args, **_kwargs):
            raise RuntimeError("unavailable")

    httpx_stub.AsyncClient = _AsyncClient
    sys.modules["httpx"] = httpx_stub

from app.services.ai_model_catalog import (
    build_model_autocomplete_choices,
    get_recommended_models,
    list_installed_ollama_models,
)


def test_recommended_models_contains_baseline_entries() -> None:
    values = {m.value for m in get_recommended_models()}
    assert "openai:gpt-4o-mini" in values
    assert "openai:gpt-4o" in values
    assert "openai:gpt-4o-transcribe" in values
    assert "ollama:qwen2.5:1.5b" in values


def test_list_installed_ollama_models_returns_empty_on_unavailable_service() -> None:
    models = asyncio.run(list_installed_ollama_models("http://127.0.0.1:1"))
    assert models == []


def test_build_model_autocomplete_choices_filters_by_task_and_caps_results() -> None:
    choices = asyncio.run(build_model_autocomplete_choices("transcription", "trans"))
    assert choices
    assert len(choices) <= 25
    assert choices[0].value == "openai:gpt-4o-transcribe"


def test_build_model_autocomplete_choices_deduplicates_values() -> None:
    choices = asyncio.run(build_model_autocomplete_choices("summary", "gpt-4o-mini"))
    values = [choice.value for choice in choices]
    assert len(values) == len(set(values))


def test_build_model_autocomplete_choices_supports_climate_analysis_task() -> None:
    choices = asyncio.run(build_model_autocomplete_choices("climate_analysis", ""))
    values = [choice.value for choice in choices]
    assert "ollama:llama3.2:3b" in values
    assert "openai:gpt-4o-mini" in values
    assert "openai:gpt-4o" in values
