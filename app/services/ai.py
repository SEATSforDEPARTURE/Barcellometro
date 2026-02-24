from __future__ import annotations

import asyncio
from typing import Any, Optional

from openai import AsyncOpenAI

from app.services.database import DatabaseService


class AiService:
    def __init__(self, database: DatabaseService, api_key: str) -> None:
        self._database = database
        self._enabled = False
        self._api_key = api_key
        self._client: Optional[AsyncOpenAI] = None
        self._model_map: dict[str, str] = {}
        self._metrics = {
            "last_updated_ts": None,
        }

    async def load_settings(self) -> None:
        stored = await self._database.get_setting("ai_enabled")
        if stored is None:
            await self._database.set_setting("ai_enabled", "false")
            self._enabled = False
        else:
            self._enabled = stored.lower() in {"1", "true", "yes", "y"}
        self._model_map = await self._load_model_map()
        if self._api_key:
            self._client = AsyncOpenAI(api_key=self._api_key)

    async def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        await self._database.set_setting("ai_enabled", "true" if enabled else "false")

    def is_enabled(self) -> bool:
        return self._enabled

    def get_model(self, task: str) -> Optional[str]:
        return self._model_map.get(task)

    async def set_model(self, task: str, model: str) -> None:
        self._model_map[task] = model
        await self._database.set_setting(f"ai_model.{task}", model)

    def client(self) -> Optional[AsyncOpenAI]:
        return self._client

    def status(self) -> dict[str, Any]:
        return {
            "active": True,
            "state": "running" if self._enabled else "disabled",
            "metrics": {"models": dict(self._model_map), **self._metrics},
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
        if not self._enabled or self._client is None:
            return None
        model = self.get_model("summary") or "gpt-4o-mini"
        messages = self._build_general_messages(question, persona_system, history)
        response = await asyncio.wait_for(self._client.responses.create(model=model, input=messages), timeout=timeout_seconds)
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
        if not self._enabled or self._client is None:
            return None
        model = self.get_model("summary") or "gpt-4o-mini"
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
        text = str(getattr(response, "output_text", "") or "").strip()
        return text or None

    async def _load_model_map(self) -> dict[str, str]:
        return {
            "summary": (await self._database.get_setting("ai_model.summary")) or "gpt-4o-mini",
            "transcription": (await self._database.get_setting("ai_model.transcription")) or "gpt-4o-transcribe",
            "translation": (await self._database.get_setting("ai_model.translation")) or "gpt-4o-mini",
        }
