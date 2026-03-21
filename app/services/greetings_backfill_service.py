from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.database import DatabaseService

_MODERATION_ACTION_EVENT_TYPES = (
    "join",
    "leave",
    "kick",
    "ban",
    "unban",
    "tempban",
    "grace",
    "inactive_kick",
    "inactive_tempban",
    "inactive_grace",
)
_SUPPORTED_EVENT_TYPES = frozenset(_MODERATION_ACTION_EVENT_TYPES)
_EXPLICIT_DEPARTURE_TYPES = frozenset({"kick", "ban", "tempban", "inactive_kick", "inactive_tempban"})
_NON_DEPARTURE_TYPES = frozenset({"grace", "inactive_grace"})
_LEAVE_DEDUPE_WINDOW_SECONDS = 300
_INACTIVE_ABSORPTION_WINDOW_SECONDS = 600


@dataclass(frozen=True, slots=True)
class GreetingsBackfillRunResult:
    imported_count: int
    skipped_count: int
    canonical_count: int
    last_run_at: str | None


@dataclass(frozen=True, slots=True)
class _BackfillCandidate:
    source_kind: str
    source: str
    source_ref: str
    guild_id: str
    user_id: str
    event_type_key: str
    occurred_at: str
    moderator_id: str | None
    reason: str | None
    duration_seconds: int | None
    expires_at: str | None
    operation_id: str | None
    metadata: dict[str, Any]
    sort_order: int


class GreetingsBackfillService:
    """Rebuilds the canonical greetings timeline from raw historical sources.

    `moderation_actions` remains the raw audit trail.
    `member_flow_events` is the idempotent, canonical timeline consumed by
    greetings live rendering/counting/deduplication.
    """

    ENABLED_KEY = "greetings.backfill.enabled"
    LAST_RUN_AT_KEY = "greetings.backfill.last_run_at"
    LAST_RUN_IMPORTED_KEY = "greetings.backfill.last_run_imported_count"
    LAST_RUN_SKIPPED_KEY = "greetings.backfill.last_run_skipped_count"

    def __init__(self, database: DatabaseService) -> None:
        self._database = database
        self._lock = asyncio.Lock()
        self._enabled = False

    async def load_settings(self) -> None:
        stored = await self._database.get_setting(self.ENABLED_KEY)
        if stored is None:
            await self._database.set_setting(self.ENABLED_KEY, "false")
            self._enabled = False
            return
        self._enabled = str(stored).strip().lower() in {"1", "true", "yes", "y", "on"}

    async def is_enabled(self) -> bool:
        stored = await self._database.get_setting(self.ENABLED_KEY)
        if stored is None:
            await self._database.set_setting(self.ENABLED_KEY, "false")
            self._enabled = False
            return False
        self._enabled = str(stored).strip().lower() in {"1", "true", "yes", "y", "on"}
        return self._enabled

    async def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        await self._database.set_setting(self.ENABLED_KEY, "true" if enabled else "false")

    async def status(self, guild_id: str | None = None) -> dict[str, Any]:
        enabled = await self.is_enabled()
        canonical_count = await self._count_canonical_records(guild_id)
        return {
            "enabled": enabled,
            "last_run_at": await self._database.get_setting(self.LAST_RUN_AT_KEY),
            "last_run_imported_count": self._parse_optional_int(await self._database.get_setting(self.LAST_RUN_IMPORTED_KEY)),
            "last_run_skipped_count": self._parse_optional_int(await self._database.get_setting(self.LAST_RUN_SKIPPED_KEY)),
            "canonical_count": canonical_count,
        }

    async def run_once(self, *, guild_id: str | None = None) -> GreetingsBackfillRunResult:
        async with self._lock:
            if not await self.is_enabled():
                canonical_count = await self._count_canonical_records(guild_id)
                return GreetingsBackfillRunResult(imported_count=0, skipped_count=0, canonical_count=canonical_count, last_run_at=None)

            moderation_candidates = await self._load_moderation_candidates(guild_id)
            event_candidates = await self._load_event_fallback_candidates(guild_id, moderation_candidates)
            candidates = sorted([*moderation_candidates, *event_candidates], key=lambda item: (item.occurred_at, item.sort_order, item.source_ref))

            imported_count = 0
            skipped_count = 0
            inactive_tempban_index = self._index_inactive_tempbans(moderation_candidates)

            for candidate in candidates:
                imported = await self._import_candidate(candidate, inactive_tempban_index=inactive_tempban_index)
                if imported:
                    imported_count += 1
                else:
                    skipped_count += 1

            last_run_at = datetime.now(timezone.utc).isoformat()
            await self._database.set_setting(self.LAST_RUN_AT_KEY, last_run_at)
            await self._database.set_setting(self.LAST_RUN_IMPORTED_KEY, str(imported_count))
            await self._database.set_setting(self.LAST_RUN_SKIPPED_KEY, str(skipped_count))
            canonical_count = await self._count_canonical_records(guild_id)
            return GreetingsBackfillRunResult(
                imported_count=imported_count,
                skipped_count=skipped_count,
                canonical_count=canonical_count,
                last_run_at=last_run_at,
            )

    async def _count_canonical_records(self, guild_id: str | None) -> int:
        if guild_id is None:
            row = await self._database.fetchone("SELECT COUNT(*) AS total FROM member_flow_events")
        else:
            row = await self._database.fetchone(
                "SELECT COUNT(*) AS total FROM member_flow_events WHERE guild_id = ?",
                (guild_id,),
            )
        return int(row["total"] if row is not None else 0)

    async def _load_moderation_candidates(self, guild_id: str | None) -> list[_BackfillCandidate]:
        placeholders = ", ".join("?" for _ in _MODERATION_ACTION_EVENT_TYPES)
        filters = [f"action_type IN ({placeholders})"]
        params: list[Any] = [*_MODERATION_ACTION_EVENT_TYPES]
        if guild_id is not None:
            filters.append("guild_id = ?")
            params.append(guild_id)
        rows = await self._database.fetchall(
            f"""
            SELECT *
            FROM moderation_actions
            WHERE {' AND '.join(filters)}
            ORDER BY created_at ASC, id ASC
            """,
            tuple(params),
        )
        temp_ban_rows = await self._load_temp_ban_lookup(guild_id)
        inactivity_rows = await self._load_inactivity_state_lookup(guild_id)
        candidates: list[_BackfillCandidate] = []
        for row in rows:
            metadata = self._parse_metadata(row["metadata_json"])
            action_type = str(row["action_type"] or "").strip()
            if action_type not in _SUPPORTED_EVENT_TYPES:
                continue
            guild_value = str(row["guild_id"] or "").strip()
            user_value = str(row["user_id"] or "").strip()
            created_at = str(row["created_at"] or "").strip()
            action_id = str(row["id"] or "").strip()
            if not guild_value or not user_value or not created_at or not action_id:
                continue
            source = str(metadata.get("source") or "greetings_backfill")
            enriched_metadata = dict(metadata)
            expires_at = self._resolve_expires_at(action_type=action_type, row=row, temp_ban_rows=temp_ban_rows)
            state_key = (guild_value, user_value)
            state_row = inactivity_rows.get(state_key)
            if state_row is not None and action_type.startswith("inactive_"):
                if enriched_metadata.get("state_last_kick_at") is None and state_row.get("last_kick_at"):
                    enriched_metadata["state_last_kick_at"] = state_row["last_kick_at"]
                if enriched_metadata.get("reminder_count") is None:
                    enriched_metadata["reminder_count"] = int(state_row.get("reminder_count") or 0)
            candidates.append(
                _BackfillCandidate(
                    source_kind="moderation_actions",
                    source=source,
                    source_ref=f"moderation_actions:{action_id}",
                    guild_id=guild_value,
                    user_id=user_value,
                    event_type_key=action_type,
                    occurred_at=created_at,
                    moderator_id=str(row["moderator_id"]) if row["moderator_id"] is not None else None,
                    reason=str(row["reason"]) if row["reason"] is not None else None,
                    duration_seconds=int(row["duration_seconds"]) if row["duration_seconds"] is not None else None,
                    expires_at=expires_at,
                    operation_id=str(enriched_metadata["operation_id"]) if enriched_metadata.get("operation_id") else None,
                    metadata={
                        **enriched_metadata,
                        "raw_action_id": action_id,
                        "backfill_source": "moderation_actions",
                    },
                    sort_order=self._sort_order_for_event(action_type),
                )
            )
        return candidates

    async def _load_event_fallback_candidates(
        self,
        guild_id: str | None,
        moderation_candidates: list[_BackfillCandidate],
    ) -> list[_BackfillCandidate]:
        moderation_times: dict[tuple[str, str, str], list[datetime]] = {}
        for candidate in moderation_candidates:
            if candidate.event_type_key not in {"join", "leave"}:
                continue
            moderation_times.setdefault((candidate.guild_id, candidate.user_id, candidate.event_type_key), []).append(
                self._parse_iso(candidate.occurred_at)
            )

        filters = ["event_type IN ('member.join', 'member.leave')"]
        params: list[Any] = []
        if guild_id is not None:
            filters.append("guild_id = ?")
            params.append(guild_id)
        rows = await self._database.fetchall(
            f"""
            SELECT *
            FROM events
            WHERE {' AND '.join(filters)}
            ORDER BY ts ASC, id ASC
            """,
            tuple(params),
        )
        candidates: list[_BackfillCandidate] = []
        for row in rows:
            metadata = self._parse_metadata(row["meta_json"])
            event_type = str(row["event_type"] or "").strip()
            canonical_type = "join" if event_type == "member.join" else "leave"
            guild_value = str(row["guild_id"] or "").strip()
            occurred_at = str(row["ts"] or "").strip()
            event_id = str(row["id"] or "").strip()
            user_value = str(metadata.get("target_id") or row["actor_id"] or "").strip()
            if not guild_value or not user_value or not occurred_at or not event_id:
                continue
            if self._has_moderation_match(
                moderation_times.get((guild_value, user_value, canonical_type), []),
                self._parse_iso(occurred_at),
            ):
                continue
            candidates.append(
                _BackfillCandidate(
                    source_kind="events",
                    source="discord_adapter",
                    source_ref=f"events:{event_id}",
                    guild_id=guild_value,
                    user_id=user_value,
                    event_type_key=canonical_type,
                    occurred_at=occurred_at,
                    moderator_id=None,
                    reason="Ingresso nel server" if canonical_type == "join" else "Uscita dal server",
                    duration_seconds=None,
                    expires_at=None,
                    operation_id=None,
                    metadata={
                        **metadata,
                        "backfill_source": "events",
                        "event_id": event_id,
                    },
                    sort_order=self._sort_order_for_event(canonical_type),
                )
            )
        return candidates

    async def _load_temp_ban_lookup(self, guild_id: str | None) -> dict[tuple[str, str], list[dict[str, Any]]]:
        query = "SELECT guild_id, user_id, unban_at, reason, created_at FROM temp_bans"
        params: tuple[Any, ...] = ()
        if guild_id is not None:
            query += " WHERE guild_id = ?"
            params = (guild_id,)
        query += " ORDER BY created_at ASC"
        rows = await self._database.fetchall(query, params)
        lookup: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            lookup.setdefault((str(row["guild_id"]), str(row["user_id"])), []).append(dict(row))
        return lookup

    async def _load_inactivity_state_lookup(self, guild_id: str | None) -> dict[tuple[str, str], dict[str, Any]]:
        query = "SELECT guild_id, user_id, last_reminder_at, reminder_count, last_kick_at FROM inactivity_user_state"
        params: tuple[Any, ...] = ()
        if guild_id is not None:
            query += " WHERE guild_id = ?"
            params = (guild_id,)
        rows = await self._database.fetchall(query, params)
        return {(str(row["guild_id"]), str(row["user_id"])): dict(row) for row in rows}

    def _resolve_expires_at(self, *, action_type: str, row: Any, temp_ban_rows: dict[tuple[str, str], list[dict[str, Any]]]) -> str | None:
        stored = str(row["expires_at"]) if row["expires_at"] is not None else None
        if stored:
            return stored
        if action_type not in {"tempban", "inactive_tempban"}:
            return stored
        matches = temp_ban_rows.get((str(row["guild_id"]), str(row["user_id"])), [])
        if not matches:
            return None
        action_dt = self._parse_iso(str(row["created_at"]))
        for match in matches:
            match_dt = self._parse_iso(str(match["created_at"]))
            if abs((match_dt - action_dt).total_seconds()) <= _INACTIVE_ABSORPTION_WINDOW_SECONDS:
                return str(match["unban_at"])
        return str(matches[-1]["unban_at"])

    async def _import_candidate(
        self,
        candidate: _BackfillCandidate,
        *,
        inactive_tempban_index: dict[tuple[str, str], list[_BackfillCandidate]],
    ) -> bool:
        # Idempotenza forte: la timeline canonica non reinserisce lo stesso
        # evento se la sorgente raw è già stata importata una volta.
        existing = await self._database.find_member_flow_event_by_source_ref(source=candidate.source, source_ref=candidate.source_ref)
        if existing is not None:
            return False

        visible_in_greetings = await self._resolve_visibility(candidate, inactive_tempban_index=inactive_tempban_index)
        if candidate.event_type_key == "leave" and not visible_in_greetings:
            return False
        inserted = await self._database.insert_member_flow_event(
            guild_id=candidate.guild_id,
            user_id=candidate.user_id,
            event_type_key=candidate.event_type_key,
            occurred_at=candidate.occurred_at,
            moderator_id=candidate.moderator_id,
            reason=candidate.reason,
            duration_seconds=candidate.duration_seconds,
            expires_at=candidate.expires_at,
            source=candidate.source,
            source_ref=candidate.source_ref,
            operation_id=candidate.operation_id,
            visible_in_greetings=visible_in_greetings,
            metadata=candidate.metadata,
        )
        return inserted.get("source_ref") == candidate.source_ref and inserted.get("source") == candidate.source

    async def _resolve_visibility(
        self,
        candidate: _BackfillCandidate,
        *,
        inactive_tempban_index: dict[tuple[str, str], list[_BackfillCandidate]],
    ) -> bool:
        if candidate.event_type_key == "unban":
            # Canonical-only by default: retained for audit/history, hidden from
            # the greetings feed because it does not represent a visible
            # join/leave style transition on its own.
            metadata_visible = candidate.metadata.get("visible_in_greetings")
            return bool(metadata_visible) if metadata_visible is not None else False
        if candidate.event_type_key in _NON_DEPARTURE_TYPES:
            return False
        # Gli eventi di inattività restano distinti da quelli manuali e le
        # pipeline kick→tempban per inattività non devono produrre doppie uscite
        # visibili nella timeline greetings.
        if candidate.event_type_key == "inactive_kick" and self._inactive_kick_is_absorbed(candidate, inactive_tempban_index):
            return False
        if candidate.event_type_key == "leave":
            since = (self._parse_iso(candidate.occurred_at) - timedelta(seconds=_LEAVE_DEDUPE_WINDOW_SECONDS)).isoformat()
            recent = await self._database.list_recent_visible_departures(candidate.guild_id, candidate.user_id, since)
            if any(str(row.get("event_type_key") or "") in _EXPLICIT_DEPARTURE_TYPES for row in recent):
                return False
        metadata_visible = candidate.metadata.get("visible_in_greetings")
        if metadata_visible is not None:
            return bool(metadata_visible)
        return True

    def _inactive_kick_is_absorbed(
        self,
        candidate: _BackfillCandidate,
        inactive_tempban_index: dict[tuple[str, str], list[_BackfillCandidate]],
    ) -> bool:
        operation_key = None
        if candidate.operation_id:
            operation_key = (candidate.guild_id, candidate.operation_id)
            if inactive_tempban_index.get(operation_key):
                return True
        user_candidates = inactive_tempban_index.get((candidate.guild_id, candidate.user_id), [])
        current_dt = self._parse_iso(candidate.occurred_at)
        for later in user_candidates:
            later_dt = self._parse_iso(later.occurred_at)
            if 0 <= (later_dt - current_dt).total_seconds() <= _INACTIVE_ABSORPTION_WINDOW_SECONDS:
                return True
        return False

    def _index_inactive_tempbans(self, candidates: list[_BackfillCandidate]) -> dict[tuple[str, str], list[_BackfillCandidate]]:
        indexed: dict[tuple[str, str], list[_BackfillCandidate]] = {}
        for candidate in candidates:
            if candidate.event_type_key != "inactive_tempban":
                continue
            indexed.setdefault((candidate.guild_id, candidate.user_id), []).append(candidate)
            if candidate.operation_id:
                indexed.setdefault((candidate.guild_id, candidate.operation_id), []).append(candidate)
        return indexed

    def _has_moderation_match(self, moderation_dts: list[datetime], event_dt: datetime) -> bool:
        for item in moderation_dts:
            if abs((item - event_dt).total_seconds()) <= 30:
                return True
        return False

    @staticmethod
    def _sort_order_for_event(event_type_key: str) -> int:
        if event_type_key in _EXPLICIT_DEPARTURE_TYPES:
            return 0
        if event_type_key == "leave":
            return 1
        if event_type_key in _NON_DEPARTURE_TYPES:
            return 2
        return 3

    @staticmethod
    def _parse_metadata(raw: Any) -> dict[str, Any]:
        if raw is None:
            return {}
        try:
            parsed = json.loads(str(raw))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _parse_optional_int(raw: str | None) -> int | None:
        if raw is None:
            return None
        value = str(raw).strip()
        if not value:
            return None
        return int(value)

    @staticmethod
    def _parse_iso(raw: str) -> datetime:
        value = datetime.fromisoformat(raw)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
