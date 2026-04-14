from __future__ import annotations

import asyncio
from threading import Lock
from typing import Any

from app.services.translate.base import TranslationResult


class OpusMtTranslateService:
    MODEL_ID = "Helsinki-NLP/opus-mt-tc-big-en-it"

    _pipeline: Any = None
    _load_error: Exception | None = None
    _pipeline_lock = Lock()

    @classmethod
    def _get_pipeline(cls) -> Any:
        if cls._pipeline is not None:
            return cls._pipeline
        if cls._load_error is not None:
            raise RuntimeError("OPUS-MT pipeline unavailable") from cls._load_error
        with cls._pipeline_lock:
            if cls._pipeline is not None:
                return cls._pipeline
            try:
                from transformers import pipeline
            except Exception as exc:  # pragma: no cover - optional runtime dependency
                cls._load_error = exc
                raise RuntimeError("transformers dependency missing for OPUS-MT backend") from exc
            try:
                cls._pipeline = pipeline("translation", model=cls.MODEL_ID)
            except Exception as exc:  # pragma: no cover - depends on local runtime model availability
                cls._load_error = exc
                raise RuntimeError("unable to initialize OPUS-MT backend") from exc
            return cls._pipeline

    async def translate(
        self,
        text: str,
        target_lang: str,
        *,
        source_lang: str | None = None,
        backend: str | None = None,
    ) -> TranslationResult:
        normalized_source = (source_lang or "en").strip().lower()
        normalized_target = str(target_lang or "").strip().lower()
        _ = backend
        if normalized_source != "en" or normalized_target != "it":
            raise RuntimeError("OPUS-MT backend currently supports only en->it")

        def _run_translate() -> TranslationResult:
            model_pipeline = self._get_pipeline()
            outputs = model_pipeline(text)
            if not outputs:
                raise RuntimeError("OPUS-MT returned empty output")
            translated = str(outputs[0].get("translation_text") or "").strip()
            if not translated:
                raise RuntimeError("OPUS-MT returned blank translation")
            return TranslationResult(
                text=translated,
                source_lang="en",
                target_lang="it",
                backend="local",
                model="opus-mt-tc-big-en-it",
            )

        return await asyncio.to_thread(_run_translate)
