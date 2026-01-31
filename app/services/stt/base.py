from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TranscriptResult:
    text: str
    language: str
    backend: str
    model: str


class SttService(Protocol):
    async def transcribe(self, audio_path: str) -> TranscriptResult: ...
