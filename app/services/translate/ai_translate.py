from __future__ import annotations

from app.services.ai import AiService
from app.services.translate.base import TranslationResult


class AiTranslateService:
    def __init__(self, ai_service: AiService) -> None:
        self._ai_service = ai_service

    async def translate(
        self,
        text: str,
        target_lang: str,
        *,
        source_lang: str | None = None,
        backend: str | None = None,
    ) -> TranslationResult:
        _ = backend
        if not self._ai_service.is_enabled():
            raise RuntimeError("AI disabled")
        model_cfg = self._ai_service.get_model_config("translation")
        if model_cfg is None:
            raise RuntimeError("AI model not configured")
        output_text = await self._ai_service.ask_for_task(
            "translation",
            text,
            f"Translate the following text to {target_lang}. Return only the translation.",
        )
        if not output_text:
            raise RuntimeError("AI translation unavailable")
        return TranslationResult(
            text=output_text.strip(),
            source_lang=source_lang or "auto",
            target_lang=target_lang,
            backend="ai",
            model=self._ai_service.get_model_display_name("translation"),
        )
