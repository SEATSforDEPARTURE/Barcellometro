from __future__ import annotations

import logging

from app.services.ai import AiService
from app.services.database import DatabaseService
from app.services.stt.base import TranscriptResult

logger = logging.getLogger(__name__)


class AiSttService:
    def __init__(self, database: DatabaseService, ai_service: AiService) -> None:
        self._database = database
        self._ai_service = ai_service

    async def transcribe(self, audio_path: str, language_hint_override: str | None = None) -> TranscriptResult:
        if not self._ai_service.is_enabled():
            raise RuntimeError("AI disabled")
        client = self._ai_service.client()
        if client is None:
            raise RuntimeError("AI client not configured")
        model = self._ai_service.get_model("transcription")
        if model is None:
            raise RuntimeError("AI model not configured")
        configured_hint = ((await self._database.get_setting("stt.local.language_hint")) or "auto").strip().lower()
        effective_hint = configured_hint if language_hint_override is None else language_hint_override.strip().lower()

        request_kwargs = {"model": model}
        if effective_hint and effective_hint != "auto":
            request_kwargs["language"] = effective_hint

        with open(audio_path, "rb") as audio_file:
            response = await client.audio.transcriptions.create(file=audio_file, **request_kwargs)

        detected_language = (getattr(response, "language", None) or "unknown").strip().lower()
        logger.debug(
            "AI STT completed model=%s configured_hint=%s effective_hint=%s response_language=%s text_preview=%r",
            model,
            configured_hint,
            effective_hint,
            detected_language,
            (response.text or "")[:120],
        )

        return TranscriptResult(
            text=response.text.strip(),
            language=detected_language,
            detected_language=detected_language,
            language_hint=effective_hint or "auto",
            backend="ai",
            model=model,
        )
