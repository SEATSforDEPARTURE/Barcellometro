from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import text as sql_text
from sqlalchemy.engine import Engine
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
    def __init__(
        self,
        db_url: str,
        table_name: str = "ingest_events",
        engine: Engine | None = None,
    ) -> None:
        self.db_url = db_url
        self.table_name = table_name
        self._engine = engine
        self.db_path = self._resolve_sqlite_path(db_url, engine)
        self._enabled = self._engine is not None and self.db_path is not None
        self._emit_count = 0
        self._last_emit_at: datetime | None = None
        self._last_error: str | None = None
        self._disabled_logged = False
        self._lock = asyncio.Lock()

        if self._enabled:
            log.info("ingest: SQLite path=%s table=%s", self.db_path, self.table_name)
            self._ensure_table()
        elif engine is None:
            log.warning("ingest: db_engine mancante, service disabilitato (db_url=%s)", db_url)
        else:
            log.warning("ingest: DB non SQLite, service disabilitato (db_url=%s)", db_url)

    def _resolve_sqlite_path(self, db_url: str, engine: Engine | None) -> str | None:
        if engine is not None:
            if engine.url.get_backend_name() != "sqlite":
                return None
            if engine.url.database in (None, ""):
                return None
            return engine.url.database
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
        if self._engine is None:
            return
        create_sql = sql_text(
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
        with self._engine.begin() as conn:
            conn.execute(create_sql)

    async def emit(self, event: IngestEvent) -> bool:
        if not self._enabled:
            if not self._disabled_logged:
                log.warning("ingest: emit ignorato, service disabilitato (db_url=%s)", self.db_url)
                self._disabled_logged = True
            return False
        async with self._lock:
            return await asyncio.to_thread(self._insert_event, event)

    def _insert_event(self, event: IngestEvent) -> bool:
        try:
            row = event.to_row()
            if self._engine is None:
                return False
            insert_sql = sql_text(
                f"""
                INSERT OR IGNORE INTO {self.table_name}
                (event_id, source, event_type, guild_id, channel_id, author_id, content, created_at, metadata_json)
                VALUES (:event_id, :source, :event_type, :guild_id, :channel_id, :author_id, :content, :created_at, :metadata_json)
                """
            )
            with self._engine.begin() as conn:
                self._ensure_table()
                conn.execute(insert_sql, row)
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
