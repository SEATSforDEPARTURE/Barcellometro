from __future__ import annotations

import json
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any, Optional

import aiosqlite
from zoneinfo import ZoneInfo

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

            CREATE TABLE IF NOT EXISTS voice_sessions (
                voice_session_id TEXT PRIMARY KEY,
                guild_id TEXT,
                voice_channel_id TEXT,
                started_ts TEXT,
                ended_ts TEXT NULL,
                meta_json TEXT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_voice_sessions_channel
            ON voice_sessions (guild_id, voice_channel_id, started_ts);

            CREATE TABLE IF NOT EXISTS role_policies (
                guild_id TEXT,
                role_id TEXT,
                command TEXT,
                usage_limit INTEGER,
                cooldown_seconds INTEGER,
                PRIMARY KEY (guild_id, role_id, command)
            );

            CREATE TABLE IF NOT EXISTS user_policies (
                guild_id TEXT,
                user_id TEXT,
                command TEXT,
                usage_limit INTEGER,
                cooldown_seconds INTEGER,
                PRIMARY KEY (guild_id, user_id, command)
            );

            CREATE TABLE IF NOT EXISTS usage_counters (
                guild_id TEXT,
                user_id TEXT,
                command TEXT,
                window_date TEXT,
                used_count INTEGER,
                last_used_ts TEXT,
                PRIMARY KEY (guild_id, user_id, command, window_date)
            );

            CREATE TABLE IF NOT EXISTS barcello_snapshots (
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                window_minutes INTEGER NOT NULL,
                window_end_ts TEXT NOT NULL,
                score INTEGER NOT NULL,
                reasons_json TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                computed_ts TEXT NOT NULL,
                PRIMARY KEY (guild_id, channel_id, window_minutes, window_end_ts)
            );

            CREATE TABLE IF NOT EXISTS barcello_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                rater_user_id TEXT NOT NULL,
                verdict TEXT NOT NULL CHECK(verdict IN ('accurate', 'inaccurate')),
                reason TEXT NULL,
                delta_target INTEGER NULL,
                score_pred INTEGER NOT NULL,
                profile TEXT NULL
            );

            CREATE TABLE IF NOT EXISTS message_channels (
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, channel_id)
            );

            CREATE TABLE IF NOT EXISTS message_campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'CUSTOM',
                name TEXT NULL,
                text TEXT NULL,
                text_green TEXT NULL,
                text_yellow TEXT NULL,
                text_red TEXT NULL,
                text_black TEXT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                start_time_local TEXT NOT NULL,
                interval_minutes INTEGER NOT NULL,
                jitter_seconds INTEGER NOT NULL DEFAULT 0,
                only_if_idle_minutes INTEGER NOT NULL DEFAULT 0,
                mood_mode TEXT NOT NULL DEFAULT 'AUTO',
                last_sent_at TEXT NULL,
                next_run_at TEXT NOT NULL,
                created_by TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_message_campaigns_due
            ON message_campaigns (guild_id, enabled, next_run_at);

            CREATE TABLE IF NOT EXISTS message_send_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                status TEXT NOT NULL,
                reason TEXT NULL,
                error TEXT NULL,
                FOREIGN KEY(campaign_id) REFERENCES message_campaigns(id)
            );

            CREATE TABLE IF NOT EXISTS channel_activity (
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                last_message_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, channel_id)
            );

            CREATE TABLE IF NOT EXISTS message_rotation_state (
                guild_id TEXT PRIMARY KEY,
                last_campaign_id INTEGER NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        await self._ensure_message_campaign_columns()
        await self._conn.commit()
        logger.info("Database schema initialized")

    async def _ensure_message_campaign_columns(self) -> None:
        assert self._conn is not None
        columns = await self.fetchall("PRAGMA table_info(message_campaigns)")
        existing = {row["name"] for row in columns}
        missing = {
            "text_green": "TEXT NULL",
            "text_yellow": "TEXT NULL",
            "text_red": "TEXT NULL",
            "text_black": "TEXT NULL",
            "mood_mode": "TEXT NOT NULL DEFAULT 'AUTO'",
        }
        for name, col_def in missing.items():
            if name not in existing:
                await self._conn.execute(f"ALTER TABLE message_campaigns ADD COLUMN {name} {col_def}")

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

    async def get_barcello_snapshot(
        self,
        guild_id: str,
        channel_id: str,
        window_minutes: int,
        window_end_ts: str,
    ) -> Optional[aiosqlite.Row]:
        return await self.fetchone(
            """
            SELECT * FROM barcello_snapshots
            WHERE guild_id = ? AND channel_id = ? AND window_minutes = ? AND window_end_ts = ?
            """,
            (guild_id, channel_id, window_minutes, window_end_ts),
        )

    async def get_barcello_snapshot_before(
        self,
        guild_id: str,
        channel_id: str,
        window_minutes: int,
        window_end_ts: str,
    ) -> Optional[aiosqlite.Row]:
        return await self.fetchone(
            """
            SELECT * FROM barcello_snapshots
            WHERE guild_id = ? AND channel_id = ? AND window_minutes = ? AND window_end_ts < ?
            ORDER BY window_end_ts DESC
            LIMIT 1
            """,
            (guild_id, channel_id, window_minutes, window_end_ts),
        )

    async def put_barcello_snapshot(
        self,
        *,
        guild_id: str,
        channel_id: str,
        window_minutes: int,
        window_end_ts: str,
        score: int,
        reasons_json: str,
        metrics_json: str,
        computed_ts: str,
    ) -> None:
        await self.execute(
            """
            INSERT INTO barcello_snapshots (
                guild_id, channel_id, window_minutes, window_end_ts,
                score, reasons_json, metrics_json, computed_ts
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, channel_id, window_minutes, window_end_ts) DO UPDATE SET
                score = excluded.score,
                reasons_json = excluded.reasons_json,
                metrics_json = excluded.metrics_json,
                computed_ts = excluded.computed_ts
            """,
            (
                guild_id,
                channel_id,
                window_minutes,
                window_end_ts,
                score,
                reasons_json,
                metrics_json,
                computed_ts,
            ),
        )

    async def insert_barcello_feedback(
        self,
        *,
        created_at: str,
        channel_id: str,
        snapshot_id: str,
        rater_user_id: str,
        verdict: str,
        reason: Optional[str],
        delta_target: Optional[int],
        score_pred: int,
        profile: Optional[str],
    ) -> None:
        await self.execute(
            """
            INSERT INTO barcello_feedback (
                created_at, channel_id, snapshot_id, rater_user_id, verdict, reason, delta_target, score_pred, profile
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                channel_id,
                snapshot_id,
                rater_user_id,
                verdict,
                reason,
                delta_target,
                score_pred,
                profile,
            ),
        )

    async def list_barcello_feedback(self, days: int = 30) -> list[aiosqlite.Row]:
        return await self.fetchall(
            """
            SELECT *
            FROM barcello_feedback
            WHERE created_at >= datetime('now', ?)
            ORDER BY created_at DESC
            """,
            (f"-{days} days",),
        )

    async def fetch_barcello_feedback(self, *, time_from: str, time_to: str) -> list[aiosqlite.Row]:
        return await self.fetchall(
            """
            SELECT *
            FROM barcello_feedback
            WHERE created_at >= ? AND created_at <= ?
            ORDER BY created_at DESC
            """,
            (time_from, time_to),
        )

    async def get_barcello_snapshot_by_end(
        self,
        *,
        channel_id: str,
        window_minutes: int,
        window_end_ts: str,
    ) -> Optional[aiosqlite.Row]:
        return await self.fetchone(
            """
            SELECT * FROM barcello_snapshots
            WHERE channel_id = ? AND window_minutes = ? AND window_end_ts = ?
            """,
            (channel_id, window_minutes, window_end_ts),
        )

    async def fetch_messages_in_range(
        self,
        *,
        channel_id: str,
        start_ts: str,
        end_ts: str,
        limit: int = 1000,
    ) -> list[aiosqlite.Row]:
        return await self.fetchall(
            """
            SELECT * FROM messages
            WHERE channel_id = ? AND ts >= ? AND ts <= ?
            ORDER BY ts ASC
            LIMIT ?
            """,
            (channel_id, start_ts, end_ts, limit),
        )

    async def fetch_events_in_range(
        self,
        *,
        channel_id: str,
        start_ts: str,
        end_ts: str,
        limit: int = 1000,
    ) -> list[aiosqlite.Row]:
        return await self.fetchall(
            """
            SELECT * FROM events
            WHERE channel_id = ? AND ts >= ? AND ts <= ?
            ORDER BY ts ASC
            LIMIT ?
            """,
            (channel_id, start_ts, end_ts, limit),
        )

    async def fetch_latest_message_in_range(
        self,
        *,
        channel_id: str,
        start_ts: str,
        end_ts: str,
    ) -> Optional[aiosqlite.Row]:
        return await self.fetchone(
            """
            SELECT ts, message_id
            FROM messages
            WHERE channel_id = ? AND ts >= ? AND ts <= ?
            ORDER BY ts DESC
            LIMIT 1
            """,
            (channel_id, start_ts, end_ts),
        )

    async def fetch_nearest_message_id(
        self,
        *,
        channel_id: str,
        ts: str,
    ) -> Optional[str]:
        row = await self.fetchone(
            """
            SELECT message_id
            FROM messages
            WHERE channel_id = ?
            ORDER BY ABS(strftime('%s', ts) - strftime('%s', ?)) ASC
            LIMIT 1
            """,
            (channel_id, ts),
        )
        if row:
            return row["message_id"]
        return None

    async def fetch_nearest_message_id_in_range(
        self,
        *,
        channel_id: str,
        start_ts: str,
        end_ts: str,
        ts: str,
    ) -> Optional[str]:
        row = await self.fetchone(
            """
            SELECT message_id
            FROM messages
            WHERE channel_id = ? AND ts >= ? AND ts <= ?
            ORDER BY ABS(strftime('%s', ts) - strftime('%s', ?)) ASC
            LIMIT 1
            """,
            (channel_id, start_ts, end_ts, ts),
        )
        if row:
            return row["message_id"]
        return None

    async def message_exists_in_channel(self, *, channel_id: str, message_id: str) -> bool:
        row = await self.fetchone(
            """
            SELECT 1
            FROM messages
            WHERE channel_id = ? AND message_id = ?
            LIMIT 1
            """,
            (channel_id, message_id),
        )
        return row is not None

    async def fetch_message_by_id(
        self,
        *,
        channel_id: str,
        message_id: str,
    ) -> Optional[aiosqlite.Row]:
        return await self.fetchone(
            """
            SELECT message_id, author_id, content, ts
            FROM messages
            WHERE channel_id = ? AND message_id = ?
            LIMIT 1
            """,
            (channel_id, message_id),
        )

    async def fetch_user_display_name(self, *, guild_id: str, user_id: str) -> Optional[str]:
        row = await self.fetchone(
            """
            SELECT gm.nickname, u.display_name, u.global_name, u.username
            FROM users u
            LEFT JOIN guild_memberships gm
                ON gm.user_id = u.user_id AND gm.guild_id = ?
            WHERE u.user_id = ?
            LIMIT 1
            """,
            (guild_id, user_id),
        )
        if not row:
            return None
        return (
            row["nickname"]
            or row["display_name"]
            or row["global_name"]
            or row["username"]
        )

    async def fetch_voice_sessions_in_range(
        self,
        *,
        guild_id: str,
        voice_channel_id: str,
        start_ts: str,
        end_ts: str,
    ) -> list[aiosqlite.Row]:
        return await self.fetchall(
            """
            SELECT voice_session_id, started_ts, ended_ts, meta_json
            FROM voice_sessions
            WHERE guild_id = ? AND voice_channel_id = ?
              AND started_ts <= ?
              AND (ended_ts IS NULL OR ended_ts >= ?)
            ORDER BY started_ts ASC
            """,
            (guild_id, voice_channel_id, end_ts, start_ts),
        )

    async def fetch_last_privacy_event_before(
        self,
        *,
        channel_id: str,
        ts: str,
    ) -> Optional[aiosqlite.Row]:
        return await self.fetchone(
            """
            SELECT ts, event_type, actor_id, meta_json
            FROM events
            WHERE channel_id = ? AND ts <= ? AND event_type IN (?, ?)
            ORDER BY ts DESC
            LIMIT 1
            """,
            (channel_id, ts, "voice.privacy_on", "voice.privacy_off"),
        )

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

    async def earliest_event_ts(self) -> Optional[str]:
        row = await self.fetchone("SELECT ts FROM events ORDER BY ts ASC LIMIT 1")
        return row["ts"] if row else None

    async def message_exists(self, message_id: str) -> bool:
        row = await self.fetchone("SELECT 1 FROM messages WHERE message_id = ? LIMIT 1", (message_id,))
        return row is not None

    async def upsert_role_policy(self, guild_id: str, role_id: str, command: str, usage_limit: Optional[int], cooldown_seconds: Optional[int]) -> None:
        await self.execute(
            """
            INSERT INTO role_policies (guild_id, role_id, command, usage_limit, cooldown_seconds)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, role_id, command) DO UPDATE SET
                usage_limit = excluded.usage_limit,
                cooldown_seconds = excluded.cooldown_seconds
            """,
            (guild_id, role_id, command, usage_limit, cooldown_seconds),
        )

    async def upsert_user_policy(self, guild_id: str, user_id: str, command: str, usage_limit: Optional[int], cooldown_seconds: Optional[int]) -> None:
        await self.execute(
            """
            INSERT INTO user_policies (guild_id, user_id, command, usage_limit, cooldown_seconds)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, command) DO UPDATE SET
                usage_limit = excluded.usage_limit,
                cooldown_seconds = excluded.cooldown_seconds
            """,
            (guild_id, user_id, command, usage_limit, cooldown_seconds),
        )

    async def delete_role_policy(self, guild_id: str, role_id: str, command: str) -> None:
        await self.execute(
            "DELETE FROM role_policies WHERE guild_id = ? AND role_id = ? AND command = ?",
            (guild_id, role_id, command),
        )

    async def delete_user_policy(self, guild_id: str, user_id: str, command: str) -> None:
        await self.execute(
            "DELETE FROM user_policies WHERE guild_id = ? AND user_id = ? AND command = ?",
            (guild_id, user_id, command),
        )

    async def fetch_role_policies(self, guild_id: str, role_id: str) -> list[aiosqlite.Row]:
        return await self.fetchall(
            "SELECT command, usage_limit, cooldown_seconds FROM role_policies WHERE guild_id = ? AND role_id = ?",
            (guild_id, role_id),
        )

    async def fetch_user_policies(self, guild_id: str, user_id: str) -> list[aiosqlite.Row]:
        return await self.fetchall(
            "SELECT command, usage_limit, cooldown_seconds FROM user_policies WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )

    async def fetch_role_policy(self, guild_id: str, role_id: str, command: str) -> Optional[aiosqlite.Row]:
        return await self.fetchone(
            "SELECT usage_limit, cooldown_seconds FROM role_policies WHERE guild_id = ? AND role_id = ? AND command = ?",
            (guild_id, role_id, command),
        )

    async def fetch_user_policy(self, guild_id: str, user_id: str, command: str) -> Optional[aiosqlite.Row]:
        return await self.fetchone(
            "SELECT usage_limit, cooldown_seconds FROM user_policies WHERE guild_id = ? AND user_id = ? AND command = ?",
            (guild_id, user_id, command),
        )

    async def fetch_usage_counter(self, guild_id: str, user_id: str, command: str, window_date: str) -> Optional[aiosqlite.Row]:
        return await self.fetchone(
            "SELECT used_count, last_used_ts FROM usage_counters WHERE guild_id = ? AND user_id = ? AND command = ? AND window_date = ?",
            (guild_id, user_id, command, window_date),
        )

    async def upsert_usage_counter(self, guild_id: str, user_id: str, command: str, window_date: str, used_count: int, last_used_ts: str) -> None:
        await self.execute(
            """
            INSERT INTO usage_counters (guild_id, user_id, command, window_date, used_count, last_used_ts)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, command, window_date) DO UPDATE SET
                used_count = excluded.used_count,
                last_used_ts = excluded.last_used_ts
            """,
            (guild_id, user_id, command, window_date, used_count, last_used_ts),
        )

    async def start_voice_session(self, voice_session_id: str, guild_id: str, voice_channel_id: str, started_ts: str, meta: dict[str, Any]) -> None:
        await self.execute(
            """
            INSERT INTO voice_sessions (voice_session_id, guild_id, voice_channel_id, started_ts, ended_ts, meta_json)
            VALUES (?, ?, ?, ?, NULL, ?)
            """,
            (voice_session_id, guild_id, voice_channel_id, started_ts, json.dumps(meta)),
        )

    async def end_voice_session(self, voice_session_id: str, ended_ts: str) -> None:
        await self.execute(
            "UPDATE voice_sessions SET ended_ts = ? WHERE voice_session_id = ?",
            (ended_ts, voice_session_id),
        )

    async def get_active_voice_session(self, guild_id: str, voice_channel_id: str) -> Optional[aiosqlite.Row]:
        return await self.fetchone(
            """
            SELECT voice_session_id, started_ts, meta_json
            FROM voice_sessions
            WHERE guild_id = ? AND voice_channel_id = ? AND ended_ts IS NULL
            ORDER BY started_ts DESC
            LIMIT 1
            """,
            (guild_id, voice_channel_id),
        )

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

    async def find_voice_ingest_bots_for_voice_channel(self, voice_channel_id: str) -> list[str]:
        rows = await self.fetchall(
            "SELECT key FROM settings WHERE key LIKE 'voice_ingest.%' AND key LIKE '%.target_voice_channel_id' AND value = ?",
            (voice_channel_id,),
        )
        bot_ids: set[str] = set()
        for row in rows:
            key = row["key"]
            parts = key.split(".")
            if len(parts) == 3:
                _, bot_id, _ = parts
                bot_ids.add(bot_id)
        return sorted(bot_ids)

    async def get_last_privacy_event(self, voice_channel_id: str) -> Optional[dict[str, Any]]:
        row = await self.fetchone(
            "SELECT ts, event_type, actor_id, meta_json FROM events WHERE channel_id = ? AND event_type IN (?, ?) ORDER BY ts DESC LIMIT 1",
            (voice_channel_id, "voice.privacy_on", "voice.privacy_off"),
        )
        if row is None:
            return None
        meta = json.loads(row["meta_json"]) if row["meta_json"] else {}
        return {
            "ts": row["ts"],
            "event_type": row["event_type"],
            "actor_id": row["actor_id"],
            "meta": meta,
        }

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

    async def set_message_channel_enabled(self, guild_id: str, channel_id: str, enabled: bool) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.execute(
            """
            INSERT INTO message_channels (guild_id, channel_id, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, channel_id) DO UPDATE SET
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (guild_id, channel_id, 1 if enabled else 0, now, now),
        )

    async def get_message_channel_status(self, guild_id: str, channel_id: str) -> bool:
        row = await self.fetchone(
            "SELECT enabled FROM message_channels WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
        return bool(row["enabled"]) if row else False

    async def list_enabled_message_channels(self, guild_id: str) -> list[str]:
        rows = await self.fetchall(
            "SELECT channel_id FROM message_channels WHERE guild_id = ? AND enabled = 1",
            (guild_id,),
        )
        return [row["channel_id"] for row in rows]

    async def create_message_campaign(
        self,
        *,
        guild_id: str,
        campaign_type: str,
        name: Optional[str],
        text: Optional[str],
        text_green: Optional[str],
        text_yellow: Optional[str],
        text_red: Optional[str],
        text_black: Optional[str],
        enabled: bool,
        start_time_local: str,
        interval_minutes: int,
        jitter_seconds: int,
        only_if_idle_minutes: int,
        mood_mode: str,
        next_run_at: str,
        created_by: Optional[str],
    ) -> int:
        assert self._conn is not None
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._conn.execute(
            """
            INSERT INTO message_campaigns (
                guild_id, type, name, text, text_green, text_yellow, text_red, text_black, enabled, start_time_local, interval_minutes,
                jitter_seconds, only_if_idle_minutes, mood_mode, last_sent_at, next_run_at, created_by,
                created_at, updated_at, deleted_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, NULL)
            """,
            (
                guild_id,
                campaign_type,
                name,
                text,
                text_green,
                text_yellow,
                text_red,
                text_black,
                1 if enabled else 0,
                start_time_local,
                interval_minutes,
                jitter_seconds,
                only_if_idle_minutes,
                mood_mode,
                next_run_at,
                created_by,
                now,
                now,
            ),
        )
        await self._conn.commit()
        return int(cursor.lastrowid)

    async def list_message_campaigns(self, guild_id: str, *, include_disabled: bool = True) -> list[aiosqlite.Row]:
        conditions = ["guild_id = ?", "deleted_at IS NULL"]
        params: list[Any] = [guild_id]
        if not include_disabled:
            conditions.append("enabled = 1")
        query = f"SELECT * FROM message_campaigns WHERE {' AND '.join(conditions)} ORDER BY id ASC"
        return await self.fetchall(query, tuple(params))

    async def get_message_campaign(self, guild_id: str, campaign_id: int) -> Optional[aiosqlite.Row]:
        return await self.fetchone(
            """
            SELECT * FROM message_campaigns
            WHERE guild_id = ? AND id = ? AND deleted_at IS NULL
            """,
            (guild_id, campaign_id),
        )

    async def set_message_campaign_enabled(self, guild_id: str, campaign_id: int, enabled: bool) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.execute(
            """
            UPDATE message_campaigns
            SET enabled = ?, updated_at = ?
            WHERE guild_id = ? AND id = ? AND deleted_at IS NULL
            """,
            (1 if enabled else 0, now, guild_id, campaign_id),
        )

    async def soft_delete_message_campaign(self, guild_id: str, campaign_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.execute(
            """
            UPDATE message_campaigns
            SET enabled = 0, deleted_at = ?, updated_at = ?
            WHERE guild_id = ? AND id = ?
            """,
            (now, now, guild_id, campaign_id),
        )

    async def update_campaign_next_run(self, guild_id: str, campaign_id: int, next_run_at: str, last_sent_at: Optional[str]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.execute(
            """
            UPDATE message_campaigns
            SET next_run_at = ?, last_sent_at = ?, updated_at = ?
            WHERE guild_id = ? AND id = ? AND deleted_at IS NULL
            """,
            (next_run_at, last_sent_at, now, guild_id, campaign_id),
        )

    async def due_message_campaigns(self, now_iso: str) -> list[dict[str, object]]:
        rows = await self.fetchall(
            """
            SELECT *
            FROM message_campaigns
            WHERE enabled = 1 AND deleted_at IS NULL AND next_run_at <= ?
            ORDER BY next_run_at ASC
            """,
            (now_iso,),
        )
        return [dict(row) for row in rows]

    async def get_channel_last_activity(self, guild_id: str, channel_id: str) -> Optional[str]:
        row = await self.fetchone(
            """
            SELECT last_message_at
            FROM channel_activity
            WHERE guild_id = ? AND channel_id = ?
            """,
            (guild_id, channel_id),
        )
        return row["last_message_at"] if row else None

    async def upsert_channel_activity(self, guild_id: str, channel_id: str, last_message_at: str) -> None:
        await self.execute(
            """
            INSERT INTO channel_activity (guild_id, channel_id, last_message_at)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, channel_id) DO UPDATE SET
                last_message_at = excluded.last_message_at
            """,
            (guild_id, channel_id, last_message_at),
        )

    async def insert_send_log(
        self,
        *,
        campaign_id: int,
        guild_id: str,
        channel_id: str,
        sent_at: str,
        status: str,
        reason: Optional[str],
        error: Optional[str],
    ) -> None:
        await self.execute(
            """
            INSERT INTO message_send_log (
                campaign_id, guild_id, channel_id, sent_at, status, reason, error
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (campaign_id, guild_id, channel_id, sent_at, status, reason, error),
        )

    async def count_message_send_log_since(self, guild_id: str, channel_id: str, since_iso: str) -> int:
        row = await self.fetchone(
            """
            SELECT COUNT(*) AS count
            FROM message_send_log
            WHERE guild_id = ? AND channel_id = ? AND status = 'sent' AND sent_at >= ?
            """,
            (guild_id, channel_id, since_iso),
        )
        return int(row["count"]) if row else 0

    async def count_sent_today(self, guild_id: str, channel_id: str, day_yyyymmdd: str) -> int:
        tz = ZoneInfo("Europe/Rome")
        day = datetime.fromisoformat(day_yyyymmdd).date()
        start_local = datetime.combine(day, time.min, tzinfo=tz)
        end_local = start_local + timedelta(days=1)
        start_utc = start_local.astimezone(timezone.utc).isoformat()
        end_utc = end_local.astimezone(timezone.utc).isoformat()
        row = await self.fetchone(
            """
            SELECT COUNT(*) AS count
            FROM message_send_log
            WHERE guild_id = ? AND channel_id = ? AND status = 'sent' AND sent_at >= ? AND sent_at < ?
            """,
            (guild_id, channel_id, start_utc, end_utc),
        )
        return int(row["count"]) if row else 0

    async def get_rotation_state(self, guild_id: str) -> Optional[int]:
        row = await self.fetchone(
            "SELECT last_campaign_id FROM message_rotation_state WHERE guild_id = ?",
            (guild_id,),
        )
        if row is None:
            return None
        return row["last_campaign_id"]

    async def set_rotation_state(self, guild_id: str, last_campaign_id: Optional[int]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.execute(
            """
            INSERT INTO message_rotation_state (guild_id, last_campaign_id, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                last_campaign_id = excluded.last_campaign_id,
                updated_at = excluded.updated_at
            """,
            (guild_id, last_campaign_id, now),
        )

    async def list_custom_campaigns_enabled(self, guild_id: str) -> list[dict[str, object]]:
        rows = await self.fetchall(
            """
            SELECT *
            FROM message_campaigns
            WHERE guild_id = ? AND type = 'CUSTOM' AND enabled = 1 AND deleted_at IS NULL
            ORDER BY id ASC
            """,
            (guild_id,),
        )
        return [dict(row) for row in rows]

    async def list_campaign_guilds(self) -> list[str]:
        rows = await self.fetchall(
            """
            SELECT DISTINCT guild_id
            FROM message_campaigns
            WHERE enabled = 1 AND deleted_at IS NULL
            """,
        )
        return [row["guild_id"] for row in rows]
