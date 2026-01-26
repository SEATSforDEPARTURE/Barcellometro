from __future__ import annotations

import json
import logging
from typing import Any, Optional

import aiosqlite

logger = logging.getLogger(__name__)


class DatabaseService:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA foreign_keys=ON;")
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    async def initialize_schema(self) -> None:
        assert self._conn is not None
        await self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT,
                global_name TEXT,
                display_name TEXT,
                avatar_url TEXT,
                is_bot INTEGER,
                first_seen_ts TEXT,
                last_seen_ts TEXT,
                message_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS guild_memberships (
                guild_id TEXT,
                user_id TEXT,
                nickname TEXT,
                joined_at TEXT,
                last_seen_ts TEXT,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS channels (
                channel_id TEXT PRIMARY KEY,
                guild_id TEXT,
                name TEXT,
                enabled INTEGER DEFAULT 0,
                type TEXT,
                category_id TEXT,
                is_nsfw INTEGER,
                slowmode_delay INTEGER
            );

            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                guild_id TEXT,
                channel_id TEXT,
                author_id TEXT,
                ts TEXT,
                edited_ts TEXT,
                content TEXT,
                is_deleted INTEGER DEFAULT 0,
                reply_to_message_id TEXT,
                mentions_json TEXT,
                attachments_json TEXT,
                embeds_json TEXT
            );

            CREATE TABLE IF NOT EXISTS reactions (
                message_id TEXT,
                user_id TEXT,
                emoji TEXT,
                ts TEXT
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT,
                event_type TEXT,
                platform TEXT,
                guild_id TEXT,
                channel_id TEXT,
                actor_id TEXT,
                target_id TEXT,
                meta_json TEXT
            );
            """
        )
        await self._conn.commit()
        logger.info("Database schema initialized")

    async def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        assert self._conn is not None
        await self._conn.execute(query, params)
        await self._conn.commit()

    async def fetchone(self, query: str, params: tuple[Any, ...] = ()) -> Optional[aiosqlite.Row]:
        assert self._conn is not None
        self._conn.row_factory = aiosqlite.Row
        async with self._conn.execute(query, params) as cursor:
            return await cursor.fetchone()

    async def fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[aiosqlite.Row]:
        assert self._conn is not None
        self._conn.row_factory = aiosqlite.Row
        async with self._conn.execute(query, params) as cursor:
            return await cursor.fetchall()

    async def get_setting(self, key: str) -> Optional[str]:
        row = await self.fetchone("SELECT value FROM settings WHERE key = ?", (key,))
        if row:
            return row["value"]
        return None

    async def set_setting(self, key: str, value: str) -> None:
        await self.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    async def upsert_channel(self, channel_id: str, guild_id: str, name: str, enabled: int, channel_type: str, category_id: Optional[str], is_nsfw: int, slowmode_delay: int) -> None:
        await self.execute(
            """
            INSERT INTO channels (channel_id, guild_id, name, enabled, type, category_id, is_nsfw, slowmode_delay)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                name = excluded.name,
                enabled = excluded.enabled,
                type = excluded.type,
                category_id = excluded.category_id,
                is_nsfw = excluded.is_nsfw,
                slowmode_delay = excluded.slowmode_delay
            """,
            (channel_id, guild_id, name, enabled, channel_type, category_id, is_nsfw, slowmode_delay),
        )

    async def set_channel_enabled(self, channel_id: str, enabled: int) -> None:
        await self.execute("UPDATE channels SET enabled = ? WHERE channel_id = ?", (enabled, channel_id))

    async def is_channel_enabled(self, channel_id: str) -> bool:
        row = await self.fetchone("SELECT enabled FROM channels WHERE channel_id = ?", (channel_id,))
        if row is None:
            return False
        return bool(row["enabled"])

    async def count_enabled_channels(self) -> int:
        row = await self.fetchone("SELECT COUNT(*) as count FROM channels WHERE enabled = 1")
        return int(row["count"]) if row else 0

    async def fetch_enabled_channels(self) -> list[aiosqlite.Row]:
        return await self.fetchall(
            "SELECT channel_id, guild_id, name, type FROM channels WHERE enabled = 1"
        )

    async def count_table(self, table_name: str) -> int:
        row = await self.fetchone(f"SELECT COUNT(*) as count FROM {table_name}")
        return int(row["count"]) if row else 0

    async def latest_event_ts(self) -> Optional[str]:
        row = await self.fetchone("SELECT ts FROM events ORDER BY ts DESC LIMIT 1")
        return row["ts"] if row else None

    async def upsert_user(self, user_id: str, username: str, global_name: Optional[str], display_name: str, avatar_url: Optional[str], is_bot: bool, ts: str, increment_message: bool) -> None:
        await self.execute(
            """
            INSERT INTO users (user_id, username, global_name, display_name, avatar_url, is_bot, first_seen_ts, last_seen_ts, message_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                global_name = excluded.global_name,
                display_name = excluded.display_name,
                avatar_url = excluded.avatar_url,
                is_bot = excluded.is_bot,
                last_seen_ts = excluded.last_seen_ts,
                message_count = users.message_count + ?
            """,
            (
                user_id,
                username,
                global_name,
                display_name,
                avatar_url,
                int(is_bot),
                ts,
                ts,
                1 if increment_message else 0,
                1 if increment_message else 0,
            ),
        )

    async def upsert_guild_membership(self, guild_id: str, user_id: str, nickname: Optional[str], joined_at: Optional[str], last_seen_ts: str) -> None:
        await self.execute(
            """
            INSERT INTO guild_memberships (guild_id, user_id, nickname, joined_at, last_seen_ts)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                nickname = excluded.nickname,
                joined_at = COALESCE(guild_memberships.joined_at, excluded.joined_at),
                last_seen_ts = excluded.last_seen_ts
            """,
            (guild_id, user_id, nickname, joined_at, last_seen_ts),
        )

    async def insert_message(self, message_id: str, guild_id: str, channel_id: str, author_id: str, ts: str, content: Optional[str], reply_to_message_id: Optional[str], mentions: list[str], attachments: list[dict[str, Any]], embeds: list[dict[str, Any]]) -> None:
        await self.execute(
            """
            INSERT INTO messages (message_id, guild_id, channel_id, author_id, ts, content, reply_to_message_id, mentions_json, attachments_json, embeds_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                content = excluded.content,
                reply_to_message_id = excluded.reply_to_message_id,
                mentions_json = excluded.mentions_json,
                attachments_json = excluded.attachments_json,
                embeds_json = excluded.embeds_json
            """,
            (
                message_id,
                guild_id,
                channel_id,
                author_id,
                ts,
                content,
                reply_to_message_id,
                json.dumps(mentions),
                json.dumps(attachments),
                json.dumps(embeds),
            ),
        )

    async def update_message_edit(self, message_id: str, edited_ts: str, content: Optional[str]) -> None:
        await self.execute(
            "UPDATE messages SET edited_ts = ?, content = ? WHERE message_id = ?",
            (edited_ts, content, message_id),
        )

    async def mark_message_deleted(self, message_id: str) -> None:
        await self.execute("UPDATE messages SET is_deleted = 1 WHERE message_id = ?", (message_id,))

    async def insert_reaction(self, message_id: str, user_id: str, emoji: str, ts: str) -> None:
        await self.execute(
            "INSERT INTO reactions (message_id, user_id, emoji, ts) VALUES (?, ?, ?, ?)",
            (message_id, user_id, emoji, ts),
        )

    async def delete_reaction(self, message_id: str, user_id: str, emoji: str) -> None:
        await self.execute(
            "DELETE FROM reactions WHERE message_id = ? AND user_id = ? AND emoji = ?",
            (message_id, user_id, emoji),
        )

    async def insert_event(self, ts: str, event_type: str, platform: str, guild_id: Optional[str], channel_id: Optional[str], actor_id: Optional[str], target_id: Optional[str], meta: dict[str, Any]) -> None:
        await self.execute(
            "INSERT INTO events (ts, event_type, platform, guild_id, channel_id, actor_id, target_id, meta_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, event_type, platform, guild_id, channel_id, actor_id, target_id, json.dumps(meta)),
        )

    async def prune_messages(self, cutoff_ts: str) -> int:
        assert self._conn is not None
        cursor = await self._conn.execute("DELETE FROM messages WHERE ts < ?", (cutoff_ts,))
        await self._conn.commit()
        return cursor.rowcount

    async def prune_events(self, cutoff_ts: str) -> int:
        assert self._conn is not None
        cursor = await self._conn.execute("DELETE FROM events WHERE ts < ?", (cutoff_ts,))
        await self._conn.commit()
        return cursor.rowcount
