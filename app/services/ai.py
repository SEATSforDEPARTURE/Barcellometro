from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from openai import AsyncOpenAI

from app.services.ai_backends.ollama_backend import OllamaBackend
from app.services.ai_utils import parse_model_string
from app.services.database import DatabaseService


class AiService:
    OLLAMA_SLOW_TASKS: frozenset[str] = frozenset({"summary", "server_summary", "campaign_editorial"})
    OLLAMA_SLOW_TASK_TIMEOUT_SECONDS: float = 90.0
    OLLAMA_SUMMARY_TIMEOUT_SECONDS: float = 150.0
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
        """
        Restituisce la stringa completa configurata nel DB:
        es: 'openai:gpt-4o-mini' oppure 'ollama:qwen2.5:1.5b'
        """
        return self._model_map.get(task)

    def get_runtime_model(self, task: str) -> Optional[str]:
        return self.get_model_config(task)

    def get_model(self, task: str) -> Optional[str]:
        return self.get_model_config(task)

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

    async def _run_model(self, provider: str, model: str, system: str, prompt: str, timeout_seconds: float) -> Any:
        if provider == "openai":
            if self._client is None:
                raise RuntimeError("Client OpenAI non inizializzato")
            return await asyncio.wait_for(
                self._client.responses.create(
                    model=model,
                    input=[
                        {"role": "system", "content": system or ""},
                        {"role": "user", "content": prompt},
                    ],
                ),
                timeout=timeout_seconds,
            )
        if provider == "ollama":
            return await self._ollama.generate_text(model, system, prompt, timeout_seconds)
        raise RuntimeError(f"Provider non supportato: {provider}")

    @staticmethod
    def _extract_text(result: Any) -> str:
        if isinstance(result, str):
            return result.strip()
        return str(getattr(result, "output_text", "") or "").strip()

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
        if not self._enabled:
            return None
        model_cfg = self.get_model_config(task)
        if not model_cfg:
            model_cfg = self.get_model_config("summary") or "openai:gpt-4o-mini"

        provider, model = parse_model_string(model_cfg)
        effective_timeout = self._resolve_timeout(task, provider, timeout_seconds)
        self.logger.info("[AI] task=%s provider=%s timeout=%.1fs", task, provider, effective_timeout)
        system = persona_system
        prompt = question if not history else history[-1].get("content", question)

        try:
            self.logger.info("[AI] task=%s provider=%s model=%s", task, provider, model)
            result = await self._run_model(provider, model, system, prompt, effective_timeout)
            self._metrics["last_used_task"] = task
            self._metrics["last_used_model"] = model_cfg
            text = self._extract_text(result)
            return text or None
        except Exception as exc:
            fallback_cfg = self.get_fallback_model(task)
            if not fallback_cfg:
                raise
            provider_fb, model_fb = parse_model_string(fallback_cfg)
            if provider_fb == provider and model_fb == model:
                self.logger.warning(
                    "[AI] task=%s primary=%s:%s fallback=%s:%s fallback_skipped=same_provider_model error=%s",
                    task,
                    provider,
                    model,
                    provider_fb,
                    model_fb,
                    exc.__class__.__name__,
                )
                raise
            fallback_timeout = self._resolve_timeout(task, provider_fb, timeout_seconds)
            fallback_note = ""
            if task == "summary" and provider == "ollama" and provider_fb == "ollama":
                fallback_note = " same_backend_lower_capacity_reliability=low"
            self.logger.warning(
                "[AI] task=%s primary=%s:%s failed=%s fallback=%s:%s timeout=%.1fs%s",
                task,
                provider,
                model,
                exc.__class__.__name__,
                provider_fb,
                model_fb,
                fallback_timeout,
                fallback_note,
            )
            self.logger.info("[AI] task=%s provider=%s model=%s", task, provider_fb, model_fb)
            result = await self._run_model(provider_fb, model_fb, system, prompt, fallback_timeout)
            self._metrics["last_used_task"] = task
            self._metrics["last_used_model"] = fallback_cfg
            text = self._extract_text(result)
            return text or None

    def _resolve_timeout(self, task: str, provider: str, requested_timeout: float) -> float:
        if provider == "ollama" and task == "summary":
            return max(requested_timeout, self.OLLAMA_SUMMARY_TIMEOUT_SECONDS)
        if provider == "ollama" and task in self.OLLAMA_SLOW_TASKS:
            return max(requested_timeout, self.OLLAMA_SLOW_TASK_TIMEOUT_SECONDS)
        return requested_timeout

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
        system_with_sources = (
            f"{persona_system}\n"
            "Quando usi il web, cita esplicitamente le fonti consultate con link o nome testata/sito."
        )
        return await self.ask_for_task(task, question, system_with_sources, history, timeout_seconds=timeout_seconds)

    async def run_test(self, task: str, prompt: str, *, use_web: bool = False, timeout_seconds: float = 20.0) -> dict[str, Any]:
        model = self.get_model_config(task) or self.get_model_config("summary") or "openai:gpt-4o-mini"
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

    def get_model_display_name(self, task: str) -> str:
        model_cfg = self._metrics.get("last_used_model") if self._metrics.get("last_used_task") == task else None
        if not model_cfg:
            model_cfg = self.get_model_config(task) or self.get_model_config("summary") or ""
        if not model_cfg:
            return "unknown"
        provider, model = parse_model_string(str(model_cfg))
        if provider == "ollama":
            return model.split(":")[0]
        return model

    async def generate_text(self, task: str, prompt: str, system: str | None = None) -> str:
        text = await self.ask_for_task(task, prompt, system or "")
        if text is None:
            raise RuntimeError("AI output vuoto")
        return text

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
