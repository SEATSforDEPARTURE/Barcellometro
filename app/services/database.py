from __future__ import annotations

import json
import logging
import re
import uuid
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

            CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_voice_session_per_channel
            ON voice_sessions (guild_id, voice_channel_id)
            WHERE ended_ts IS NULL;


            CREATE TABLE IF NOT EXISTS voice_participant_events (
                event_id TEXT PRIMARY KEY,
                guild_id TEXT NOT NULL,
                voice_channel_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                username TEXT,
                event_type TEXT NOT NULL,
                ts TEXT NOT NULL,
                from_channel_id TEXT,
                to_channel_id TEXT,
                meta_json TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_vpe_guild_channel_ts
            ON voice_participant_events (guild_id, voice_channel_id, ts);

            CREATE INDEX IF NOT EXISTS idx_vpe_guild_user_ts
            ON voice_participant_events (guild_id, user_id, ts);

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


            CREATE TABLE IF NOT EXISTS daily_reports (
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0,
                send_time_local TEXT NOT NULL DEFAULT '00:00',
                last_sent_local_date TEXT NULL,
                last_sent_time_local TEXT NULL,
                last_sent_kind TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, channel_id)
            );

            CREATE TABLE IF NOT EXISTS message_channels (
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, channel_id)
            );

            CREATE TABLE IF NOT EXISTS activity_channels (
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, channel_id)
            );

            CREATE TABLE IF NOT EXISTS message_campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                channel_id TEXT NULL,
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
                deleted_at TEXT NULL,
                embed_title TEXT NULL,
                embed_color TEXT NULL
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

            CREATE TABLE IF NOT EXISTS trigger_channels (
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                trigger_key TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, channel_id, trigger_key)
            );

            CREATE TABLE IF NOT EXISTS trigger_barcello_state (
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                last_color TEXT NULL,
                last_score INTEGER NULL,
                last_ts TEXT NULL,
                PRIMARY KEY (guild_id, channel_id)
            );

            CREATE TABLE IF NOT EXISTS trigger_barcello_state_last_seen (
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                color TEXT NOT NULL,
                last_seen_ts TEXT NOT NULL,
                PRIMARY KEY (guild_id, channel_id, color)
            );

            CREATE TABLE IF NOT EXISTS trigger_barcello_daily_state_stats (
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                day_date TEXT NOT NULL,
                color TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                first_seen_ts TEXT NULL,
                last_seen_ts TEXT NULL,
                PRIMARY KEY (guild_id, channel_id, day_date, color)
            );

            CREATE TABLE IF NOT EXISTS trigger_barcello_notify_cooldown (
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                color TEXT NOT NULL,
                last_notified_ts TEXT NOT NULL,
                PRIMARY KEY (guild_id, channel_id, color)
            );

            CREATE TABLE IF NOT EXISTS trigger_phrases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                phrase TEXT NOT NULL,
                match_mode TEXT NOT NULL DEFAULT 'CONTAINS',
                case_sensitive INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_seen_ts TEXT NULL,
                last_seen_message_id TEXT NULL,
                embed_color TEXT NULL,
                UNIQUE (guild_id, channel_id, phrase)
            );

            CREATE TABLE IF NOT EXISTS trigger_phrase_user_stats (
                phrase_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                last_seen_ts TEXT NULL,
                last_seen_message_id TEXT NULL,
                PRIMARY KEY (phrase_id, user_id),
                FOREIGN KEY (phrase_id) REFERENCES trigger_phrases(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS trigger_phrase_milestones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phrase_id INTEGER NOT NULL,
                threshold_count INTEGER NOT NULL,
                template_text TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (phrase_id, threshold_count),
                FOREIGN KEY (phrase_id) REFERENCES trigger_phrases(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS trigger_phrase_global_milestones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                threshold_count INTEGER NOT NULL,
                template_text TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, threshold_count)
            );

            CREATE TABLE IF NOT EXISTS trigger_phrase_global_user_custom_phrases (
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                custom_text TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS trigger_state (
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                trigger_key TEXT NOT NULL,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, channel_id, trigger_key)
            );

            CREATE TABLE IF NOT EXISTS kv_cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_hobbies (
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                user_name TEXT,
                hobby TEXT NOT NULL,
                source_channel_id TEXT NOT NULL,
                source_message_id TEXT NOT NULL,
                source_created_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_used_at TEXT NULL,
                PRIMARY KEY (guild_id, user_id, hobby, source_message_id)
            );


            CREATE TABLE IF NOT EXISTS qna_user_bonus (
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                bonus INTEGER NOT NULL,
                expires_at TEXT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            );
            

            CREATE TABLE IF NOT EXISTS qna_sessions (
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                history_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, channel_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS activity_monitoring_config (
                guild_id TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                mod_channel_id TEXT NULL,
                send_time_local TEXT NOT NULL DEFAULT '09:00',
                last_sent_local_date TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS inactivity_config (
                guild_id TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                auto_enabled INTEGER NOT NULL DEFAULT 0,
                grace_days_after_reminder INTEGER NOT NULL DEFAULT 7,
                reminder_cooldown_days INTEGER NOT NULL DEFAULT 14,
                ban_days INTEGER NOT NULL DEFAULT 7,
                atrio_channel_id TEXT NULL,
                invite_url TEXT NULL,
                excluded_role_ids_json TEXT NOT NULL DEFAULT '[]',
                default_policy_json TEXT NOT NULL DEFAULT '{"inactive_days":30,"window_days":30,"min_messages":1,"mode":"OR","min_account_age_days":0}',
                dm_reminder_template TEXT NULL,
                dm_kick_template TEXT NULL,
                atrio_template TEXT NULL,
                updated_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS inactivity_role_policies (
                guild_id TEXT NOT NULL,
                role_id TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 0,
                policy_json TEXT NOT NULL,
                PRIMARY KEY (guild_id, role_id)
            );

            CREATE TABLE IF NOT EXISTS inactivity_user_state (
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                last_reminder_at TEXT NULL,
                reminder_count INTEGER NOT NULL DEFAULT 0,
                last_kick_at TEXT NULL,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS temp_bans (
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                unban_at TEXT NOT NULL,
                reason TEXT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS aura_user_profile (
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                eligible INTEGER NOT NULL DEFAULT 0,
                eligibility_reason TEXT,
                role_tier TEXT,
                aura_lifetime INTEGER NOT NULL DEFAULT 0,
                aura_season INTEGER NOT NULL DEFAULT 0,
                last_computed_at TEXT,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS aura_user_rolling_stats (
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                window_key TEXT NOT NULL,
                msg_count INTEGER NOT NULL DEFAULT 0,
                reply_received INTEGER NOT NULL DEFAULT 0,
                unique_interactions INTEGER NOT NULL DEFAULT 0,
                degrade_events INTEGER NOT NULL DEFAULT 0,
                invigorate_events INTEGER NOT NULL DEFAULT 0,
                quality_counter INTEGER NOT NULL DEFAULT 0,
                last_activity_at TEXT,
                PRIMARY KEY (guild_id, user_id, window_key)
            );

            CREATE TABLE IF NOT EXISTS aura_events_ledger (
                id TEXT PRIMARY KEY,
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                channel_id TEXT,
                ts TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                delta_points INTEGER NOT NULL,
                meta_json TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_aura_events_ledger_gut
            ON aura_events_ledger (guild_id, user_id, ts);

            CREATE TABLE IF NOT EXISTS aura_results (
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                channel_id TEXT,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                karma_percent INTEGER NOT NULL,
                trend_delta INTEGER NOT NULL,
                points_total INTEGER NOT NULL,
                metrics_json TEXT NOT NULL,
                computed_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id, channel_id, period_start, period_end)
            );

            CREATE TABLE IF NOT EXISTS aura_mission_assignments (
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                mission_id TEXT NOT NULL,
                assigned_at TEXT NOT NULL,
                due_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'assigned',
                completed_at TEXT,
                reward_points INTEGER NOT NULL DEFAULT 0,
                meta_json TEXT,
                PRIMARY KEY (guild_id, user_id, mission_id, assigned_at)
            );

            CREATE TABLE IF NOT EXISTS archetype_profiles (
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                period_days INTEGER NOT NULL,
                archetype_scores_json TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                computed_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id, period_days)
            );

            """
        )
        await self._ensure_message_campaign_columns()
        await self._ensure_daily_report_columns()
        await self._ensure_trigger_phrase_columns()
        await self._conn.commit()
        logger.info("Database schema initialized")

    async def _ensure_message_campaign_columns(self) -> None:
        assert self._conn is not None
        columns = await self.fetchall("PRAGMA table_info(message_campaigns)")
        existing = {row["name"] for row in columns}
        missing = {
            "guild_id": "TEXT NULL",
            "channel_id": "TEXT NULL",
            "text_green": "TEXT NULL",
            "text_yellow": "TEXT NULL",
            "text_red": "TEXT NULL",
            "text_black": "TEXT NULL",
            "mood_mode": "TEXT NOT NULL DEFAULT 'AUTO'",
            "embed_title": "TEXT NULL",
            "embed_color": "TEXT NULL",
        }
        for name, col_def in missing.items():
            if name not in existing:
                await self._conn.execute(f"ALTER TABLE message_campaigns ADD COLUMN {name} {col_def}")

    async def _ensure_daily_report_columns(self) -> None:
        assert self._conn is not None
        columns = await self.fetchall("PRAGMA table_info(daily_reports)")
        existing = {row["name"] for row in columns}
        missing = {
            "last_sent_time_local": "TEXT NULL",
            "last_sent_kind": "TEXT NULL",
        }
        for name, col_def in missing.items():
            if name not in existing:
                await self._conn.execute(f"ALTER TABLE daily_reports ADD COLUMN {name} {col_def}")

    async def _ensure_trigger_phrase_columns(self) -> None:
        assert self._conn is not None
        columns = await self.fetchall("PRAGMA table_info(trigger_phrases)")
        existing = {row["name"] for row in columns}
        missing = {
            "embed_color": "TEXT NULL",
            "cooldown_seconds": "INTEGER NULL",
            "allowed_role_ids": "TEXT NULL",
        }
        for name, col_def in missing.items():
            if name not in existing:
                await self._conn.execute(f"ALTER TABLE trigger_phrases ADD COLUMN {name} {col_def}")

    def _serialize_allowed_role_ids(self, allowed_role_ids: list[str] | list[int] | None) -> str | None:
        if not allowed_role_ids:
            return None
        normalized: list[str] = []
        for role_id in allowed_role_ids:
            candidate = str(role_id).strip()
            if not candidate:
                continue
            normalized.append(candidate)
        if not normalized:
            return None
        deduped = list(dict.fromkeys(normalized))
        return json.dumps(deduped, ensure_ascii=False)

    def _parse_allowed_role_ids(self, raw: Any) -> list[str]:
        if raw is None:
            return []
        text = str(raw).strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        values: list[str] = []
        if isinstance(parsed, list):
            for item in parsed:
                candidate = str(item).strip()
                if candidate:
                    values.append(candidate)
        else:
            for item in text.split(","):
                candidate = item.strip()
                if candidate:
                    values.append(candidate)
        return list(dict.fromkeys(values))

    def _normalize_trigger_phrase_row(self, row: aiosqlite.Row) -> dict[str, Any]:
        data = dict(row)
        data["allowed_role_ids"] = self._parse_allowed_role_ids(data.get("allowed_role_ids"))
        cooldown = data.get("cooldown_seconds")
        data["cooldown_seconds"] = int(cooldown) if cooldown is not None else None
        return data

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
            WHERE channel_id = ? AND ts >= ? AND ts <= ? AND COALESCE(is_deleted, 0) = 0
            ORDER BY ts ASC
            LIMIT ?
            """,
            (channel_id, start_ts, end_ts, limit),
        )


    async def get_channel_coverage(self, channel_id: str) -> tuple[Optional[str], Optional[str]]:
        row = await self.fetchone(
            """
            SELECT MIN(ts) AS min_ts, MAX(ts) AS max_ts
            FROM messages
            WHERE channel_id = ? AND COALESCE(is_deleted, 0) = 0
            """,
            (channel_id,),
        )
        if not row:
            return None, None
        return row["min_ts"], row["max_ts"]

    async def fetch_messages_in_range_time_bucketed(
        self,
        *,
        channel_id: str,
        start_ts: str,
        end_ts: str,
        buckets: int,
        per_bucket_limit: int,
        include_bots: bool = True,
    ) -> list[aiosqlite.Row]:
        start_dt = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end_ts.replace("Z", "+00:00"))
        if end_dt < start_dt:
            start_dt, end_dt = end_dt, start_dt
        total_seconds = max(0, int((end_dt - start_dt).total_seconds()))
        bucket_count = max(1, int(buckets or 1))
        bucket_size = max(1, total_seconds // bucket_count)
        per_bucket = max(1, int(per_bucket_limit or 1))

        base_query = """
            SELECT
                m.*, 
                COALESCE(gm.nickname, u.display_name, u.global_name, u.username, m.author_id) AS author_name
            FROM messages AS m
            LEFT JOIN users AS u ON u.user_id = m.author_id
            LEFT JOIN guild_memberships AS gm ON gm.guild_id = m.guild_id AND gm.user_id = m.author_id
            WHERE m.channel_id = ? AND m.ts >= ? AND m.ts <= ? AND COALESCE(m.is_deleted, 0) = 0
        """
        if not include_bots:
            base_query += " AND COALESCE(u.is_bot, 0) = 0"
        base_query += " ORDER BY m.ts ASC LIMIT ?"

        rows: list[aiosqlite.Row] = []
        bucket_counts: list[int] = []
        for idx in range(bucket_count):
            bucket_start = start_dt + timedelta(seconds=idx * bucket_size)
            if idx == bucket_count - 1:
                bucket_end = end_dt
            else:
                bucket_end = bucket_start + timedelta(seconds=bucket_size - 1)
            if bucket_end < bucket_start:
                bucket_end = bucket_start
            bucket_rows = await self.fetchall(
                base_query,
                (channel_id, bucket_start.isoformat(), bucket_end.isoformat(), per_bucket),
            )
            bucket_counts.append(len(bucket_rows))
            rows.extend(bucket_rows)

        deduped: list[aiosqlite.Row] = []
        seen_message_ids: set[str] = set()
        seen_fallback_keys: set[tuple[str, str, str]] = set()
        for row in rows:
            message_id = str(row["message_id"] or "").strip() if "message_id" in row.keys() else ""
            if message_id:
                if message_id in seen_message_ids:
                    continue
                seen_message_ids.add(message_id)
                deduped.append(row)
                continue
            author_id = str(row["author_id"] or "").strip() if "author_id" in row.keys() else ""
            ts_value = str(row["ts"] or "").strip() if "ts" in row.keys() else ""
            content_value = str(row["content"] or "")
            fallback_key = (author_id, ts_value, content_value)
            if fallback_key in seen_fallback_keys:
                continue
            seen_fallback_keys.add(fallback_key)
            deduped.append(row)

        deduped.sort(key=lambda row: str(row["ts"] or ""))
        logger.info(
            "messages bucketed fetch: channel_id=%s buckets=%s per_bucket_limit=%s include_bots=%s bucket_counts=%s total=%s deduped=%s",
            channel_id,
            bucket_count,
            per_bucket,
            include_bots,
            bucket_counts,
            len(rows),
            len(deduped),
        )
        return deduped

    async def search_channel_messages(
        self,
        channel_id: str,
        query_text: str,
        limit: int = 60,
        candidate_pool: int = 300,
        min_content_length: int = 0,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(60, int(limit or 60)))
        safe_pool = max(safe_limit, min(300, int(candidate_pool or 300)))
        keywords = [token for token in re.findall(r"\w+", query_text.lower()) if len(token) > 2][:12]
        phrase = query_text.strip().lower()

        params: list[Any] = [channel_id]
        where_parts = ["m.channel_id = ?", "COALESCE(m.is_deleted, 0) = 0", "COALESCE(u.is_bot, 0) = 0"]
        if min_content_length > 0:
            where_parts.append("LENGTH(TRIM(COALESCE(m.content, ''))) >= ?")
            params.append(int(min_content_length))
        if keywords:
            like_parts: list[str] = []
            for kw in keywords:
                like_parts.append("LOWER(m.content) LIKE ?")
                params.append(f"%{kw}%")
            where_parts.append("(" + " OR ".join(like_parts) + ")")

        sql = f"""
            SELECT
                m.message_id,
                m.guild_id,
                m.channel_id,
                m.author_id,
                m.ts AS created_at,
                m.content,
                COALESCE(gm.nickname, u.display_name, u.global_name, u.username, m.author_id) AS author_name
            FROM messages AS m
            LEFT JOIN users AS u ON u.user_id = m.author_id
            LEFT JOIN guild_memberships AS gm ON gm.guild_id = m.guild_id AND gm.user_id = m.author_id
            WHERE {' AND '.join(where_parts)}
            ORDER BY m.ts DESC
            LIMIT ?
        """
        params.append(safe_pool)
        rows = await self.fetchall(sql, tuple(params))
        scored: list[dict[str, Any]] = []
        for row in rows:
            content = str(row["content"] or "")
            lower = content.lower()
            score = 0
            for kw in keywords:
                idx = lower.find(kw)
                if idx >= 0:
                    score += 1
                    if idx < 80:
                        score += 1
            if phrase and phrase in lower:
                score += 2
            if score <= 0 and keywords:
                continue
            scored.append(
                {
                    "message_id": str(row["message_id"] or ""),
                    "guild_id": str(row["guild_id"] or ""),
                    "channel_id": str(row["channel_id"] or ""),
                    "author_id": str(row["author_id"] or ""),
                    "author_name": str(row["author_name"] or row["author_id"] or ""),
                    "created_at": str(row["created_at"] or ""),
                    "content": content,
                    "score": score,
                }
            )
        scored.sort(key=lambda item: (int(item.get("score", 0)), str(item.get("created_at", ""))), reverse=True)
        return scored[:safe_limit]

    async def search_guild_messages(
        self,
        *,
        guild_id: str,
        query_text: str,
        limit: int = 60,
        candidate_pool: int = 300,
        min_content_length: int = 0,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(60, int(limit or 60)))
        safe_pool = max(safe_limit, min(300, int(candidate_pool or 300)))
        keywords = [token for token in re.findall(r"\w+", query_text.lower()) if len(token) > 2][:12]
        phrase = query_text.strip().lower()

        params: list[Any] = [guild_id]
        where_parts = ["m.guild_id = ?", "COALESCE(m.is_deleted, 0) = 0", "COALESCE(u.is_bot, 0) = 0"]
        if min_content_length > 0:
            where_parts.append("LENGTH(TRIM(COALESCE(m.content, ''))) >= ?")
            params.append(int(min_content_length))
        if keywords:
            like_parts: list[str] = []
            for kw in keywords:
                like_parts.append("LOWER(m.content) LIKE ?")
                params.append(f"%{kw}%")
            where_parts.append("(" + " OR ".join(like_parts) + ")")

        sql = f"""
            SELECT
                m.message_id,
                m.guild_id,
                m.channel_id,
                m.author_id,
                m.ts AS created_at,
                m.content,
                COALESCE(gm.nickname, u.display_name, u.global_name, u.username, m.author_id) AS author_name
            FROM messages AS m
            LEFT JOIN users AS u ON u.user_id = m.author_id
            LEFT JOIN guild_memberships AS gm ON gm.guild_id = m.guild_id AND gm.user_id = m.author_id
            WHERE {' AND '.join(where_parts)}
            ORDER BY m.ts DESC
            LIMIT ?
        """
        params.append(safe_pool)
        rows = await self.fetchall(sql, tuple(params))
        scored: list[dict[str, Any]] = []
        for row in rows:
            content = str(row["content"] or "")
            lower = content.lower()
            score = 0
            for kw in keywords:
                idx = lower.find(kw)
                if idx >= 0:
                    score += 1
                    if idx < 80:
                        score += 1
            if phrase and phrase in lower:
                score += 2
            if score <= 0 and keywords:
                continue
            scored.append(
                {
                    "message_id": str(row["message_id"] or ""),
                    "guild_id": str(row["guild_id"] or ""),
                    "channel_id": str(row["channel_id"] or ""),
                    "author_id": str(row["author_id"] or ""),
                    "author_name": str(row["author_name"] or row["author_id"] or ""),
                    "created_at": str(row["created_at"] or ""),
                    "content": content,
                    "score": score,
                }
            )
        scored.sort(key=lambda item: (int(item.get("score", 0)), str(item.get("created_at", ""))), reverse=True)
        return scored[:safe_limit]

    async def get_qna_session_history(self, guild_id: str, channel_id: str, user_id: str, now_iso: str) -> list[dict[str, str]]:
        row = await self.fetchone(
            """
            SELECT history_json, expires_at
            FROM qna_sessions
            WHERE guild_id = ? AND channel_id = ? AND user_id = ?
            """,
            (guild_id, channel_id, user_id),
        )
        if not row:
            return []
        expires_at = str(row["expires_at"] or "")
        if expires_at and expires_at < now_iso:
            await self.execute(
                "DELETE FROM qna_sessions WHERE guild_id = ? AND channel_id = ? AND user_id = ?",
                (guild_id, channel_id, user_id),
            )
            return []
        try:
            parsed = json.loads(str(row["history_json"] or "[]"))
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [item for item in parsed if isinstance(item, dict)]

    async def upsert_qna_session_history(
        self,
        guild_id: str,
        channel_id: str,
        user_id: str,
        history: list[dict[str, str]],
        now_iso: str,
        expires_at_iso: str,
    ) -> None:
        await self.execute(
            """
            INSERT INTO qna_sessions (guild_id, channel_id, user_id, history_json, updated_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, channel_id, user_id) DO UPDATE SET
                history_json = excluded.history_json,
                updated_at = excluded.updated_at,
                expires_at = excluded.expires_at
            """,
            (guild_id, channel_id, user_id, json.dumps(history, ensure_ascii=False), now_iso, expires_at_iso),
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
            WHERE channel_id = ? AND ts >= ? AND ts <= ? AND COALESCE(is_deleted, 0) = 0
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
            WHERE channel_id = ? AND COALESCE(is_deleted, 0) = 0
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
            WHERE channel_id = ? AND ts >= ? AND ts <= ? AND COALESCE(is_deleted, 0) = 0
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
            WHERE channel_id = ? AND message_id = ? AND COALESCE(is_deleted, 0) = 0
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
            SELECT message_id, author_id, content, ts, embeds_json
            FROM messages
            WHERE channel_id = ? AND message_id = ? AND COALESCE(is_deleted, 0) = 0
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


    async def insert_voice_participant_event(
        self,
        *,
        event_id: str,
        guild_id: str,
        voice_channel_id: str,
        user_id: str,
        username: str | None,
        event_type: str,
        ts: str,
        from_channel_id: str | None = None,
        to_channel_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        await self.execute(
            """
            INSERT INTO voice_participant_events (
                event_id, guild_id, voice_channel_id, user_id, username,
                event_type, ts, from_channel_id, to_channel_id, meta_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                guild_id,
                voice_channel_id,
                user_id,
                username,
                event_type,
                ts,
                from_channel_id,
                to_channel_id,
                json.dumps(meta) if meta is not None else None,
            ),
        )

    async def fetch_voice_participant_events_in_range(
        self,
        guild_id: str,
        voice_channel_id: str,
        start_ts: str,
        end_ts: str,
    ) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            """
            SELECT event_id, guild_id, voice_channel_id, user_id, username, event_type, ts,
                   from_channel_id, to_channel_id, meta_json
            FROM voice_participant_events
            WHERE guild_id = ? AND voice_channel_id = ?
              AND ts >= ? AND ts <= ?
            ORDER BY ts ASC
            """,
            (guild_id, voice_channel_id, start_ts, end_ts),
        )
        return [dict(row) for row in rows]

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

    async def get_trigger_enabled(self, guild_id: str, channel_id: str, trigger_key: str) -> bool:
        row = await self.fetchone(
            "SELECT enabled FROM trigger_channels WHERE guild_id = ? AND channel_id = ? AND trigger_key = ?",
            (guild_id, channel_id, trigger_key),
        )
        return bool(row["enabled"]) if row else False

    async def get_trigger_enabled_any_channel(self, guild_id: str, trigger_key: str) -> bool:
        row = await self.fetchone(
            "SELECT 1 FROM trigger_channels WHERE guild_id = ? AND trigger_key = ? AND enabled = 1 LIMIT 1",
            (guild_id, trigger_key),
        )
        return row is not None

    async def get_trigger_enabled_global(self, guild_id: str, trigger_key: str, *, scope_channel_id: str = "__guild__") -> bool:
        return await self.get_trigger_enabled(guild_id, scope_channel_id, trigger_key)

    async def set_trigger_enabled_global(
        self,
        guild_id: str,
        trigger_key: str,
        enabled: bool,
        *,
        scope_channel_id: str = "__guild__",
    ) -> None:
        await self.set_trigger_enabled(guild_id, scope_channel_id, trigger_key, enabled)

    async def set_trigger_enabled(self, guild_id: str, channel_id: str, trigger_key: str, enabled: bool) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.execute(
            """
            INSERT INTO trigger_channels (guild_id, channel_id, trigger_key, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, channel_id, trigger_key) DO UPDATE SET
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (guild_id, channel_id, trigger_key, 1 if enabled else 0, now, now),
        )

    async def list_triggers(self, guild_id: str, channel_id: str) -> dict[str, bool]:
        rows = await self.fetchall(
            "SELECT trigger_key, enabled FROM trigger_channels WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
        data = {"barcello": False, "frasi": False, "prompt": False, "qna": False, "insights": False}
        for row in rows:
            data[str(row["trigger_key"])] = bool(row["enabled"])
        return data

    async def list_enabled_trigger_channels(self, trigger_key: str) -> list[aiosqlite.Row]:
        return await self.fetchall(
            "SELECT guild_id, channel_id FROM trigger_channels WHERE trigger_key = ? AND enabled = 1",
            (trigger_key,),
        )

    async def get_barcello_trigger_state(self, guild_id: str, channel_id: str) -> Optional[dict[str, Any]]:
        row = await self.fetchone(
            "SELECT guild_id, channel_id, last_color, last_score, last_ts FROM trigger_barcello_state WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
        return dict(row) if row else None

    async def upsert_barcello_trigger_state(
        self,
        guild_id: str,
        channel_id: str,
        last_color: Optional[str],
        last_score: Optional[int],
        last_ts: Optional[str],
    ) -> None:
        await self.execute(
            """
            INSERT INTO trigger_barcello_state (guild_id, channel_id, last_color, last_score, last_ts)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, channel_id) DO UPDATE SET
                last_color = excluded.last_color,
                last_score = excluded.last_score,
                last_ts = excluded.last_ts
            """,
            (guild_id, channel_id, last_color, last_score, last_ts),
        )

    async def get_barcello_last_seen_for_color(self, guild_id: str, channel_id: str, color: str) -> Optional[str]:
        row = await self.fetchone(
            """
            SELECT last_seen_ts
            FROM trigger_barcello_state_last_seen
            WHERE guild_id = ? AND channel_id = ? AND color = ?
            """,
            (guild_id, channel_id, color),
        )
        return str(row["last_seen_ts"]) if row and row["last_seen_ts"] else None

    async def set_barcello_last_seen_for_color(self, guild_id: str, channel_id: str, color: str, ts: str) -> None:
        await self.execute(
            """
            INSERT INTO trigger_barcello_state_last_seen (guild_id, channel_id, color, last_seen_ts)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, channel_id, color) DO UPDATE SET
                last_seen_ts = excluded.last_seen_ts
            """,
            (guild_id, channel_id, color, ts),
        )

    async def get_barcello_daily_color_stats(
        self,
        guild_id: str,
        channel_id: str,
        day_date: str,
        color: str,
    ) -> dict[str, Any]:
        row = await self.fetchone(
            """
            SELECT count, first_seen_ts, last_seen_ts
            FROM trigger_barcello_daily_state_stats
            WHERE guild_id = ? AND channel_id = ? AND day_date = ? AND color = ?
            """,
            (guild_id, channel_id, day_date, color),
        )
        if not row:
            return {"count": 0, "first_seen_ts": None, "last_seen_ts": None}
        return {
            "count": int(row["count"] or 0),
            "first_seen_ts": row["first_seen_ts"],
            "last_seen_ts": row["last_seen_ts"],
        }

    async def increment_barcello_daily_color(
        self,
        guild_id: str,
        channel_id: str,
        day_date: str,
        color: str,
        ts: str,
    ) -> tuple[int, bool]:
        existing = await self.fetchone(
            """
            SELECT count
            FROM trigger_barcello_daily_state_stats
            WHERE guild_id = ? AND channel_id = ? AND day_date = ? AND color = ?
            """,
            (guild_id, channel_id, day_date, color),
        )
        if not existing:
            await self.execute(
                """
                INSERT INTO trigger_barcello_daily_state_stats (
                    guild_id, channel_id, day_date, color, count, first_seen_ts, last_seen_ts
                )
                VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (guild_id, channel_id, day_date, color, ts, ts),
            )
            return 1, True

        new_count = int(existing["count"] or 0) + 1
        await self.execute(
            """
            UPDATE trigger_barcello_daily_state_stats
            SET count = ?, last_seen_ts = ?
            WHERE guild_id = ? AND channel_id = ? AND day_date = ? AND color = ?
            """,
            (new_count, ts, guild_id, channel_id, day_date, color),
        )
        return new_count, False

    async def get_barcello_last_notified(self, guild_id: str, channel_id: str, color: str) -> Optional[str]:
        row = await self.fetchone(
            """
            SELECT last_notified_ts
            FROM trigger_barcello_notify_cooldown
            WHERE guild_id = ? AND channel_id = ? AND color = ?
            """,
            (guild_id, channel_id, color),
        )
        return str(row["last_notified_ts"]) if row and row["last_notified_ts"] else None

    async def set_barcello_last_notified(self, guild_id: str, channel_id: str, color: str, ts: str) -> None:
        await self.execute(
            """
            INSERT INTO trigger_barcello_notify_cooldown (guild_id, channel_id, color, last_notified_ts)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, channel_id, color) DO UPDATE SET
                last_notified_ts = excluded.last_notified_ts
            """,
            (guild_id, channel_id, color, ts),
        )

    async def add_trigger_phrase(
        self,
        guild_id: str,
        channel_id: str,
        phrase: str,
        match_mode: str,
        case_sensitive: bool,
        embed_color: str | None = None,
        cooldown_seconds: int | None = None,
        allowed_role_ids: list[str] | list[int] | None = None,
    ) -> None:
        serialized_role_ids = self._serialize_allowed_role_ids(allowed_role_ids)
        await self.execute(
            """
            INSERT INTO trigger_phrases (
                guild_id,
                channel_id,
                phrase,
                match_mode,
                case_sensitive,
                enabled,
                embed_color,
                cooldown_seconds,
                allowed_role_ids
            )
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT(guild_id, channel_id, phrase) DO UPDATE SET
                match_mode = excluded.match_mode,
                case_sensitive = excluded.case_sensitive,
                enabled = 1,
                embed_color = excluded.embed_color,
                cooldown_seconds = excluded.cooldown_seconds,
                allowed_role_ids = excluded.allowed_role_ids
            """,
            (
                guild_id,
                channel_id,
                phrase,
                match_mode,
                1 if case_sensitive else 0,
                embed_color,
                cooldown_seconds,
                serialized_role_ids,
            ),
        )

    async def remove_trigger_phrase(self, guild_id: str, channel_id: str, phrase: str) -> None:
        await self.execute(
            "DELETE FROM trigger_phrases WHERE guild_id = ? AND channel_id = ? AND phrase = ?",
            (guild_id, channel_id, phrase),
        )

    async def list_trigger_phrases(self, guild_id: str, channel_id: str) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            "SELECT * FROM trigger_phrases WHERE guild_id = ? AND channel_id = ? ORDER BY id ASC",
            (guild_id, channel_id),
        )
        return [self._normalize_trigger_phrase_row(row) for row in rows]

    async def list_trigger_phrases_guild(self, guild_id: str) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            "SELECT * FROM trigger_phrases WHERE guild_id = ? ORDER BY id ASC",
            (guild_id,),
        )
        return [self._normalize_trigger_phrase_row(row) for row in rows]

    async def get_matching_phrases(self, guild_id: str, channel_id: str) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            "SELECT * FROM trigger_phrases WHERE guild_id = ? AND channel_id = ? AND enabled = 1 ORDER BY id ASC",
            (guild_id, channel_id),
        )
        return [self._normalize_trigger_phrase_row(row) for row in rows]

    async def get_matching_phrases_guild(self, guild_id: str) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            "SELECT * FROM trigger_phrases WHERE guild_id = ? AND enabled = 1 ORDER BY id ASC",
            (guild_id,),
        )
        return [self._normalize_trigger_phrase_row(row) for row in rows]

    async def remove_trigger_phrase_guild(self, guild_id: str, phrase: str) -> None:
        await self.execute(
            "DELETE FROM trigger_phrases WHERE guild_id = ? AND phrase = ?",
            (guild_id, phrase),
        )

    async def remove_trigger_phrase_by_id(self, guild_id: str, phrase_id: int) -> None:
        await self.execute(
            "DELETE FROM trigger_phrases WHERE guild_id = ? AND id = ?",
            (guild_id, phrase_id),
        )

    async def get_trigger_phrase_by_id(self, guild_id: str, phrase_id: int) -> dict[str, Any]:
        row = await self.fetchone(
            "SELECT * FROM trigger_phrases WHERE guild_id = ? AND id = ?",
            (guild_id, phrase_id),
        )
        if row is None:
            return {}
        return self._normalize_trigger_phrase_row(row)

    async def update_trigger_phrase(
        self,
        guild_id: str,
        phrase_id: int,
        *,
        phrase: str | None = None,
        match_mode: str | None = None,
        embed_color: str | None = None,
        set_embed_color: bool = False,
        cooldown_seconds: int | None = None,
        set_cooldown_seconds: bool = False,
        allowed_role_ids: list[str] | list[int] | None = None,
        set_allowed_role_ids: bool = False,
        enabled: bool | None = None,
    ) -> bool:
        updates: list[str] = []
        params: list[Any] = []
        if phrase is not None:
            updates.append("phrase = ?")
            params.append(phrase)
        if match_mode is not None:
            updates.append("match_mode = ?")
            params.append(match_mode)
        if set_embed_color:
            updates.append("embed_color = ?")
            params.append(embed_color)
        if set_cooldown_seconds:
            updates.append("cooldown_seconds = ?")
            params.append(cooldown_seconds)
        if set_allowed_role_ids:
            updates.append("allowed_role_ids = ?")
            params.append(self._serialize_allowed_role_ids(allowed_role_ids))
        if enabled is not None:
            updates.append("enabled = ?")
            params.append(1 if enabled else 0)

        if not updates:
            return False
        params.extend([guild_id, phrase_id])
        await self.execute(
            f"UPDATE trigger_phrases SET {', '.join(updates)} WHERE guild_id = ? AND id = ?",
            tuple(params),
        )
        return True

    async def update_phrase_last_seen(self, phrase_id: int, ts: str, message_id: str) -> None:
        await self.execute(
            "UPDATE trigger_phrases SET last_seen_ts = ?, last_seen_message_id = ? WHERE id = ?",
            (ts, message_id, phrase_id),
        )

    async def upsert_trigger_phrase_milestone(self, phrase_id: int, threshold_count: int, template_text: str) -> None:
        await self.execute(
            """
            INSERT INTO trigger_phrase_milestones (phrase_id, threshold_count, template_text)
            VALUES (?, ?, ?)
            ON CONFLICT(phrase_id, threshold_count) DO UPDATE SET
                template_text = excluded.template_text
            """,
            (phrase_id, threshold_count, template_text),
        )

    async def delete_trigger_phrase_milestone(self, phrase_id: int, threshold_count: int) -> bool:
        existing = await self.fetchone(
            "SELECT 1 FROM trigger_phrase_milestones WHERE phrase_id = ? AND threshold_count = ?",
            (phrase_id, threshold_count),
        )
        if existing is None:
            return False
        await self.execute(
            "DELETE FROM trigger_phrase_milestones WHERE phrase_id = ? AND threshold_count = ?",
            (phrase_id, threshold_count),
        )
        return True

    async def list_trigger_phrase_milestones(self, phrase_id: int) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            """
            SELECT id, phrase_id, threshold_count, template_text, created_at
            FROM trigger_phrase_milestones
            WHERE phrase_id = ?
            ORDER BY threshold_count ASC
            """,
            (phrase_id,),
        )
        return [dict(row) for row in rows]

    async def get_trigger_phrase_milestone(self, phrase_id: int, threshold_count: int) -> dict[str, Any]:
        row = await self.fetchone(
            """
            SELECT id, phrase_id, threshold_count, template_text, created_at
            FROM trigger_phrase_milestones
            WHERE phrase_id = ? AND threshold_count = ?
            """,
            (phrase_id, threshold_count),
        )
        return dict(row) if row else {}

    async def set_trigger_phrase_global_milestone(self, guild_id: str, threshold_count: int, template_text: str) -> None:
        await self.execute(
            """
            INSERT INTO trigger_phrase_global_milestones (guild_id, threshold_count, template_text)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, threshold_count) DO UPDATE SET
                template_text = excluded.template_text
            """,
            (guild_id, threshold_count, template_text),
        )

    async def delete_trigger_phrase_global_milestone(self, guild_id: str, threshold_count: int) -> bool:
        existing = await self.fetchone(
            "SELECT 1 FROM trigger_phrase_global_milestones WHERE guild_id = ? AND threshold_count = ?",
            (guild_id, threshold_count),
        )
        if existing is None:
            return False
        await self.execute(
            "DELETE FROM trigger_phrase_global_milestones WHERE guild_id = ? AND threshold_count = ?",
            (guild_id, threshold_count),
        )
        return True

    async def list_trigger_phrase_global_milestones(self, guild_id: str) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            """
            SELECT id, guild_id, threshold_count, template_text, created_at
            FROM trigger_phrase_global_milestones
            WHERE guild_id = ?
            ORDER BY threshold_count ASC
            """,
            (guild_id,),
        )
        return [dict(row) for row in rows]

    async def get_trigger_phrase_global_milestone(self, guild_id: str, threshold_count: int) -> dict[str, Any]:
        row = await self.fetchone(
            """
            SELECT id, guild_id, threshold_count, template_text, created_at
            FROM trigger_phrase_global_milestones
            WHERE guild_id = ? AND threshold_count = ?
            """,
            (guild_id, threshold_count),
        )
        return dict(row) if row else {}

    async def upsert_trigger_phrase_global_user_custom_text(self, guild_id: str, user_id: str, custom_text: str) -> None:
        await self.execute(
            """
            INSERT INTO trigger_phrase_global_user_custom_phrases (guild_id, user_id, custom_text)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                custom_text = excluded.custom_text,
                updated_at = CURRENT_TIMESTAMP
            """,
            (guild_id, user_id, custom_text),
        )

    async def delete_trigger_phrase_global_user_custom_text(self, guild_id: str, user_id: str) -> bool:
        existing = await self.fetchone(
            "SELECT 1 FROM trigger_phrase_global_user_custom_phrases WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        if existing is None:
            return False
        await self.execute(
            "DELETE FROM trigger_phrase_global_user_custom_phrases WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        return True

    async def get_trigger_phrase_global_user_custom_text(self, guild_id: str, user_id: str) -> str:
        row = await self.fetchone(
            """
            SELECT custom_text
            FROM trigger_phrase_global_user_custom_phrases
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        )
        return str(row["custom_text"]) if row and row["custom_text"] is not None else ""

    async def list_trigger_phrase_global_user_custom_texts(self, guild_id: str) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            """
            SELECT guild_id, user_id, custom_text, created_at, updated_at
            FROM trigger_phrase_global_user_custom_phrases
            WHERE guild_id = ?
            ORDER BY updated_at DESC, user_id ASC
            """,
            (guild_id,),
        )
        return [dict(row) for row in rows]

    async def get_trigger_phrase_stats_summary(self, guild_id: str, phrase_id: int) -> dict[str, Any]:
        row = await self.fetchone(
            """
            SELECT
                p.id AS phrase_id,
                p.phrase AS phrase,
                p.last_seen_ts AS phrase_last_seen_ts,
                p.last_seen_message_id AS phrase_last_seen_message_id,
                COALESCE(COUNT(s.user_id), 0) AS unique_users,
                COALESCE(SUM(s.count), 0) AS total_uses,
                MAX(s.last_seen_ts) AS last_seen_ts_max,
                MIN(s.last_seen_ts) AS first_seen_ts_min
            FROM trigger_phrases p
            LEFT JOIN trigger_phrase_user_stats s ON s.phrase_id = p.id
            WHERE p.guild_id = ? AND p.id = ?
            GROUP BY p.id, p.phrase, p.last_seen_ts, p.last_seen_message_id
            """,
            (guild_id, phrase_id),
        )
        return dict(row) if row else {}

    async def list_trigger_phrase_user_stats(self, guild_id: str, phrase_id: int, limit: int = 10) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            """
            SELECT s.user_id, s.count, s.last_seen_ts, s.last_seen_message_id
            FROM trigger_phrase_user_stats s
            INNER JOIN trigger_phrases p ON p.id = s.phrase_id
            WHERE p.guild_id = ? AND p.id = ?
            ORDER BY s.count DESC, s.last_seen_ts DESC
            LIMIT ?
            """,
            (guild_id, phrase_id, limit),
        )
        return [dict(row) for row in rows]

    async def get_phrase_user_stats(self, phrase_id: int, user_id: str) -> dict[str, Any]:
        row = await self.fetchone(
            """
            SELECT phrase_id, user_id, count, last_seen_ts, last_seen_message_id
            FROM trigger_phrase_user_stats
            WHERE phrase_id = ? AND user_id = ?
            """,
            (phrase_id, user_id),
        )
        return dict(row) if row else {}

    async def increment_phrase_user_stats(self, phrase_id: int, user_id: str, ts: str, message_id: str) -> int:
        await self.execute(
            """
            INSERT INTO trigger_phrase_user_stats (phrase_id, user_id, count, last_seen_ts, last_seen_message_id)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(phrase_id, user_id) DO UPDATE SET
                count = trigger_phrase_user_stats.count + 1,
                last_seen_ts = excluded.last_seen_ts,
                last_seen_message_id = excluded.last_seen_message_id
            """,
            (phrase_id, user_id, ts, message_id),
        )
        row = await self.fetchone(
            "SELECT count FROM trigger_phrase_user_stats WHERE phrase_id = ? AND user_id = ?",
            (phrase_id, user_id),
        )
        return int(row["count"]) if row else 0

    async def get_trigger_state(self, guild_id: str, channel_id: str, trigger_key: str) -> dict[str, Any]:
        row = await self.fetchone(
            "SELECT state_json FROM trigger_state WHERE guild_id = ? AND channel_id = ? AND trigger_key = ?",
            (guild_id, channel_id, trigger_key),
        )
        if not row:
            return {}
        try:
            parsed = json.loads(str(row["state_json"] or "{}"))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    async def get_trigger_state_any_channel(
        self,
        guild_id: str,
        trigger_key: str,
        *,
        scope_channel_id: str = "__guild__",
    ) -> dict[str, Any]:
        global_state = await self.get_trigger_state(guild_id, scope_channel_id, trigger_key)
        if global_state:
            return global_state
        row = await self.fetchone(
            """
            SELECT state_json
            FROM trigger_state
            WHERE guild_id = ? AND trigger_key = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (guild_id, trigger_key),
        )
        if not row:
            return {}
        try:
            parsed = json.loads(str(row["state_json"] or "{}"))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    async def set_trigger_state(self, guild_id: str, channel_id: str, trigger_key: str, state: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.execute(
            """
            INSERT INTO trigger_state (guild_id, channel_id, trigger_key, state_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, channel_id, trigger_key) DO UPDATE SET
                state_json = excluded.state_json,
                updated_at = excluded.updated_at
            """,
            (guild_id, channel_id, trigger_key, json.dumps(state, ensure_ascii=False), now),
        )

    async def set_trigger_state_global(
        self,
        guild_id: str,
        trigger_key: str,
        state: dict[str, Any],
        *,
        scope_channel_id: str = "__guild__",
    ) -> None:
        await self.set_trigger_state(guild_id, scope_channel_id, trigger_key, state)

    async def get_trigger_phrase_global_milestones_enabled(self, guild_id: str) -> bool:
        state = await self.get_trigger_state_any_channel(guild_id, "frasi")
        value = state.get("global_milestones_enabled")
        return bool(value) if isinstance(value, bool) else False

    async def set_trigger_phrase_global_milestones_enabled(self, guild_id: str, enabled: bool) -> None:
        state = await self.get_trigger_state_any_channel(guild_id, "frasi")
        normalized = dict(state) if isinstance(state, dict) else {}
        normalized["global_milestones_enabled"] = bool(enabled)
        await self.set_trigger_state_global(guild_id, "frasi", normalized)

    async def get_cache(self, key: str) -> Optional[str]:
        now = datetime.now(timezone.utc).isoformat()
        row = await self.fetchone(
            "SELECT value FROM kv_cache WHERE key = ? AND expires_at > ?",
            (key, now),
        )
        if not row:
            await self.execute("DELETE FROM kv_cache WHERE key = ? AND expires_at <= ?", (key, now))
            return None
        return str(row["value"])

    async def set_cache(self, key: str, value: str, ttl_seconds: int) -> None:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=max(1, ttl_seconds))
        await self.execute(
            """
            INSERT INTO kv_cache (key, value, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                expires_at = excluded.expires_at,
                created_at = excluded.created_at
            """,
            (key, value, expires_at.isoformat(), now.isoformat()),
        )

    async def insert_user_hobby(
        self,
        guild_id: str,
        user_id: str,
        user_name: str,
        hobby: str,
        source_channel_id: str,
        source_message_id: str,
        source_created_at: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.execute(
            """
            INSERT OR IGNORE INTO user_hobbies (
                guild_id, user_id, user_name, hobby, source_channel_id, source_message_id, source_created_at, created_at, last_used_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (guild_id, user_id, user_name, hobby, source_channel_id, source_message_id, source_created_at, now),
        )

    async def list_recent_messages_for_hobbies(
        self,
        guild_id: str,
        channel_id: str,
        limit: int = 60,
    ) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            """
            SELECT
                m.message_id,
                m.guild_id,
                m.channel_id,
                m.author_id,
                m.ts,
                m.content,
                COALESCE(gm.nickname, u.display_name, u.global_name, u.username, m.author_id) AS user_name
            FROM messages m
            LEFT JOIN users u ON u.user_id = m.author_id
            LEFT JOIN guild_memberships gm ON gm.guild_id = m.guild_id AND gm.user_id = m.author_id
            WHERE m.guild_id = ? AND m.channel_id = ? AND COALESCE(m.is_deleted, 0) = 0 AND COALESCE(m.content, '') <> ''
            ORDER BY m.ts DESC
            LIMIT ?
            """,
            (guild_id, channel_id, limit),
        )
        return [dict(row) for row in rows]

    async def get_next_hobby(
        self,
        guild_id: str,
        channel_id: str,
        not_used_since_iso: str,
    ) -> Optional[dict[str, Any]]:
        row = await self.fetchone(
            """
            SELECT * FROM user_hobbies
            WHERE guild_id = ?
              AND source_channel_id = ?
              AND (last_used_at IS NULL OR last_used_at < ?)
            ORDER BY COALESCE(last_used_at, '1970-01-01T00:00:00+00:00') ASC, source_created_at DESC
            LIMIT 1
            """,
            (guild_id, channel_id, not_used_since_iso),
        )
        if row:
            return dict(row)
        fallback = await self.fetchone(
            """
            SELECT * FROM user_hobbies
            WHERE guild_id = ?
              AND (last_used_at IS NULL OR last_used_at < ?)
            ORDER BY COALESCE(last_used_at, '1970-01-01T00:00:00+00:00') ASC, source_created_at DESC
            LIMIT 1
            """,
            (guild_id, not_used_since_iso),
        )
        return dict(fallback) if fallback else None

    async def mark_hobby_used(self, guild_id: str, user_id: str, hobby: str, source_message_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.execute(
            """
            UPDATE user_hobbies
            SET last_used_at = ?
            WHERE guild_id = ? AND user_id = ? AND hobby = ? AND source_message_id = ?
            """,
            (now, guild_id, user_id, hobby, source_message_id),
        )


    async def get_qna_bonus(self, guild_id: str, user_id: str) -> tuple[int, Optional[str]]:
        row = await self.fetchone(
            "SELECT bonus, expires_at FROM qna_user_bonus WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        if not row:
            return 0, None
        expires_at = row["expires_at"]
        if expires_at:
            try:
                if datetime.fromisoformat(str(expires_at)) <= datetime.now(timezone.utc):
                    await self.clear_qna_bonus(guild_id, user_id)
                    return 0, None
            except ValueError:
                await self.clear_qna_bonus(guild_id, user_id)
                return 0, None
        return int(row["bonus"] or 0), str(expires_at) if expires_at else None

    async def set_qna_bonus(self, guild_id: str, user_id: str, bonus: int, expires_at: Optional[str]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.execute(
            """
            INSERT INTO qna_user_bonus (guild_id, user_id, bonus, expires_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                bonus = excluded.bonus,
                expires_at = excluded.expires_at,
                updated_at = excluded.updated_at
            """,
            (guild_id, user_id, bonus, expires_at, now),
        )

    async def clear_qna_bonus(self, guild_id: str, user_id: str) -> None:
        await self.execute(
            "DELETE FROM qna_user_bonus WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
    async def get_usage(self, guild_id: str, user_id: str, command: str, window_date: str) -> int:
        row = await self.fetch_usage_counter(guild_id, user_id, command, window_date)
        if not row:
            return 0
        return int(row["used_count"])

    async def increment_usage(self, guild_id: str, user_id: str, command: str, window_date: str, ts: str) -> int:
        current = await self.get_usage(guild_id, user_id, command, window_date)
        new_value = current + 1
        await self.upsert_usage_counter(guild_id, user_id, command, window_date, new_value, ts)
        return new_value

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

    async def close_open_voice_sessions(
        self,
        *,
        ended_ts: str,
        source: str | None = None,
        started_before_ts: str | None = None,
    ) -> int:
        assert self._conn is not None
        where_clauses = ["ended_ts IS NULL"]
        params: list[str] = [ended_ts]
        if source:
            where_clauses.append("(meta_json IS NOT NULL AND meta_json LIKE ?)")
            params.append(f'%"source"%{source}%')
        if started_before_ts:
            where_clauses.append("started_ts < ?")
            params.append(started_before_ts)
        query = f"UPDATE voice_sessions SET ended_ts = ? WHERE {' AND '.join(where_clauses)}"
        cursor = await self._conn.execute(query, tuple(params))
        await self._conn.commit()
        return cursor.rowcount

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


    def _validate_hhmm(self, value: str) -> str:
        parsed = datetime.strptime(value, "%H:%M")
        return parsed.strftime("%H:%M")

    async def upsert_daily_report_channel(self, guild_id: str, channel_id: str, enabled: bool | int, send_time_local: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        safe_time = self._validate_hhmm(send_time_local)
        await self.execute(
            """
            INSERT INTO daily_reports (guild_id, channel_id, enabled, send_time_local, last_sent_local_date, created_at, updated_at)
            VALUES (?, ?, ?, ?, NULL, ?, ?)
            ON CONFLICT(guild_id, channel_id) DO UPDATE SET
                enabled = excluded.enabled,
                send_time_local = excluded.send_time_local,
                updated_at = excluded.updated_at
            """,
            (guild_id, channel_id, 1 if bool(enabled) else 0, safe_time, now, now),
        )

    async def set_daily_report_enabled(self, guild_id: str, channel_id: str, enabled: bool) -> None:
        row = await self.get_daily_report_config(guild_id, channel_id)
        send_time = str(row["send_time_local"]) if row else "00:00"
        await self.upsert_daily_report_channel(guild_id, channel_id, enabled, send_time)

    async def set_daily_report_time(self, guild_id: str, channel_id: str, send_time_local: str) -> None:
        row = await self.get_daily_report_config(guild_id, channel_id)
        enabled = bool(row["enabled"]) if row else False
        await self.upsert_daily_report_channel(guild_id, channel_id, enabled, send_time_local)

    async def get_daily_report_config(self, guild_id: str, channel_id: str) -> Optional[aiosqlite.Row]:
        return await self.fetchone(
            "SELECT guild_id, channel_id, enabled, send_time_local, last_sent_local_date, last_sent_time_local, last_sent_kind FROM daily_reports WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )

    async def list_enabled_daily_report_channels(self, guild_id: str) -> list[aiosqlite.Row]:
        return await self.fetchall(
            "SELECT channel_id, send_time_local, last_sent_local_date, last_sent_time_local, last_sent_kind FROM daily_reports WHERE guild_id = ? AND enabled = 1",
            (guild_id,),
        )

    async def mark_daily_report_sent(
        self,
        guild_id: str,
        channel_id: str,
        local_date_str: str,
        *,
        local_time_str: str,
        sent_kind: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        safe_time = self._validate_hhmm(local_time_str)
        kind = sent_kind if sent_kind in {"scheduled", "manual"} else "scheduled"
        await self.execute(
            """
            UPDATE daily_reports
            SET last_sent_local_date = ?, last_sent_time_local = ?, last_sent_kind = ?, updated_at = ?
            WHERE guild_id = ? AND channel_id = ?
            """,
            (local_date_str, safe_time, kind, now, guild_id, channel_id),
        )

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

    async def set_activity_channel_enabled(self, guild_id: str, channel_id: str, enabled: bool) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.execute(
            """
            INSERT INTO activity_channels (guild_id, channel_id, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, channel_id) DO UPDATE SET
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (guild_id, channel_id, 1 if enabled else 0, now, now),
        )

    async def get_activity_channel_status(self, guild_id: str, channel_id: str) -> bool:
        row = await self.fetchone(
            "SELECT enabled FROM activity_channels WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
        return bool(row["enabled"]) if row else False

    async def list_enabled_activity_channels(self, guild_id: str) -> list[str]:
        rows = await self.fetchall(
            "SELECT channel_id FROM activity_channels WHERE guild_id = ? AND enabled = 1",
            (guild_id,),
        )
        return [str(row["channel_id"]) for row in rows]

    async def count_messages_in_range_single_channel(self, guild_id: str, channel_id: str, start_ts: str, end_ts: str) -> int:
        row = await self.fetchone(
            """
            SELECT COUNT(*) AS total
            FROM messages
            WHERE guild_id = ? AND channel_id = ? AND ts >= ? AND ts <= ? AND COALESCE(is_deleted, 0) = 0
            """,
            (guild_id, channel_id, start_ts, end_ts),
        )
        return int(row["total"] or 0) if row else 0

    async def count_user_messages_in_range(
        self,
        guild_id: str,
        user_id: str,
        start_ts: str,
        end_ts: str,
        *,
        channel_ids: list[str] | None = None,
    ) -> int:
        query = (
            "SELECT COUNT(*) AS total FROM messages "
            "WHERE guild_id = ? AND author_id = ? AND ts >= ? AND ts <= ? AND COALESCE(is_deleted, 0) = 0"
        )
        params: list[str] = [guild_id, user_id, start_ts, end_ts]
        if channel_ids:
            placeholders = ",".join("?" for _ in channel_ids)
            query += f" AND channel_id IN ({placeholders})"
            params.extend(channel_ids)
        row = await self.fetchone(query, tuple(params))
        return int(row["total"] or 0) if row else 0

    async def fetch_user_messages_in_range(
        self,
        guild_id: str,
        user_id: str,
        start_ts: str,
        end_ts: str,
        *,
        channel_ids: list[str] | None = None,
    ) -> list[dict[str, str | None]]:
        query = (
            "SELECT message_id, channel_id, ts, content, reply_to_message_id, mentions_json "
            "FROM messages WHERE guild_id = ? AND author_id = ? AND ts >= ? AND ts <= ? "
            "AND COALESCE(is_deleted, 0) = 0"
        )
        params: list[str] = [guild_id, user_id, start_ts, end_ts]
        if channel_ids:
            placeholders = ",".join("?" for _ in channel_ids)
            query += f" AND channel_id IN ({placeholders})"
            params.extend(channel_ids)
        query += " ORDER BY ts ASC"
        rows = await self.fetchall(query, tuple(params))
        out: list[dict[str, str | None]] = []
        for row in rows:
            out.append(
                {
                    "message_id": str(row["message_id"]) if row["message_id"] else None,
                    "channel_id": str(row["channel_id"]) if row["channel_id"] else None,
                    "ts": str(row["ts"]) if row["ts"] else None,
                    "content": str(row["content"]) if row["content"] else "",
                    "reply_to_message_id": str(row["reply_to_message_id"]) if row["reply_to_message_id"] else None,
                    "mentions_json": str(row["mentions_json"]) if row["mentions_json"] else None,
                }
            )
        return out

    async def fetch_message_author_id(self, guild_id: str, message_id: str) -> str | None:
        row = await self.fetchone(
            "SELECT author_id FROM messages WHERE guild_id = ? AND message_id = ? AND COALESCE(is_deleted, 0) = 0",
            (guild_id, message_id),
        )
        if not row or not row["author_id"]:
            return None
        return str(row["author_id"])

    async def count_active_users_in_range_single_channel(self, guild_id: str, channel_id: str, start_ts: str, end_ts: str) -> int:
        row = await self.fetchone(
            """
            SELECT COUNT(DISTINCT author_id) AS total
            FROM messages
            WHERE guild_id = ? AND channel_id = ? AND ts >= ? AND ts <= ? AND COALESCE(is_deleted, 0) = 0
            """,
            (guild_id, channel_id, start_ts, end_ts),
        )
        return int(row["total"] or 0) if row else 0

    async def fetch_user_counts_in_range_channel(self, guild_id: str, channel_id: str, start_ts: str, end_ts: str) -> dict[int, int]:
        rows = await self.fetchall(
            """
            SELECT author_id, COUNT(*) AS c
            FROM messages
            WHERE guild_id = ? AND channel_id = ? AND ts >= ? AND ts <= ? AND COALESCE(is_deleted, 0) = 0
            GROUP BY author_id
            """,
            (guild_id, channel_id, start_ts, end_ts),
        )
        result: dict[int, int] = {}
        for row in rows:
            try:
                result[int(row["author_id"])] = int(row["c"])
            except Exception:
                continue
        return result

    async def fetch_distinct_authors_in_range_channel(self, guild_id: str, channel_id: str, start_ts: str, end_ts: str) -> set[int]:
        rows = await self.fetchall(
            """
            SELECT DISTINCT author_id
            FROM messages
            WHERE guild_id = ? AND channel_id = ? AND ts >= ? AND ts <= ? AND COALESCE(is_deleted, 0) = 0
            """,
            (guild_id, channel_id, start_ts, end_ts),
        )
        result: set[int] = set()
        for row in rows:
            try:
                result.add(int(row["author_id"]))
            except Exception:
                continue
        return result

    async def fetch_user_last_message_in_range_channel(
        self,
        guild_id: str,
        channel_id: str,
        start_ts: str,
        end_ts: str,
    ) -> dict[int, tuple[str, str | None]]:
        rows = await self.fetchall(
            """
            SELECT m.author_id, m.ts, m.message_id
            FROM messages m
            JOIN (
                SELECT author_id, MAX(ts) AS max_ts
                FROM messages
                WHERE guild_id = ? AND channel_id = ? AND ts >= ? AND ts <= ? AND COALESCE(is_deleted, 0) = 0
                GROUP BY author_id
            ) x
              ON x.author_id = m.author_id AND x.max_ts = m.ts
            WHERE m.guild_id = ? AND m.channel_id = ? AND m.ts >= ? AND m.ts <= ? AND COALESCE(m.is_deleted, 0) = 0
            """,
            (guild_id, channel_id, start_ts, end_ts, guild_id, channel_id, start_ts, end_ts),
        )
        result: dict[int, tuple[str, str | None]] = {}
        for row in rows:
            try:
                aid = int(row["author_id"])
            except Exception:
                continue
            ts = str(row["ts"])
            message_id = str(row["message_id"]) if row["message_id"] else None
            prev = result.get(aid)
            if prev is None or ts > prev[0]:
                result[aid] = (ts, message_id)
        return result

    async def fetch_user_last_message_in_channel_since(
        self,
        guild_id: str,
        channel_id: str,
        since_ts: str,
    ) -> dict[int, tuple[str, str | None]]:
        rows = await self.fetchall(
            """
            SELECT m.author_id, m.ts, m.message_id
            FROM messages m
            JOIN (
                SELECT author_id, MAX(ts) AS max_ts
                FROM messages
                WHERE guild_id = ? AND channel_id = ? AND ts >= ? AND COALESCE(is_deleted, 0) = 0
                GROUP BY author_id
            ) x
              ON x.author_id = m.author_id AND x.max_ts = m.ts
            WHERE m.guild_id = ? AND m.channel_id = ? AND m.ts >= ? AND COALESCE(m.is_deleted, 0) = 0
            """,
            (guild_id, channel_id, since_ts, guild_id, channel_id, since_ts),
        )
        result: dict[int, tuple[str, str | None]] = {}
        for row in rows:
            try:
                aid = int(row["author_id"])
            except Exception:
                continue
            ts = str(row["ts"])
            message_id = str(row["message_id"]) if row["message_id"] else None
            prev = result.get(aid)
            if prev is None or ts > prev[0]:
                result[aid] = (ts, message_id)
        return result

    async def fetch_user_timestamps_in_range_channel(
        self,
        guild_id: str,
        channel_id: str,
        start_ts: str,
        end_ts: str,
    ) -> list[tuple[int, str, str | None]]:
        rows = await self.fetchall(
            """
            SELECT author_id, ts, message_id
            FROM messages
            WHERE guild_id = ? AND channel_id = ? AND ts >= ? AND ts <= ? AND COALESCE(is_deleted, 0) = 0
            ORDER BY ts ASC
            """,
            (guild_id, channel_id, start_ts, end_ts),
        )
        result: list[tuple[int, str, str | None]] = []
        for row in rows:
            try:
                result.append((int(row["author_id"]), str(row["ts"]), str(row["message_id"]) if row["message_id"] else None))
            except Exception:
                continue
        return result

    async def top_authors_in_channel_range(
        self,
        guild_id: str,
        channel_id: str,
        start_ts: str,
        end_ts: str,
        limit: int,
    ) -> list[tuple[int, int]]:
        counts = await self.fetch_user_counts_in_range_channel(guild_id, channel_id, start_ts, end_ts)
        ordered = sorted(counts.items(), key=lambda item: item[1], reverse=True)
        return ordered[: max(1, int(limit))]

    async def fetch_message_timestamps_in_range_single_channel(
        self,
        guild_id: str,
        channel_id: str,
        start_ts: str,
        end_ts: str,
    ) -> list[str]:
        rows = await self.fetchall(
            """
            SELECT ts
            FROM messages
            WHERE guild_id = ? AND channel_id = ? AND ts >= ? AND ts <= ? AND COALESCE(is_deleted, 0) = 0
            ORDER BY ts ASC
            """,
            (guild_id, channel_id, start_ts, end_ts),
        )
        return [str(row["ts"]) for row in rows if row and row["ts"]]

    async def last_seen_by_user_in_channel(self, guild_id: str, channel_id: str, since_ts: str) -> dict[int, str]:
        latest = await self.fetch_user_last_message_in_channel_since(guild_id, channel_id, since_ts)
        return {uid: item[0] for uid, item in latest.items()}

    async def upsert_activity_monitoring_config(
        self,
        guild_id: str,
        *,
        enabled: bool,
        mod_channel_id: str | None,
        send_time_local: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        safe_time = self._validate_hhmm(send_time_local)
        await self.execute(
            """
            INSERT INTO activity_monitoring_config (guild_id, enabled, mod_channel_id, send_time_local, last_sent_local_date, created_at, updated_at)
            VALUES (?, ?, ?, ?, NULL, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                enabled = excluded.enabled,
                mod_channel_id = excluded.mod_channel_id,
                send_time_local = excluded.send_time_local,
                updated_at = excluded.updated_at
            """,
            (guild_id, 1 if enabled else 0, mod_channel_id, safe_time, now, now),
        )

    async def get_activity_monitoring_config(self, guild_id: str) -> Optional[aiosqlite.Row]:
        return await self.fetchone(
            "SELECT guild_id, enabled, mod_channel_id, send_time_local, last_sent_local_date FROM activity_monitoring_config WHERE guild_id = ?",
            (guild_id,),
        )

    async def list_enabled_activity_monitoring_configs(self) -> list[aiosqlite.Row]:
        return await self.fetchall(
            "SELECT guild_id, enabled, mod_channel_id, send_time_local, last_sent_local_date FROM activity_monitoring_config WHERE enabled = 1"
        )

    async def mark_activity_monitoring_sent(self, guild_id: str, local_date_str: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.execute(
            "UPDATE activity_monitoring_config SET last_sent_local_date = ?, updated_at = ? WHERE guild_id = ?",
            (local_date_str, now, guild_id),
        )

    async def create_message_campaign(
        self,
        *,
        guild_id: str,
        channel_id: str,
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
        embed_title: Optional[str] = None,
        embed_color: Optional[str] = None,
    ) -> int:
        assert self._conn is not None
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._conn.execute(
            """
            INSERT INTO message_campaigns (
                guild_id, channel_id, type, name, text, text_green, text_yellow, text_red, text_black, enabled, start_time_local, interval_minutes,
                jitter_seconds, only_if_idle_minutes, mood_mode, last_sent_at, next_run_at, created_by,
                created_at, updated_at, deleted_at, embed_title, embed_color
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                guild_id,
                channel_id,
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
                embed_title,
                embed_color,
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

    async def get_inactivity_config(self, guild_id: str) -> Optional[aiosqlite.Row]:
        return await self.fetchone("SELECT * FROM inactivity_config WHERE guild_id = ?", (guild_id,))

    async def upsert_inactivity_config(self, guild_id: str, **fields: Any) -> None:
        now = datetime.now(timezone.utc).isoformat()
        current = await self.get_inactivity_config(guild_id)
        base: dict[str, Any] = {
            "enabled": 0,
            "auto_enabled": 0,
            "grace_days_after_reminder": 7,
            "reminder_cooldown_days": 14,
            "ban_days": 7,
            "atrio_channel_id": None,
            "invite_url": None,
            "excluded_role_ids_json": "[]",
            "default_policy_json": '{"inactive_days":30,"window_days":30,"min_messages":1,"mode":"OR","min_account_age_days":0}',
            "dm_reminder_template": None,
            "dm_kick_template": None,
            "atrio_template": None,
            "created_at": now,
            "updated_at": now,
        }
        if current:
            for key in base:
                if key in current.keys():
                    base[key] = current[key]
        base.update(fields)
        base["updated_at"] = now
        columns = [
            "guild_id",
            "enabled",
            "auto_enabled",
            "grace_days_after_reminder",
            "reminder_cooldown_days",
            "ban_days",
            "atrio_channel_id",
            "invite_url",
            "excluded_role_ids_json",
            "default_policy_json",
            "dm_reminder_template",
            "dm_kick_template",
            "atrio_template",
            "updated_at",
            "created_at",
        ]
        values = [guild_id] + [base[col] for col in columns[1:]]
        placeholders = ", ".join("?" for _ in columns)
        update_cols = ", ".join(f"{col}=excluded.{col}" for col in columns[1:-1])
        await self.execute(
            f"INSERT INTO inactivity_config ({', '.join(columns)}) VALUES ({placeholders}) ON CONFLICT(guild_id) DO UPDATE SET {update_cols}",
            tuple(values),
        )

    async def set_inactivity_enabled(self, guild_id: str, enabled: bool) -> None:
        await self.upsert_inactivity_config(guild_id, enabled=1 if enabled else 0)

    async def set_inactivity_auto_enabled(self, guild_id: str, auto_enabled: bool) -> None:
        await self.upsert_inactivity_config(guild_id, auto_enabled=1 if auto_enabled else 0)

    async def upsert_inactivity_role_policy(self, guild_id: str, role_id: str, policy_json: str, priority: int) -> None:
        await self.execute(
            """
            INSERT INTO inactivity_role_policies (guild_id, role_id, priority, policy_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, role_id) DO UPDATE SET
                priority = excluded.priority,
                policy_json = excluded.policy_json
            """,
            (guild_id, role_id, int(priority), policy_json),
        )

    async def delete_inactivity_role_policy(self, guild_id: str, role_id: str) -> None:
        await self.execute("DELETE FROM inactivity_role_policies WHERE guild_id = ? AND role_id = ?", (guild_id, role_id))

    async def list_inactivity_role_policies(self, guild_id: str) -> list[aiosqlite.Row]:
        return await self.fetchall(
            "SELECT guild_id, role_id, priority, policy_json FROM inactivity_role_policies WHERE guild_id = ? ORDER BY priority DESC, role_id ASC",
            (guild_id,),
        )

    async def get_inactivity_user_state(self, guild_id: str, user_id: str) -> Optional[aiosqlite.Row]:
        return await self.fetchone("SELECT * FROM inactivity_user_state WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))

    async def fetch_inactivity_user_states(self, guild_id: str, user_ids: list[str]) -> dict[str, aiosqlite.Row]:
        if not user_ids:
            return {}
        placeholders = ", ".join("?" for _ in user_ids)
        rows = await self.fetchall(
            f"SELECT * FROM inactivity_user_state WHERE guild_id = ? AND user_id IN ({placeholders})",
            (guild_id, *user_ids),
        )
        return {str(row["user_id"]): row for row in rows}

    async def extend_user_grace(self, guild_id: str, user_id: str, ts_iso: str) -> None:
        await self.execute(
            """
            INSERT INTO inactivity_user_state (guild_id, user_id, last_reminder_at, reminder_count, last_kick_at)
            VALUES (?, ?, ?, 0, NULL)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                last_reminder_at = excluded.last_reminder_at
            """,
            (guild_id, user_id, ts_iso),
        )

    async def list_inactivity_banned_states(self, guild_id: str) -> list[aiosqlite.Row]:
        return await self.fetchall(
            "SELECT user_id, last_kick_at FROM inactivity_user_state WHERE guild_id = ? AND last_kick_at IS NOT NULL",
            (guild_id,),
        )

    async def mark_user_reminded(self, guild_id: str, user_id: str, ts_iso: str) -> None:
        await self.execute(
            """
            INSERT INTO inactivity_user_state (guild_id, user_id, last_reminder_at, reminder_count, last_kick_at)
            VALUES (?, ?, ?, 1, NULL)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                last_reminder_at = excluded.last_reminder_at,
                reminder_count = COALESCE(inactivity_user_state.reminder_count, 0) + 1
            """,
            (guild_id, user_id, ts_iso),
        )

    async def mark_user_kicked(self, guild_id: str, user_id: str, ts_iso: str) -> None:
        await self.execute(
            """
            INSERT INTO inactivity_user_state (guild_id, user_id, last_reminder_at, reminder_count, last_kick_at)
            VALUES (?, ?, NULL, 0, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                last_kick_at = excluded.last_kick_at
            """,
            (guild_id, user_id, ts_iso),
        )

    async def add_temp_ban(self, guild_id: str, user_id: str, unban_at: str, reason: str | None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.execute(
            """
            INSERT INTO temp_bans (guild_id, user_id, unban_at, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                unban_at = excluded.unban_at,
                reason = excluded.reason
            """,
            (guild_id, user_id, unban_at, reason, now),
        )

    async def list_due_temp_unbans(self, now_iso: str) -> list[aiosqlite.Row]:
        return await self.fetchall("SELECT guild_id, user_id, unban_at, reason, created_at FROM temp_bans WHERE unban_at <= ? ORDER BY unban_at ASC", (now_iso,))

    async def remove_temp_ban(self, guild_id: str, user_id: str) -> None:
        await self.execute("DELETE FROM temp_bans WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))

    async def fetch_last_message_ts_by_user_guild(self, guild_id: str) -> dict[int, str]:
        rows = await self.fetchall(
            """
            SELECT author_id, MAX(ts) AS last_ts
            FROM messages
            WHERE guild_id = ? AND COALESCE(is_deleted, 0) = 0
            GROUP BY author_id
            """,
            (guild_id,),
        )
        result: dict[int, str] = {}
        for row in rows:
            aid = row["author_id"]
            ts = row["last_ts"]
            if not aid or not ts:
                continue
            try:
                result[int(str(aid))] = str(ts)
            except Exception:
                continue
        return result

    async def fetch_last_message_info_by_user_guild(self, guild_id: str) -> dict[int, dict[str, str]]:
        rows = await self.fetchall(
            """
            SELECT m.author_id, m.ts AS last_ts, m.channel_id AS last_channel_id, m.message_id AS last_message_id
            FROM messages AS m
            INNER JOIN (
                SELECT author_id, MAX(ts) AS last_ts
                FROM messages
                WHERE guild_id = ? AND COALESCE(is_deleted, 0) = 0
                GROUP BY author_id
            ) AS latest
              ON latest.author_id = m.author_id AND latest.last_ts = m.ts
            WHERE m.guild_id = ? AND COALESCE(m.is_deleted, 0) = 0
            ORDER BY m.author_id ASC, m.message_id DESC
            """,
            (guild_id, guild_id),
        )
        result: dict[int, dict[str, str]] = {}
        for row in rows:
            aid = row["author_id"]
            if not aid:
                continue
            try:
                author_id = int(str(aid))
            except Exception:
                continue
            if author_id in result:
                continue
            ts = row["last_ts"]
            channel_id = row["last_channel_id"]
            message_id = row["last_message_id"]
            if not ts or not channel_id or not message_id:
                continue
            result[author_id] = {
                "ts": str(ts),
                "channel_id": str(channel_id),
                "message_id": str(message_id),
            }
        return result

    async def fetch_message_counts_by_user_since(self, guild_id: str, since_ts: str) -> dict[int, int]:
        rows = await self.fetchall(
            """
            SELECT author_id, COUNT(*) AS cnt
            FROM messages
            WHERE guild_id = ? AND ts >= ? AND COALESCE(is_deleted, 0) = 0
            GROUP BY author_id
            """,
            (guild_id, since_ts),
        )
        result: dict[int, int] = {}
        for row in rows:
            aid = row["author_id"]
            cnt = row["cnt"]
            if not aid:
                continue
            try:
                result[int(str(aid))] = int(cnt)
            except Exception:
                continue
        return result



    async def upsert_aura_rolling_on_message(self, *, guild_id: str, user_id: str, window_key: str, ts: str, unique_increment: int) -> None:
        await self.execute(
            """
            INSERT INTO aura_user_rolling_stats (guild_id, user_id, window_key, msg_count, unique_interactions, quality_counter, last_activity_at)
            VALUES (?, ?, ?, 1, ?, 1, ?)
            ON CONFLICT(guild_id, user_id, window_key) DO UPDATE SET
                msg_count = aura_user_rolling_stats.msg_count + 1,
                unique_interactions = aura_user_rolling_stats.unique_interactions + excluded.unique_interactions,
                quality_counter = aura_user_rolling_stats.quality_counter + 1,
                last_activity_at = excluded.last_activity_at
            """,
            (guild_id, user_id, window_key, max(unique_increment, 1), ts),
        )

    async def upsert_aura_rolling_on_barcello(self, *, guild_id: str, user_id: str, window_key: str, ts: str, invigorate: bool) -> None:
        col = "invigorate_events" if invigorate else "degrade_events"
        await self.execute(
            f"""
            INSERT INTO aura_user_rolling_stats (guild_id, user_id, window_key, {col}, last_activity_at)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(guild_id, user_id, window_key) DO UPDATE SET
                {col} = aura_user_rolling_stats.{col} + 1,
                last_activity_at = excluded.last_activity_at
            """,
            (guild_id, user_id, window_key, ts),
        )

    async def fetch_recent_active_users(self, guild_id: str, ts: str, minutes: int = 30) -> list[str]:
        end_dt = datetime.fromisoformat(ts)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        start_ts = (end_dt - timedelta(minutes=minutes)).isoformat()
        rows = await self.fetchall(
            """
            SELECT DISTINCT author_id FROM messages
            WHERE guild_id = ? AND ts >= ? AND ts <= ? AND COALESCE(is_deleted, 0) = 0
            """,
            (guild_id, start_ts, end_dt.isoformat()),
        )
        return [str(r["author_id"]) for r in rows if r["author_id"]]

    async def upsert_aura_user_profile(self, *, guild_id: str, user_id: str, eligible: int, eligibility_reason: str, role_tier: str, last_computed_at: str) -> None:
        await self.execute(
            """
            INSERT INTO aura_user_profile (guild_id, user_id, eligible, eligibility_reason, role_tier, last_computed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                eligible = excluded.eligible,
                eligibility_reason = excluded.eligibility_reason,
                role_tier = excluded.role_tier,
                last_computed_at = excluded.last_computed_at
            """,
            (guild_id, user_id, eligible, eligibility_reason, role_tier, last_computed_at),
        )

    async def fetch_aura_metrics(self, guild_id: str, user_id: str, start_ts: str, end_ts: str, *, channel_id: str | None = None) -> dict[str, int]:
        params: list[str] = [guild_id, user_id, start_ts, end_ts]
        extra = ""
        if channel_id:
            extra = " AND channel_id = ?"
            params.append(channel_id)
        msg_row = await self.fetchone(
            f"""
            SELECT COUNT(*) AS msg_count,
                   SUM(CASE WHEN reply_to_message_id IS NOT NULL THEN 1 ELSE 0 END) AS replied
            FROM messages
            WHERE guild_id = ? AND author_id = ? AND ts >= ? AND ts <= ? AND COALESCE(is_deleted, 0) = 0 {extra}
            """,
            tuple(params),
        )
        rolling_row = await self.fetchone(
            """
            SELECT SUM(unique_interactions) AS unique_interactions,
                   SUM(degrade_events) AS degrade_events,
                   SUM(invigorate_events) AS invigorate_events,
                   SUM(quality_counter) AS quality_counter
            FROM aura_user_rolling_stats
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        )
        return {
            "msg_count": int(msg_row["msg_count"] or 0) if msg_row else 0,
            "reply_received": int(msg_row["replied"] or 0) if msg_row else 0,
            "unique_interactions": int(rolling_row["unique_interactions"] or 0) if rolling_row else 0,
            "degrade_events": int(rolling_row["degrade_events"] or 0) if rolling_row else 0,
            "invigorate_events": int(rolling_row["invigorate_events"] or 0) if rolling_row else 0,
            "quality_counter": int(rolling_row["quality_counter"] or 0) if rolling_row else 0,
        }

    async def count_user_messages_for_day(self, guild_id: str, user_id: str, day_iso: str) -> int:
        row = await self.fetchone(
            """
            SELECT COUNT(*) AS cnt
            FROM messages
            WHERE guild_id = ? AND author_id = ? AND substr(ts, 1, 10) = ? AND COALESCE(is_deleted, 0) = 0
            """,
            (guild_id, user_id, day_iso),
        )
        return int(row["cnt"] or 0) if row else 0

    async def count_user_distinct_channels_for_day(self, guild_id: str, user_id: str, day_iso: str) -> int:
        row = await self.fetchone(
            """
            SELECT COUNT(DISTINCT channel_id) AS cnt
            FROM messages
            WHERE guild_id = ? AND author_id = ? AND substr(ts, 1, 10) = ? AND COALESCE(is_deleted, 0) = 0
            """,
            (guild_id, user_id, day_iso),
        )
        return int(row["cnt"] or 0) if row else 0

    async def count_guild_good_morning_before(self, guild_id: str, day_iso: str, before_ts: str, keywords: list[str]) -> int:
        rows = await self.fetchall(
            """
            SELECT content FROM messages
            WHERE guild_id = ? AND substr(ts, 1, 10) = ? AND ts < ? AND COALESCE(is_deleted, 0) = 0
            """,
            (guild_id, day_iso, before_ts),
        )
        lowered = [str(k).lower() for k in keywords if str(k).strip()]
        count = 0
        for row in rows:
            content = str(row["content"] or "").lower()
            if any(k in content for k in lowered):
                count += 1
        return count

    async def upsert_aura_result(self, *, guild_id: str, user_id: str, channel_id: str | None, period_start: str, period_end: str, karma_percent: int, trend_delta: int, points_total: int, metrics_json: str, computed_at: str) -> None:
        await self.execute(
            """
            INSERT INTO aura_results (guild_id, user_id, channel_id, period_start, period_end, karma_percent, trend_delta, points_total, metrics_json, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, channel_id, period_start, period_end) DO UPDATE SET
                karma_percent = excluded.karma_percent,
                trend_delta = excluded.trend_delta,
                points_total = excluded.points_total,
                metrics_json = excluded.metrics_json,
                computed_at = excluded.computed_at
            """,
            (guild_id, user_id, channel_id, period_start, period_end, karma_percent, trend_delta, points_total, metrics_json, computed_at),
        )

    async def fetch_latest_aura_result(self, guild_id: str, user_id: str, period_start: str, period_end: str, *, channel_id: str | None = None) -> Optional[aiosqlite.Row]:
        return await self.fetchone(
            """
            SELECT * FROM aura_results
            WHERE guild_id = ? AND user_id = ? AND period_start = ? AND period_end = ?
              AND ((channel_id IS NULL AND ? IS NULL) OR channel_id = ?)
            ORDER BY computed_at DESC LIMIT 1
            """,
            (guild_id, user_id, period_start, period_end, channel_id, channel_id),
        )

    async def fetch_latest_aura_result_covering_window(self, guild_id: str, user_id: str, period_start: str, period_end: str, *, channel_id: str | None = None) -> Optional[aiosqlite.Row]:
        return await self.fetchone(
            """
            SELECT * FROM aura_results
            WHERE guild_id = ? AND user_id = ? AND period_start <= ? AND period_end >= ?
              AND ((channel_id IS NULL AND ? IS NULL) OR channel_id = ?)
            ORDER BY computed_at DESC LIMIT 1
            """,
            (guild_id, user_id, period_start, period_end, channel_id, channel_id),
        )

    async def fetch_user_channels_in_range(self, guild_id: str, user_id: str, start_ts: str, end_ts: str) -> list[str]:
        rows = await self.fetchall(
            """
            SELECT DISTINCT channel_id FROM messages
            WHERE guild_id = ? AND author_id = ? AND ts >= ? AND ts <= ? AND COALESCE(is_deleted, 0) = 0
            """,
            (guild_id, user_id, start_ts, end_ts),
        )
        return [str(r["channel_id"]) for r in rows if r["channel_id"]]

    async def insert_aura_ledger_event(
        self,
        guild_id: str,
        user_id: str,
        channel_id: str | None,
        ts: str,
        reason_code: str,
        delta_points: int,
        meta: dict[str, Any],
        *,
        event_id: str | None = None,
    ) -> str:
        ledger_id = (event_id or uuid.uuid4().hex).strip() or uuid.uuid4().hex
        await self.execute(
            "INSERT INTO aura_events_ledger (id, guild_id, user_id, channel_id, ts, reason_code, delta_points, meta_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ledger_id, guild_id, user_id, channel_id, ts, reason_code, delta_points, json.dumps(meta)),
        )
        return ledger_id

    async def aura_ledger_event_already_recorded(
        self,
        *,
        guild_id: str,
        user_id: str,
        reason_code: str,
        message_id: str,
        source_event: str,
        mission_id: str | None = None,
    ) -> bool:
        rows = await self.fetchall(
            """
            SELECT COALESCE(meta_json, '{}') AS meta_json
            FROM aura_events_ledger
            WHERE guild_id = ? AND user_id = ? AND reason_code = ?
            ORDER BY ts DESC
            LIMIT 200
            """,
            (guild_id, user_id, reason_code),
        )
        for row in rows:
            try:
                meta = json.loads(row["meta_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if str(meta.get("message_id") or "") != message_id:
                continue
            if str(meta.get("source_event") or "") != source_event:
                continue
            if mission_id is not None and str(meta.get("mission_id") or "") != mission_id:
                continue
            return True
        return False

    async def fetch_aura_ledger_aggregate(self, guild_id: str, user_id: str, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            """
            SELECT reason_code, SUM(delta_points) AS total
            FROM aura_events_ledger
            WHERE guild_id = ? AND user_id = ? AND ts >= ? AND ts <= ?
            GROUP BY reason_code
            ORDER BY total DESC
            """,
            (guild_id, user_id, start_ts, end_ts),
        )
        return [{"reason_code": str(r["reason_code"]), "total": int(r["total"] or 0)} for r in rows]

    async def fetch_aura_ledger_events(self, guild_id: str, user_id: str, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            """
            SELECT channel_id, ts, reason_code, delta_points, COALESCE(meta_json, '{}') AS meta_json
            FROM aura_events_ledger
            WHERE guild_id = ? AND user_id = ? AND ts >= ? AND ts <= ?
            ORDER BY ts DESC
            """,
            (guild_id, user_id, start_ts, end_ts),
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            meta_raw = row["meta_json"] or "{}"
            try:
                meta = json.loads(meta_raw)
            except json.JSONDecodeError:
                meta = {}
            out.append(
                {
                    "guild_id": guild_id,
                    "user_id": user_id,
                    "channel_id": str(row["channel_id"]) if row["channel_id"] else None,
                    "message_id": str(meta.get("message_id")) if meta.get("message_id") else None,
                    "ts": str(row["ts"]),
                    "reason_code": str(row["reason_code"]),
                    "delta_points": int(row["delta_points"] or 0),
                    "meta": meta,
                }
            )
        return out

    async def fetch_aura_ledger_report(self, guild_id: str, start_ts: str, end_ts: str) -> dict[str, Any]:
        totals = await self.fetchone(
            """
            SELECT
                SUM(CASE WHEN delta_points > 0 THEN delta_points ELSE 0 END) AS total_positive,
                SUM(CASE WHEN delta_points < 0 THEN delta_points ELSE 0 END) AS total_negative,
                COUNT(DISTINCT user_id) AS users_count
            FROM aura_events_ledger
            WHERE guild_id = ? AND ts >= ? AND ts <= ?
            """,
            (guild_id, start_ts, end_ts),
        )
        by_user = await self.fetchall(
            """
            SELECT user_id, SUM(delta_points) AS total
            FROM aura_events_ledger
            WHERE guild_id = ? AND ts >= ? AND ts <= ?
            GROUP BY user_id
            ORDER BY total DESC
            LIMIT 10
            """,
            (guild_id, start_ts, end_ts),
        )
        by_reason = await self.fetchall(
            """
            SELECT reason_code, SUM(delta_points) AS total, COUNT(*) AS cnt
            FROM aura_events_ledger
            WHERE guild_id = ? AND ts >= ? AND ts <= ?
            GROUP BY reason_code
            ORDER BY ABS(total) DESC
            LIMIT 10
            """,
            (guild_id, start_ts, end_ts),
        )
        by_channel = await self.fetchall(
            """
            SELECT channel_id, COUNT(*) AS cnt
            FROM aura_events_ledger
            WHERE guild_id = ? AND ts >= ? AND ts <= ?
            GROUP BY channel_id
            ORDER BY cnt DESC
            LIMIT 10
            """,
            (guild_id, start_ts, end_ts),
        )

        positives = [{"user_id": str(row["user_id"]), "total": int(row["total"] or 0)} for row in by_user if int(row["total"] or 0) > 0][:5]
        negatives = [
            {"user_id": str(row["user_id"]), "total": int(row["total"] or 0)}
            for row in sorted(by_user, key=lambda x: int(x["total"] or 0))
            if int(row["total"] or 0) < 0
        ][:5]

        return {
            "totals": {
                "positive": int((totals["total_positive"] if totals else 0) or 0),
                "negative": int((totals["total_negative"] if totals else 0) or 0),
                "users_count": int((totals["users_count"] if totals else 0) or 0),
            },
            "top_positive": positives,
            "top_negative": negatives,
            "by_reason": [
                {"reason_code": str(r["reason_code"]), "total": int(r["total"] or 0), "count": int(r["cnt"] or 0)}
                for r in by_reason
            ],
            "by_channel": [{"channel_id": str(r["channel_id"]) if r["channel_id"] else None, "count": int(r["cnt"] or 0)} for r in by_channel],
        }

    async def get_channel_name_map(self, guild_id: str) -> dict[str, str]:
        rows = await self.fetchall("SELECT channel_id, name FROM channels WHERE guild_id = ?", (guild_id,))
        return {str(r["channel_id"]): f"#{str(r['name'])}" for r in rows if r["channel_id"]}

    async def get_member_name_map(self, guild_id: str) -> dict[str, str]:
        rows = await self.fetchall("SELECT user_id, nickname FROM guild_memberships WHERE guild_id = ?", (guild_id,))
        out: dict[str, str] = {}
        for row in rows:
            uid = str(row["user_id"])
            nick = str(row["nickname"] or "").strip()
            out[uid] = nick or uid
        return out

    async def assign_aura_mission(
        self,
        *,
        guild_id: str,
        user_id: str,
        mission_id: str,
        assigned_at: str,
        due_date: str,
        reward_points: int,
        meta: dict[str, Any] | None = None,
    ) -> None:
        await self.execute(
            """
            INSERT INTO aura_mission_assignments (guild_id, user_id, mission_id, assigned_at, due_date, status, completed_at, reward_points, meta_json)
            VALUES (?, ?, ?, ?, ?, 'assigned', NULL, ?, ?)
            """,
            (guild_id, user_id, mission_id, assigned_at, due_date, int(reward_points), json.dumps(meta or {})),
        )

    async def complete_aura_mission(self, *, guild_id: str, user_id: str, mission_id: str, assigned_at: str, completed_at: str) -> None:
        await self.execute(
            """
            UPDATE aura_mission_assignments
            SET status = 'completed', completed_at = ?
            WHERE guild_id = ? AND user_id = ? AND mission_id = ? AND assigned_at = ? AND status = 'assigned'
            """,
            (completed_at, guild_id, user_id, mission_id, assigned_at),
        )

    async def expire_aura_missions(self, *, guild_id: str, user_id: str, now_ts: str) -> None:
        await self.execute(
            """
            UPDATE aura_mission_assignments
            SET status = 'expired'
            WHERE guild_id = ? AND user_id = ? AND status = 'assigned' AND due_date < ?
            """,
            (guild_id, user_id, now_ts),
        )

    async def list_aura_missions_for_user(self, guild_id: str, user_id: str, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            """
            SELECT *
            FROM aura_mission_assignments
            WHERE guild_id = ? AND user_id = ? AND assigned_at >= ? AND assigned_at <= ?
            ORDER BY assigned_at DESC
            """,
            (guild_id, user_id, start_ts, end_ts),
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                meta = json.loads(row["meta_json"] or "{}")
            except json.JSONDecodeError:
                meta = {}
            out.append(
                {
                    "mission_id": str(row["mission_id"]),
                    "assigned_at": str(row["assigned_at"]),
                    "due_date": str(row["due_date"]),
                    "status": str(row["status"]),
                    "completed_at": str(row["completed_at"]) if row["completed_at"] else None,
                    "reward_points": int(row["reward_points"] or 0),
                    "meta": meta,
                }
            )
        return out

    async def fetch_aura_mission_stats(self, guild_id: str, start_ts: str, end_ts: str) -> dict[str, int]:
        row = await self.fetchone(
            """
            SELECT
                COUNT(*) AS assigned_count,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_count,
                SUM(CASE WHEN status = 'assigned' THEN 1 ELSE 0 END) AS pending_count,
                COUNT(DISTINCT user_id) AS users_count
            FROM aura_mission_assignments
            WHERE guild_id = ? AND assigned_at >= ? AND assigned_at <= ?
            """,
            (guild_id, start_ts, end_ts),
        )
        if not row:
            return {"assigned_count": 0, "completed_count": 0, "pending_count": 0, "users_count": 0}
        return {
            "assigned_count": int(row["assigned_count"] or 0),
            "completed_count": int(row["completed_count"] or 0),
            "pending_count": int(row["pending_count"] or 0),
            "users_count": int(row["users_count"] or 0),
        }

    async def fetch_aura_ledger_events_for_guild(self, guild_id: str, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            """
            SELECT *
            FROM aura_events_ledger
            WHERE guild_id = ? AND ts >= ? AND ts <= ?
            ORDER BY ts ASC
            """,
            (guild_id, start_ts, end_ts),
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                meta = json.loads(row["meta_json"] or "{}")
            except json.JSONDecodeError:
                meta = {}
            out.append(
                {
                    "guild_id": str(row["guild_id"]),
                    "user_id": str(row["user_id"]),
                    "channel_id": str(row["channel_id"]) if row["channel_id"] else None,
                    "ts": str(row["ts"]),
                    "reason_code": str(row["reason_code"]),
                    "delta_points": int(row["delta_points"] or 0),
                    "meta": meta,
                }
            )
        return out

    async def fetch_aura_user_reason_totals(self, guild_id: str, user_id: str, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            """
            SELECT reason_code, SUM(delta_points) AS total
            FROM aura_events_ledger
            WHERE guild_id = ? AND user_id = ? AND ts >= ? AND ts <= ?
            GROUP BY reason_code
            ORDER BY ABS(total) DESC
            LIMIT 3
            """,
            (guild_id, user_id, start_ts, end_ts),
        )
        return [{"reason_code": str(r["reason_code"]), "total": int(r["total"] or 0)} for r in rows]

    async def sum_aura_points(self, guild_id: str, user_id: str, *, channel_id: str | None = None) -> int:
        row = await self.fetchone(
            """
            SELECT SUM(delta_points) AS total
            FROM aura_events_ledger
            WHERE guild_id = ? AND user_id = ?
              AND ((channel_id IS NULL AND ? IS NULL) OR channel_id = ?)
            """,
            (guild_id, user_id, channel_id, channel_id),
        )
        return int(row["total"] or 0) if row else 0

    async def upsert_archetype_profile(self, *, guild_id: str, user_id: str, period_days: int, archetype_scores_json: str, metrics_json: str, computed_at: str) -> None:
        await self.execute(
            """
            INSERT INTO archetype_profiles (guild_id, user_id, period_days, archetype_scores_json, metrics_json, computed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, period_days) DO UPDATE SET
                archetype_scores_json = excluded.archetype_scores_json,
                metrics_json = excluded.metrics_json,
                computed_at = excluded.computed_at
            """,
            (guild_id, user_id, period_days, archetype_scores_json, metrics_json, computed_at),
        )

    async def fetch_latest_archetype_profile(self, guild_id: str, user_id: str, period_days: int = 30) -> Optional[aiosqlite.Row]:
        return await self.fetchone(
            "SELECT * FROM archetype_profiles WHERE guild_id = ? AND user_id = ? AND period_days = ? ORDER BY computed_at DESC LIMIT 1",
            (guild_id, user_id, period_days),
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
