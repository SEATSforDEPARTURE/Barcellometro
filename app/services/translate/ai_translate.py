from __future__ import annotations

from app.services.ai import AiService
from app.services.translate.base import TranslationResult


class AiTranslateService:
    def __init__(self, ai_service: AiService) -> None:
        self._ai_service = ai_service

    async def translate(self, text: str, target_lang: str) -> TranslationResult:
        if not self._ai_service.is_enabled():
            raise RuntimeError("AI disabled")
        client = self._ai_service.client()
        if client is None:
            raise RuntimeError("AI client not configured")
        model = self._ai_service.get_model("translation")
        if model is None:
            raise RuntimeError("AI model not configured")
        response = await client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": f"Translate the following text to {target_lang}. Return only the translation.",
                },
                {"role": "user", "content": text},
            ],
        )
        output_text = response.output_text.strip()
        return TranslationResult(
            text=output_text,
            source_lang="auto",
            target_lang=target_lang,
            backend="ai",
            model=model,
        )
