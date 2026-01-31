from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Optional

from faster_whisper import WhisperModel

from app.services.database import DatabaseService
from app.services.stt.base import TranscriptResult


@dataclass(frozen=True)
class _SttConfig:
    model: str
    compute_type: str
    beam_size: int
    language_hint: str


class FasterWhisperSttService:
    def __init__(self, database: DatabaseService) -> None:
        self._database = database
        self._model: Optional[WhisperModel] = None
        self._config: Optional[_SttConfig] = None

    async def transcribe(self, audio_path: str) -> TranscriptResult:
        config = await self._load_config()
        model = await self._get_model(config)

        def _run() -> TranscriptResult:
            language = None if config.language_hint == "auto" else config.language_hint
            segments, info = model.transcribe(
                audio_path,
                beam_size=config.beam_size,
                language=language,
            )
            text = "".join(segment.text for segment in segments).strip()
            detected_lang = info.language if info and info.language else (language or "auto")
            return TranscriptResult(
                text=text,
                language=detected_lang,
                backend="local",
                model=config.model,
            )

        return await asyncio.to_thread(_run)

    async def _load_config(self) -> _SttConfig:
        model = (await self._database.get_setting("stt.local.model")) or os.getenv("STT_LOCAL_MODEL", "small")
        compute_type = (await self._database.get_setting("stt.local.compute_type")) or os.getenv("STT_LOCAL_COMPUTE_TYPE", "int8")
        beam_raw = (await self._database.get_setting("stt.local.beam_size")) or os.getenv("STT_LOCAL_BEAM_SIZE", "1")
        language_hint = (await self._database.get_setting("stt.local.language_hint")) or "auto"
        return _SttConfig(
            model=model,
            compute_type=compute_type,
            beam_size=int(beam_raw),
            language_hint=language_hint,
        )

    async def _get_model(self, config: _SttConfig) -> WhisperModel:
        if self._model and self._config == config:
            return self._model
        self._model = WhisperModel(config.model, compute_type=config.compute_type)
        self._config = config
        return self._model
