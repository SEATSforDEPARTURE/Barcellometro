from __future__ import annotations

from typing import Optional

from app.services.ai import AiService


class CommunityInsightsService:
    def __init__(self, ai_service: AiService | None = None) -> None:
        self._ai_service = ai_service

    async def get_next_message(self, guild_id: str) -> Optional[str]:
        _ = guild_id
        return None

    def status(self) -> dict[str, object]:
        return {
            "active": True,
            "state": "stub",
        }
