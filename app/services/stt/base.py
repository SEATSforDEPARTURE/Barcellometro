from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TranscriptResult:
    text: str
    language: str
    detected_language: str
    language_hint: str
    backend: str
    model: str


class SttService(Protocol):
    async def transcribe(self, audio_path: str, language_hint_override: str | None = None) -> TranscriptResult: ...
