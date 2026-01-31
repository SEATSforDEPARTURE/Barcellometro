from __future__ import annotations

import os
from typing import Optional

from app.services.ai import AiService
from app.services.database import DatabaseService
from app.services.stt.base import TranscriptResult


class AiSttService:
    def __init__(self, database: DatabaseService, ai_service: AiService) -> None:
        self._database = database
        self._ai_service = ai_service

    async def transcribe(self, audio_path: str) -> TranscriptResult:
        if not self._ai_service.is_enabled():
            raise RuntimeError("AI disabled")
        client = self._ai_service.client()
        if client is None:
            raise RuntimeError("AI client not configured")
        model = self._ai_service.get_model("transcription")
        if model is None:
            raise RuntimeError("AI model not configured")
        language_hint = (await self._database.get_setting("stt.local.language_hint")) or "auto"
        language = None if language_hint == "auto" else language_hint

        with open(audio_path, "rb") as audio_file:
            response = await client.audio.transcriptions.create(
                model=model,
                file=audio_file,
                language=language,
            )

        detected_language = getattr(response, "language", None) or language or "auto"

        return TranscriptResult(
            text=response.text.strip(),
            language=detected_language,
            backend="ai",
            model=model,
        )
