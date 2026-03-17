from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from openai import AsyncOpenAI

from app.services.ai_backends.ollama_backend import OllamaBackend
from app.services.ai_utils import parse_model_string
from app.services.database import DatabaseService


class AiService:
    SUPPORTED_MODEL_TASKS: tuple[str, ...] = (
        "summary",
        "server_summary",
        "audio_summary",
        "qa",
        "analysis",
        "transcription",
        "translation",
        "campaign_editorial",
        "campaign_prompt",
    )

    def __init__(self, database: DatabaseService, api_key: str) -> None:
        self._database = database
        self._enabled = False
        self._api_key = api_key
        self._client: Optional[AsyncOpenAI] = None
        self._model_map: dict[str, str] = {}
        self._fallback_model_map: dict[str, str] = {}
        self._ollama = OllamaBackend()
        self.logger = logging.getLogger(__name__)
        self._metrics = {
            "last_updated_ts": None,
            "last_test_task": None,
            "last_test_model": None,
            "last_test_ok": None,
            "last_test_error": None,
            "last_used_task": None,
            "last_used_model": None,
        }

    async def load_settings(self) -> None:
        stored = await self._database.get_setting("ai_enabled")
        if stored is None:
            await self._database.set_setting("ai_enabled", "false")
            self._enabled = False
        else:
            self._enabled = stored.lower() in {"1", "true", "yes", "y"}
        self._model_map = await self._load_model_map()
        self._fallback_model_map = await self._load_fallback_model_map()
        if self._api_key:
            self._client = AsyncOpenAI(api_key=self._api_key)

    async def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        await self._database.set_setting("ai_enabled", "true" if enabled else "false")

    def is_enabled(self) -> bool:
        return self._enabled

    def get_model_config(self, task: str) -> Optional[str]:
        return self._model_map.get(task)

    def get_model(self, task: str) -> Optional[str]:
        return self.get_openai_model(task)

    async def set_model(self, task: str, model: str) -> None:
        self._model_map[task] = model
        self._metrics["last_updated_ts"] = asyncio.get_running_loop().time()
        await self._database.set_setting(f"ai_model.{task}", model)

    def get_fallback_model(self, task: str) -> Optional[str]:
        return self._fallback_model_map.get(task)

    async def set_fallback_model(self, task: str, model: str) -> None:
        self._fallback_model_map[task] = model
        self._metrics["last_updated_ts"] = asyncio.get_running_loop().time()
        await self._database.set_setting(f"ai_fallback_model.{task}", model)

    def client(self) -> Optional[AsyncOpenAI]:
        return self._client

    def status(self) -> dict[str, Any]:
        return {
            "active": True,
            "state": "running" if self._enabled else "disabled",
            "models": dict(self._model_map),
            "fallback_models": dict(self._fallback_model_map),
            "metrics": dict(self._metrics),
        }


    def _build_general_messages(self, question: str, persona_system: str, history: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [{"role": "system", "content": persona_system}]
        if history:
            messages.extend(history)
        else:
            messages.append({"role": "user", "content": question})
        return messages

    async def ask_general(
        self,
        question: str,
        persona_system: str,
        history: list[dict[str, str]] | None = None,
        *,
        timeout_seconds: float = 25.0,
    ) -> str | None:
        return await self.ask_for_task("summary", question, persona_system, history, timeout_seconds=timeout_seconds)

    async def ask_for_task(
        self,
        task: str,
        question: str,
        persona_system: str,
        history: list[dict[str, str]] | None = None,
        *,
        timeout_seconds: float = 25.0,
    ) -> str | None:
        if not self._enabled or self._client is None:
            return None
        model = self.get_openai_model(task) or self.get_openai_model("summary") or "gpt-4o-mini"
        messages = self._build_general_messages(question, persona_system, history)
        response = await asyncio.wait_for(self._client.responses.create(model=model, input=messages), timeout=timeout_seconds)
        self._metrics["last_used_task"] = task
        self._metrics["last_used_model"] = model
        text = str(getattr(response, "output_text", "") or "").strip()
        return text or None

    async def ask_general_with_web(
        self,
        question: str,
        persona_system: str,
        history: list[dict[str, str]] | None = None,
        *,
        timeout_seconds: float = 35.0,
    ) -> str | None:
        return await self.ask_for_task_with_web("summary", question, persona_system, history, timeout_seconds=timeout_seconds)

    async def ask_for_task_with_web(
        self,
        task: str,
        question: str,
        persona_system: str,
        history: list[dict[str, str]] | None = None,
        *,
        timeout_seconds: float = 35.0,
    ) -> str | None:
        if not self._enabled or self._client is None:
            return None
        model = self.get_openai_model(task) or self.get_openai_model("summary") or "gpt-4o-mini"
        system_with_sources = (
            f"{persona_system}\n"
            "Quando usi il web, cita esplicitamente le fonti consultate con link o nome testata/sito."
        )
        messages = self._build_general_messages(question, system_with_sources, history)
        response = await asyncio.wait_for(
            self._client.responses.create(
                model=model,
                input=messages,
                tools=[{"type": "web_search"}],
            ),
            timeout=timeout_seconds,
        )
        self._metrics["last_used_task"] = task
        self._metrics["last_used_model"] = model
        text = str(getattr(response, "output_text", "") or "").strip()
        return text or None

    async def run_test(self, task: str, prompt: str, *, use_web: bool = False, timeout_seconds: float = 20.0) -> dict[str, Any]:
        model = self.get_openai_model(task) or self.get_openai_model("summary") or "gpt-4o-mini"
        output: str | None = None
        error: str | None = None
        ok = False
        try:
            if use_web:
                output = await self.ask_for_task_with_web(
                    task,
                    prompt,
                    "Sei un assistente di test del bot Discord.",
                    timeout_seconds=timeout_seconds,
                )
            else:
                output = await self.ask_for_task(
                    task,
                    prompt,
                    "Sei un assistente di test del bot Discord.",
                    timeout_seconds=timeout_seconds,
                )
            ok = bool(output)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)

        self._metrics["last_test_task"] = task
        self._metrics["last_test_model"] = model
        self._metrics["last_test_ok"] = ok
        self._metrics["last_test_error"] = error
        return {"ok": ok, "task": task, "model": model, "output": output, "error": error}

    def _get_model_for_task(self, task: str) -> str:
        return self._model_map.get(task) or "openai:gpt-4o-mini"

    def _get_fallback_model_for_task(self, task: str) -> Optional[str]:
        return self._fallback_model_map.get(task)

    def get_openai_model(self, task: str) -> Optional[str]:
        primary_model = self._get_model_for_task(task)
        provider, model = parse_model_string(primary_model)
        if provider == "openai":
            return model
        fallback_model = self._get_fallback_model_for_task(task)
        if not fallback_model:
            return None
        fallback_provider, fallback_name = parse_model_string(fallback_model)
        if fallback_provider == "openai":
            return fallback_name
        return None

    async def _generate_text_with_provider(self, model_str: str, system: str | None, prompt: str, timeout: float = 60.0) -> str:
        provider, model = parse_model_string(model_str)

        if provider == "openai":
            if self._client is None:
                raise RuntimeError("Client OpenAI non inizializzato")
            response = await asyncio.wait_for(
                self._client.responses.create(
                    model=model,
                    input=[
                        {"role": "system", "content": system or ""},
                        {"role": "user", "content": prompt},
                    ],
                ),
                timeout=timeout,
            )
            return response.output_text.strip()

        if provider == "ollama":
            return await self._ollama.generate_text(model, system or "", prompt, timeout)

        raise ValueError(f"Provider non supportato: {provider}")

    async def generate_text(self, task: str, prompt: str, system: str | None = None) -> str:
        primary_model = self._get_model_for_task(task)
        fallback_model = self._get_fallback_model_for_task(task)
        self.logger.info(f"[AI] task={task} model={primary_model}")

        try:
            return await self._generate_text_with_provider(primary_model, system, prompt)
        except Exception as exc:
            self.logger.warning(f"[AI] primary fallito ({primary_model}): {exc}")
            if not fallback_model:
                raise

            self.logger.info(f"[AI] task={task} model={fallback_model}")
            try:
                self.logger.info(f"[AI] fallback → {fallback_model}")
                return await self._generate_text_with_provider(fallback_model, system, prompt)
            except Exception as fallback_exc:
                self.logger.error(f"[AI] fallback fallito: {fallback_exc}")
                raise

    async def _load_model_map(self) -> dict[str, str]:
        defaults: dict[str, str] = {
            "summary": "openai:gpt-4o-mini",
            "server_summary": "openai:gpt-4o-mini",
            "audio_summary": "openai:gpt-4o-mini",
            "qa": "openai:gpt-4o-mini",
            "analysis": "openai:gpt-4o-mini",
            "transcription": "openai:gpt-4o-transcribe",
            "translation": "openai:gpt-4o-mini",
            "campaign_editorial": "openai:gpt-4o-mini",
            "campaign_prompt": "openai:gpt-4o-mini",
        }
        model_map: dict[str, str] = {}
        for task, default_model in defaults.items():
            key = f"ai_model.{task}"
            stored = await self._database.get_setting(key)
            if stored is None:
                await self._database.set_setting(key, default_model)
                model_map[task] = default_model
            else:
                model_map[task] = stored
        return model_map

    async def _load_fallback_model_map(self) -> dict[str, str]:
        defaults: dict[str, str] = {
            "summary": "ollama:qwen2.5:1.5b",
            "server_summary": "ollama:qwen2.5:1.5b",
            "audio_summary": "ollama:qwen2.5:1.5b",
            "qa": "ollama:qwen2.5:1.5b",
            "analysis": "ollama:qwen2.5:1.5b",
            "transcription": "openai:gpt-4o-transcribe",
            "translation": "openai:gpt-4o-mini",
            "campaign_editorial": "ollama:qwen2.5:1.5b",
            "campaign_prompt": "ollama:qwen2.5:1.5b",
        }
        fallback_map: dict[str, str] = {}
        for task, default_model in defaults.items():
            key = f"ai_fallback_model.{task}"
            stored = await self._database.get_setting(key)
            if stored is None:
                await self._database.set_setting(key, default_model)
                fallback_map[task] = default_model
            else:
                fallback_map[task] = stored
        return fallback_map
