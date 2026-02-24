from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

SessionScope = Literal["general_llm", "channel_qna"]
SessionKey = tuple[int, int, int]


@dataclass
class QnaSession:
    scope: SessionScope
    history: list[dict[str, str]] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_used_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class QnaSessionStore:
    def __init__(self, *, ttl_minutes: int = 60) -> None:
        self._ttl = timedelta(minutes=max(1, int(ttl_minutes)))
        self._sessions: dict[SessionKey, QnaSession] = {}

    def get(self, key: SessionKey) -> QnaSession | None:
        self.purge_expired()
        session = self._sessions.get(key)
        if session is None:
            return None
        if datetime.now(timezone.utc) - session.last_used_at > self._ttl:
            self._sessions.pop(key, None)
            return None
        session.last_used_at = datetime.now(timezone.utc)
        return session

    def set(self, key: SessionKey, session: QnaSession) -> None:
        now = datetime.now(timezone.utc)
        if session.created_at.tzinfo is None:
            session.created_at = session.created_at.replace(tzinfo=timezone.utc)
        session.last_used_at = now
        self._sessions[key] = session

    def touch(self, key: SessionKey) -> None:
        session = self._sessions.get(key)
        if session is None:
            return
        session.last_used_at = datetime.now(timezone.utc)

    def purge_expired(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [k for k, v in self._sessions.items() if now - v.last_used_at > self._ttl]
        for key in expired:
            self._sessions.pop(key, None)
