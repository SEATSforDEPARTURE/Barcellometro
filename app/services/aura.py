from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import discord

from app.services.database import DatabaseService
from app.services.entitlements import EntitlementsService

logger = logging.getLogger(__name__)


@dataclass
class AuraEligibilityResult:
    eligible: bool
    reason: str


def render_karma_bar(percent: int) -> str:
    value = max(0, min(100, int(percent)))
    width = 13
    cursor_idx = int(round((value / 100) * (width - 1)))
    cells = ["━"] * width
    cells[cursor_idx] = "🟣"
    return f"😈{''.join(cells)}😇  {value}%"


class AuraEligibilityService:
    def __init__(self, database: DatabaseService, entitlements: EntitlementsService) -> None:
        self._db = database
        self._entitlements = entitlements

    async def evaluate_member(self, member: discord.abc.User, guild_id: str, start_ts: str, end_ts: str) -> AuraEligibilityResult:
        profile = await self._entitlements.resolve_profile(member)
        aura_config = await self._entitlements.get_feature_profile_config(member, "aura")
        eligibility = aura_config.get("eligibility", {}) if isinstance(aura_config, dict) else {}
        if not bool(aura_config.get("enabled", False)):
            return AuraEligibilityResult(False, "Aura non attiva per il tuo tier")

        if bool(eligibility.get("exclude_bots", True)) and bool(getattr(member, "bot", False)):
            return AuraEligibilityResult(False, "Aura non attiva: account bot escluso")

        min_age = int(eligibility.get("min_account_age_days", 7) or 7)
        created_at = getattr(member, "created_at", None)
        if isinstance(created_at, datetime):
            created_dt = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - created_dt < timedelta(days=min_age):
                return AuraEligibilityResult(False, f"Aura non attiva: account troppo recente (min {min_age} giorni)")

        exclude_roles = {str(r).lower() for r in eligibility.get("exclude_roles", []) if r is not None}
        if exclude_roles:
            for role in getattr(member, "roles", []):
                if str(getattr(role, "id", "")).lower() in exclude_roles or str(getattr(role, "name", "")).lower() in exclude_roles:
                    return AuraEligibilityResult(False, "Aura non attiva: ruolo escluso")

        if bool(eligibility.get("exclude_if_flagged_fake", True)):
            fake_users_raw = await self._db.get_setting("aura.fake_user_ids")
            fake_users: set[str] = set()
            if fake_users_raw:
                try:
                    parsed = json.loads(fake_users_raw)
                    if isinstance(parsed, list):
                        fake_users = {str(x) for x in parsed}
                except json.JSONDecodeError:
                    logger.warning("Invalid aura.fake_user_ids setting")
            if str(getattr(member, "id", "")) in fake_users:
                return AuraEligibilityResult(False, "Aura non attiva: account segnalato")

        min_messages = int(eligibility.get("min_messages_in_range", 20) or 20)
        user_id = str(getattr(member, "id", ""))
        count = await self._db.count_user_messages_in_range(guild_id, user_id, start_ts, end_ts)
        if count < min_messages:
            return AuraEligibilityResult(False, f"Aura non attiva: servono almeno {min_messages} messaggi nel periodo")

        return AuraEligibilityResult(True, "ok")


class AuraRollingStatsService:
    def __init__(self, database: DatabaseService) -> None:
        self._db = database

    async def on_message_saved(self, *, guild_id: str, channel_id: str, user_id: str, ts: str, mentions: list[str]) -> None:
        window_key = datetime.fromisoformat(ts).date().isoformat()
        await self._db.upsert_aura_rolling_on_message(
            guild_id=guild_id,
            user_id=user_id,
            window_key=window_key,
            ts=ts,
            unique_increment=max(1, len(set(mentions))),
        )

    async def on_barcello_event(self, *, guild_id: str, ts: str, invigorate: bool) -> None:
        active_users = await self._db.fetch_recent_active_users(guild_id, ts, minutes=30)
        for user_id in active_users:
            await self._db.upsert_aura_rolling_on_barcello(
                guild_id=guild_id,
                user_id=user_id,
                window_key=datetime.fromisoformat(ts).date().isoformat(),
                ts=ts,
                invigorate=invigorate,
            )


class AuraAggregationJob:
    def __init__(
        self,
        database: DatabaseService,
        bot: discord.Client,
        eligibility_service: AuraEligibilityService,
        *,
        interval_seconds: int = 21600,
    ) -> None:
        self._db = database
        self._bot = bot
        self._eligibility = eligibility_service
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                logger.exception("Aura aggregation tick failed")
            await asyncio.sleep(self._interval_seconds)

    async def run_once(self) -> None:
        now = datetime.now(timezone.utc)
        period_start = (now - timedelta(days=30)).isoformat()
        period_end = now.isoformat()
        for guild in self._bot.guilds:
            guild_id = str(guild.id)
            for member in guild.members:
                eligibility = await self._eligibility.evaluate_member(member, guild_id, period_start, period_end)
                role_tier = await self._eligibility._entitlements.resolve_profile(member)
                await self._db.upsert_aura_user_profile(
                    guild_id=guild_id,
                    user_id=str(member.id),
                    eligible=1 if eligibility.eligible else 0,
                    eligibility_reason=eligibility.reason,
                    role_tier=role_tier,
                    last_computed_at=period_end,
                )
                if not eligibility.eligible:
                    continue
                metrics = await self._db.fetch_aura_metrics(guild_id, str(member.id), period_start, period_end)
                karma_percent = max(0, min(100, 50 + metrics["invigorate_events"] * 4 - metrics["degrade_events"] * 6 + min(metrics["msg_count"], 40) // 2))
                trend_delta = metrics["invigorate_events"] - metrics["degrade_events"]
                points_total = karma_percent + trend_delta
                metrics_json = json.dumps(metrics)
                await self._db.upsert_aura_result(
                    guild_id=guild_id,
                    user_id=str(member.id),
                    channel_id=None,
                    period_start=period_start,
                    period_end=period_end,
                    karma_percent=karma_percent,
                    trend_delta=trend_delta,
                    points_total=points_total,
                    metrics_json=metrics_json,
                    computed_at=period_end,
                )
                channels = await self._db.fetch_user_channels_in_range(guild_id, str(member.id), period_start, period_end)
                for channel_id in channels:
                    ch_metrics = await self._db.fetch_aura_metrics(guild_id, str(member.id), period_start, period_end, channel_id=channel_id)
                    ch_karma = max(0, min(100, 45 + ch_metrics["invigorate_events"] * 4 - ch_metrics["degrade_events"] * 6 + min(ch_metrics["msg_count"], 30) // 2))
                    await self._db.upsert_aura_result(
                        guild_id=guild_id,
                        user_id=str(member.id),
                        channel_id=channel_id,
                        period_start=period_start,
                        period_end=period_end,
                        karma_percent=ch_karma,
                        trend_delta=ch_metrics["invigorate_events"] - ch_metrics["degrade_events"],
                        points_total=ch_karma,
                        metrics_json=json.dumps(ch_metrics),
                        computed_at=period_end,
                    )
                await self._db.insert_aura_ledger_event(guild_id, str(member.id), None, period_end, "batch.aggregate", points_total, {"period_start": period_start, "period_end": period_end})


class ArchetypeAnalyzerService:
    def __init__(
        self,
        database: DatabaseService,
        bot: discord.Client,
        eligibility_service: AuraEligibilityService,
        *,
        interval_seconds: int = 86400,
    ) -> None:
        self._db = database
        self._bot = bot
        self._eligibility = eligibility_service
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                logger.exception("Archetype analyzer tick failed")
            await asyncio.sleep(self._interval_seconds)

    async def run_once(self) -> None:
        now = datetime.now(timezone.utc)
        period_start = (now - timedelta(days=30)).isoformat()
        period_end = now.isoformat()
        for guild in self._bot.guilds:
            guild_id = str(guild.id)
            for member in guild.members:
                eligibility = await self._eligibility.evaluate_member(member, guild_id, period_start, period_end)
                if not eligibility.eligible:
                    continue
                metrics = await self._db.fetch_aura_metrics(guild_id, str(member.id), period_start, period_end)
                score_payload = {
                    "volume": min(100, metrics["msg_count"] * 2),
                    "diversity": min(100, metrics["unique_interactions"] * 5),
                    "influence": min(100, metrics["reply_received"] * 6),
                    "climate_impact": max(0, min(100, 50 + (metrics["invigorate_events"] - metrics["degrade_events"]) * 8)),
                    "quality_proxy": min(100, metrics["quality_counter"] * 4),
                    "consistency": 100 if metrics["msg_count"] > 0 else 0,
                }
                insights = [
                    "Mantieni costanza settimanale per aumentare la stabilità.",
                    "Interagire con utenti diversi migliora la diversità.",
                ]
                await self._db.upsert_archetype_profile(
                    guild_id=guild_id,
                    user_id=str(member.id),
                    period_days=30,
                    archetype_scores_json=json.dumps(score_payload),
                    metrics_json=json.dumps({"insights": insights, "scores": score_payload}),
                    computed_at=period_end,
                )
