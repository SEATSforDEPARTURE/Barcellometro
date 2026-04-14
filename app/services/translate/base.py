from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TranslationResult:
    text: str
    source_lang: str
    target_lang: str
    backend: str
    model: str


class TranslateService(Protocol):
    async def translate(
        self,
        text: str,
        target_lang: str,
        *,
        source_lang: str | None = None,
        backend: str | None = None,
    ) -> TranslationResult: ...
