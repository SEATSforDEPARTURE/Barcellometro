import asyncio
import sqlite3

from app.services.database import DatabaseService


def _sqlite_row(select_sql: str, params: tuple[object, ...] = ()) -> sqlite3.Row:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(select_sql, params).fetchone()
        assert row is not None
        return row
    finally:
        conn.close()


def run(coro):
    return asyncio.run(coro)


def test_fetch_aura_channel_users_with_history_before_handles_sqlite_rows_and_null_user_id() -> None:
    async def _scenario() -> None:
        db = DatabaseService(":memory:")
        valid_row = _sqlite_row("SELECT ? AS user_id", (123,))
        null_row = _sqlite_row("SELECT NULL AS user_id")
        missing_user_id_row = _sqlite_row("SELECT 1 AS other_col")
        
        async def _fake_fetchall(*_args, **_kwargs):
            return [valid_row, null_row, missing_user_id_row]

        db.fetchall = _fake_fetchall  # type: ignore[method-assign]

        users = await db.fetch_aura_channel_users_with_history_before("g1", "c1", "2026-04-02T00:00:00+00:00", ["123", "999"])
        assert users == {"123"}

    run(_scenario())


def test_has_aura_channel_history_before_handles_sqlite_row_without_get() -> None:
    async def _scenario() -> None:
        db = DatabaseService(":memory:")
        has_rows_row = _sqlite_row("SELECT 1 AS has_rows")
        missing_key_row = _sqlite_row("SELECT 1 AS other_col")

        async def _fake_fetchone_has_rows(*_args, **_kwargs):
            return has_rows_row

        db.fetchone = _fake_fetchone_has_rows  # type: ignore[method-assign]
        assert await db.has_aura_channel_history_before("g1", "c1", "2026-04-02T00:00:00+00:00") is True

        async def _fake_fetchone_missing_key(*_args, **_kwargs):
            return missing_key_row

        db.fetchone = _fake_fetchone_missing_key  # type: ignore[method-assign]
        assert await db.has_aura_channel_history_before("g1", "c1", "2026-04-02T00:00:00+00:00") is False

    run(_scenario())
