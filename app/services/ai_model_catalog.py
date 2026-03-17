from __future__ import annotations

from dataclasses import dataclass

import httpx
from discord import app_commands


@dataclass(frozen=True)
class SuggestedModel:
    value: str
    label: str
    description: str
    provider: str
    task_tags: tuple[str, ...]
    source: str


def get_recommended_models() -> list[SuggestedModel]:
    return [
        SuggestedModel(
            value="openai:gpt-4o-mini",
            label="gpt-4o-mini",
            description="Economico e versatile per summary, QA e campagne prompt",
            provider="openai",
            task_tags=("summary", "server_summary", "audio_summary", "qa", "analysis", "translation", "campaign_prompt"),
            source="recommended_openai",
        ),
        SuggestedModel(
            value="openai:gpt-4o",
            label="gpt-4o",
            description="Qualità più alta per task complessi e output migliori",
            provider="openai",
            task_tags=("qa", "analysis", "campaign_prompt"),
            source="recommended_openai",
        ),
        SuggestedModel(
            value="openai:gpt-4o-transcribe",
            label="gpt-4o-transcribe",
            description="Trascrizione audio via OpenAI",
            provider="openai",
            task_tags=("transcription",),
            source="recommended_openai",
        ),
        SuggestedModel(
            value="openai:gpt-4.1-mini",
            label="gpt-4.1-mini",
            description="Alternativa veloce per task testuali, se disponibile nel progetto",
            provider="openai",
            task_tags=("summary", "server_summary", "qa", "analysis", "translation"),
            source="recommended_openai",
        ),
        SuggestedModel(
            value="ollama:qwen2.5:1.5b",
            label="qwen2.5:1.5b",
            description="Locale leggero, ottimo fallback per summary e campagne editoriali",
            provider="ollama",
            task_tags=("summary", "server_summary", "audio_summary", "translation", "campaign_editorial"),
            source="recommended_ollama",
        ),
        SuggestedModel(
            value="ollama:llama3.2:3b",
            label="llama3.2:3b",
            description="Locale più qualitativo per testi e campagne prompt",
            provider="ollama",
            task_tags=("summary", "qa", "analysis", "campaign_prompt", "campaign_editorial"),
            source="recommended_ollama",
        ),
        SuggestedModel(
            value="ollama:qwen2.5:3b",
            label="qwen2.5:3b",
            description="Locale bilanciato, migliore del 1.5b se la VPS regge",
            provider="ollama",
            task_tags=("summary", "server_summary", "qa", "analysis", "campaign_editorial"),
            source="recommended_ollama",
        ),
    ]


def _task_priority_values(task: str | None) -> list[str]:
    priorities: dict[str, list[str]] = {
        "summary": ["openai:gpt-4o-mini", "ollama:qwen2.5:1.5b", "ollama:llama3.2:3b"],
        "server_summary": ["openai:gpt-4o-mini", "ollama:qwen2.5:1.5b", "ollama:llama3.2:3b"],
        "audio_summary": ["openai:gpt-4o-mini", "ollama:qwen2.5:1.5b", "ollama:llama3.2:3b"],
        "campaign_editorial": ["ollama:qwen2.5:1.5b", "ollama:llama3.2:3b", "openai:gpt-4o-mini"],
        "campaign_prompt": ["openai:gpt-4o-mini", "openai:gpt-4o", "ollama:llama3.2:3b"],
        "transcription": ["openai:gpt-4o-transcribe", "openai:gpt-4o-mini", "ollama:qwen2.5:1.5b"],
        "translation": ["openai:gpt-4o-mini", "ollama:qwen2.5:1.5b", "openai:gpt-4.1-mini"],
        "qa": ["openai:gpt-4o-mini", "openai:gpt-4o", "ollama:llama3.2:3b"],
        "analysis": ["openai:gpt-4o-mini", "openai:gpt-4o", "ollama:llama3.2:3b"],
    }
    return priorities.get(task or "", ["openai:gpt-4o-mini", "ollama:qwen2.5:1.5b", "ollama:llama3.2:3b"])


async def list_installed_ollama_models(base_url: str = "http://localhost:11434") -> list[str]:
    urls = [f"{base_url}/api/tags", f"{base_url}/api/models"]
    for url in urls:
        try:
            async with httpx.AsyncClient(timeout=2.5) as client:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
        except Exception:
            continue

        models = payload.get("models", []) if isinstance(payload, dict) else []
        values: list[str] = []
        seen: set[str] = set()
        for item in models:
            if not isinstance(item, dict):
                continue
            raw_name = item.get("name") or item.get("model")
            if not raw_name or not isinstance(raw_name, str):
                continue
            normalized = f"ollama:{raw_name.strip()}"
            if normalized in seen:
                continue
            seen.add(normalized)
            values.append(normalized)
        return values
    return []


def _choice_name_for_model(model: SuggestedModel) -> str:
    text = f"{model.label} — {model.description}"
    if len(text) <= 100:
        return text
    return text[:99] + "…"


def _match_score(item: SuggestedModel, current: str) -> tuple[int, int]:
    if not current:
        return (1, 1)
    query = current.lower()
    value = item.value.lower()
    label = item.label.lower()
    if value == query or label == query:
        return (0, 0)
    if value.startswith(query) or label.startswith(query):
        return (0, 1)
    if query in value or query in label:
        return (1, 0)
    return (2, 0)


async def build_model_autocomplete_choices(task: str | None, current: str) -> list[app_commands.Choice[str]]:
    recommended = get_recommended_models()
    installed_values = await list_installed_ollama_models()

    installed_models = [
        SuggestedModel(
            value=value,
            label=value.removeprefix("ollama:"),
            description="Modello Ollama installato localmente",
            provider="ollama",
            task_tags=("summary", "server_summary", "audio_summary", "qa", "analysis", "transcription", "translation", "campaign_editorial", "campaign_prompt"),
            source="installed_ollama",
        )
        for value in installed_values
    ]

    all_models = recommended + installed_models
    deduped: dict[str, SuggestedModel] = {}
    for model in all_models:
        deduped.setdefault(model.value, model)

    query = (current or "").strip().lower()
    filtered = [
        model
        for model in deduped.values()
        if not query or query in model.value.lower() or query in model.label.lower()
    ]

    priorities = _task_priority_values(task)
    priority_index = {value: idx for idx, value in enumerate(priorities)}

    def sort_key(model: SuggestedModel) -> tuple[int, int, int, int, str]:
        score_group, score_inner = _match_score(model, query)
        task_bucket = 0 if model.value in priority_index else 1
        source_bucket = 0 if model.source.startswith("recommended") else 1
        priority_pos = priority_index.get(model.value, 99)
        return (score_group, score_inner, task_bucket, source_bucket, priority_pos, model.value)

    filtered.sort(key=sort_key)

    if not filtered:
        fallback_values = priorities[:3]
        fallback_map = {model.value: model for model in recommended}
        filtered = [fallback_map[value] for value in fallback_values if value in fallback_map]

    choices: list[app_commands.Choice[str]] = []
    for model in filtered[:25]:
        choices.append(app_commands.Choice(name=_choice_name_for_model(model), value=model.value))
    return choices
