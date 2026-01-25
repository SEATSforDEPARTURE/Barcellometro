from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.engine.url import make_url

log = logging.getLogger("barcellometro.service.ingest")


@dataclass(slots=True)
class IngestEvent:
    event_id: str
    source: str
    event_type: str
    guild_id: str
    channel_id: str
    author_id: str
    content: str
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, str]:
        return {
            "event_id": self.event_id,
            "source": self.source,
            "event_type": self.event_type,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "author_id": self.author_id,
            "content": self.content,
            "created_at": self.created_at.isoformat(),
            "metadata_json": json.dumps(self.metadata, ensure_ascii=False),
        }


class IngestService:
    def __init__(self, db_url: str, table_name: str = "ingest_events") -> None:
        self.db_url = db_url
        self.table_name = table_name
        self.db_path = self._resolve_sqlite_path(db_url)
        self._enabled = self.db_path is not None
        self._emit_count = 0
        self._last_emit_at: datetime | None = None
        self._last_error: str | None = None
        self._lock = asyncio.Lock()

        if self._enabled:
            log.info("ingest: SQLite path=%s table=%s", self.db_path, self.table_name)
            self._ensure_table()
        else:
            log.warning("ingest: DB non SQLite, service disabilitato (db_url=%s)", db_url)

    def _resolve_sqlite_path(self, db_url: str) -> str | None:
        try:
            url = make_url(db_url)
        except Exception:
            log.exception("ingest: URL DB non valida")
            return None
        if url.get_backend_name() != "sqlite":
            return None
        if url.database in (None, ""):
            return None
        return url.database

    def _ensure_table(self) -> None:
        if not self._enabled:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE,
                    source TEXT,
                    event_type TEXT,
                    guild_id TEXT,
                    channel_id TEXT,
                    author_id TEXT,
                    content TEXT,
                    created_at TEXT,
                    metadata_json TEXT
                )
                """
            )
            conn.commit()

    async def emit(self, event: IngestEvent) -> bool:
        if not self._enabled:
            return False
        async with self._lock:
            return await asyncio.to_thread(self._insert_event, event)

    def _insert_event(self, event: IngestEvent) -> bool:
        try:
            row = event.to_row()
            with sqlite3.connect(self.db_path) as conn:
                self._ensure_table()
                conn.execute(
                    f"""
                    INSERT OR IGNORE INTO {self.table_name}
                    (event_id, source, event_type, guild_id, channel_id, author_id, content, created_at, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["event_id"],
                        row["source"],
                        row["event_type"],
                        row["guild_id"],
                        row["channel_id"],
                        row["author_id"],
                        row["content"],
                        row["created_at"],
                        row["metadata_json"],
                    ),
                )
                conn.commit()
            self._emit_count += 1
            self._last_emit_at = event.created_at
            if self._emit_count % 100 == 0:
                log.info("ingest: %s eventi salvati", self._emit_count)
            else:
                log.debug("ingest: evento salvato (id=%s)", event.event_id)
            return True
        except Exception as exc:
            self._last_error = str(exc)
            log.exception("ingest: errore inserimento evento")
            return False

    def stats(self) -> dict[str, str | int | None]:
        return {
            "count": self._emit_count,
            "last_emit_at": self._last_emit_at.isoformat() if self._last_emit_at else None,
            "last_error": self._last_error,
        }
