from __future__ import annotations

import inspect
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.services.database import DatabaseService
from app.services.qna_session_store import QnaSession, SessionScope

logger = logging.getLogger(__name__)

QNA_FOLLOWUP_TTL_DAYS = 7


@dataclass
class PersistedQnaSession:
    guild_id: int
    channel_id: int
    user_id: int | None
    anchor_message_id: int
    scope: SessionScope
    session: QnaSession
    model_name: str | None = None


class QnaSessionsRepo:
    def __init__(self, database: DatabaseService, *, ttl_days: int = QNA_FOLLOWUP_TTL_DAYS) -> None:
        self._database = database
        self._ttl = timedelta(days=max(1, int(ttl_days)))

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    async def _safe_execute(self, conn, query: str, params: tuple[object, ...]) -> object | None:
        try:
            out = conn.execute(query, params)
        except Exception:
            return None
        if inspect.isawaitable(out):
            return await out
        return None

    async def _safe_commit(self, conn) -> None:
        try:
            out = conn.commit()
        except Exception:
            return
        if inspect.isawaitable(out):
            await out

    async def delete_expired_sessions(self) -> None:
        conn = self._database._conn
        if conn is None:
            return
        now_iso = self._now().isoformat()
        await self._safe_execute(conn, "DELETE FROM qna_followup_sessions WHERE expires_at <= ?", (now_iso,))
        await self._safe_commit(conn)

    async def save_session(
        self,
        *,
        anchor_message_id: int,
        guild_id: int,
        channel_id: int,
        user_id: int | None,
        scope: SessionScope,
        history: list[dict[str, str]],
        model_name: str | None,
        created_at: datetime | None = None,
    ) -> None:
        conn = self._database._conn
        if conn is None:
            return
        await self.delete_expired_sessions()
        now = self._now()
        created = created_at or now
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        expires_at = now + self._ttl
        history_json = json.dumps(history, ensure_ascii=False)
        await self._safe_execute(
            conn,
            """
            INSERT INTO qna_followup_sessions (
                anchor_message_id, guild_id, channel_id, user_id, scope, history_json, model_name, created_at, updated_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(anchor_message_id) DO UPDATE SET
                guild_id = excluded.guild_id,
                channel_id = excluded.channel_id,
                user_id = excluded.user_id,
                scope = excluded.scope,
                history_json = excluded.history_json,
                model_name = excluded.model_name,
                updated_at = excluded.updated_at,
                expires_at = excluded.expires_at
            """,
            (
                str(anchor_message_id),
                str(guild_id),
                str(channel_id),
                str(user_id) if user_id is not None else None,
                scope,
                history_json,
                model_name,
                created.isoformat(),
                now.isoformat(),
                expires_at.isoformat(),
            ),
        )
        await self._safe_commit(conn)

    async def get_session(self, anchor_message_id: int) -> PersistedQnaSession | None:
        conn = self._database._conn
        if conn is None:
            return None
        await self.delete_expired_sessions()
        now_iso = self._now().isoformat()
        cursor = await self._safe_execute(conn,
            """
            SELECT anchor_message_id, guild_id, channel_id, user_id, scope, history_json, model_name, created_at, updated_at
            FROM qna_followup_sessions
            WHERE anchor_message_id = ? AND expires_at > ?
            """,
            (str(anchor_message_id), now_iso),
        )
        if cursor is None:
            return None
        row = await cursor.fetchone()
        if row is None:
            return None

        try:
            history_raw = json.loads(row[5] or "[]")
        except json.JSONDecodeError:
            logger.warning("qna_followup_invalid_history anchor=%s", row[0])
            history_raw = []
        history: list[dict[str, str]] = []
        if isinstance(history_raw, list):
            for item in history_raw:
                if isinstance(item, dict):
                    role = str(item.get("role") or "").strip()
                    content = str(item.get("content") or "")
                    if role and content:
                        history.append({"role": role, "content": content})

        created_at = datetime.fromisoformat(str(row[7]))
        last_used_at = datetime.fromisoformat(str(row[8]))
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if last_used_at.tzinfo is None:
            last_used_at = last_used_at.replace(tzinfo=timezone.utc)

        user_id_value = int(row[3]) if row[3] is not None else None
        scope_value = str(row[4])
        if scope_value not in {"general_llm", "channel_qna"}:
            return None

        return PersistedQnaSession(
            guild_id=int(row[1]),
            channel_id=int(row[2]),
            user_id=user_id_value,
            anchor_message_id=int(row[0]),
            scope=scope_value,
            session=QnaSession(scope=scope_value, history=history, created_at=created_at, last_used_at=last_used_at),
            model_name=str(row[6]) if row[6] else None,
        )
