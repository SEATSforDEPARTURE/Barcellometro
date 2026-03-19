from __future__ import annotations

import sqlite3
import sys
import types
from typing import Any


class CursorWrapper:
    def __init__(self, cursor: sqlite3.Cursor, row_factory: Any) -> None:
        self._cursor = cursor
        self._row_factory = row_factory

    @property
    def lastrowid(self) -> int | None:
        return self._cursor.lastrowid

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    async def __aenter__(self) -> "CursorWrapper":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._cursor.close()

    def _convert(self, row: Any) -> Any:
        if row is None or self._row_factory is None:
            return row
        return self._row_factory(self._cursor, row)

    async def fetchone(self) -> Any:
        return self._convert(self._cursor.fetchone())

    async def fetchall(self) -> list[Any]:
        return [self._convert(row) for row in self._cursor.fetchall()]


class ExecuteResult:
    def __init__(self, cursor_wrapper: CursorWrapper) -> None:
        self._cursor_wrapper = cursor_wrapper

    def __await__(self):
        async def _coro() -> CursorWrapper:
            return self._cursor_wrapper

        return _coro().__await__()

    async def __aenter__(self) -> CursorWrapper:
        return await self._cursor_wrapper.__aenter__()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._cursor_wrapper.__aexit__(exc_type, exc, tb)


class ConnectionWrapper:
    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path)
        self.row_factory = None

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> ExecuteResult:
        return ExecuteResult(CursorWrapper(self._conn.execute(query, params), self.row_factory))

    async def executescript(self, script: str) -> None:
        self._conn.executescript(script)

    async def commit(self) -> None:
        self._conn.commit()

    async def close(self) -> None:
        self._conn.close()


async def _connect(path: str) -> ConnectionWrapper:
    return ConnectionWrapper(path)


def ensure_sqlite_stub() -> None:
    existing = sys.modules.get("aiosqlite")
    if existing is not None and callable(getattr(existing, "connect", None)):
        return
    sys.modules["aiosqlite"] = types.SimpleNamespace(
        connect=_connect,
        Row=sqlite3.Row,
        Connection=ConnectionWrapper,
        IntegrityError=sqlite3.IntegrityError,
    )
