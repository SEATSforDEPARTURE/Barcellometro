from __future__ import annotations

import asyncio

import argostranslate.translate

from app.services.translate.base import TranslationResult


class ArgosTranslateService:
    async def translate(self, text: str, target_lang: str) -> TranslationResult:
        def _run() -> TranslationResult:
            installed_languages = argostranslate.translate.get_installed_languages()
            target = None
            for language in installed_languages:
                if language.code == target_lang:
                    target = language
                    break
            if target is None:
                raise RuntimeError("Target language not installed")
            source = installed_languages[0]
            translation = source.get_translation(target)
            if translation is None:
                raise RuntimeError("Translation pair not available")
            return TranslationResult(
                text=translation.translate(text),
                source_lang=source.code,
                target_lang=target_lang,
                backend="local",
                model="argos",
            )

        return await asyncio.to_thread(_run)
