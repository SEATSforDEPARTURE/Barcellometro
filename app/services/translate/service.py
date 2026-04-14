from __future__ import annotations

from app.services.translate.ai_translate import AiTranslateService
from app.services.translate.argos import ArgosTranslateService
from app.services.translate.base import TranslationResult
from app.services.translate.opus_mt import OpusMtTranslateService


class TranslationService:
    def __init__(self, *, argos: ArgosTranslateService, ai: AiTranslateService | None = None, opus_mt: OpusMtTranslateService | None = None) -> None:
        self._argos = argos
        self._ai = ai
        self._opus_mt = opus_mt or OpusMtTranslateService()

    async def translate(
        self,
        text: str,
        target_lang: str,
        *,
        source_lang: str | None = None,
        backend: str | None = None,
    ) -> TranslationResult:
        selected_backend = (backend or "local").strip().lower()
        if selected_backend in {"opusmt", "opus", "opus-mt"}:
            return await self._opus_mt.translate(text, target_lang, source_lang=source_lang, backend=selected_backend)
        if selected_backend == "ai":
            if self._ai is None:
                raise RuntimeError("AI translation backend unavailable")
            return await self._ai.translate(text, target_lang, source_lang=source_lang, backend=selected_backend)
        return await self._argos.translate(text, target_lang, source_lang=source_lang, backend=selected_backend)
