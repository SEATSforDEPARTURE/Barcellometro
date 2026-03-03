from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo
from typing import Any, Optional

import discord

from app.core.service_registry import ServiceRegistry
from app.services.barcello import BarcelloService
from app.services.barcello_calibration import BarcelloCalibrationService
from app.services.entitlements import EntitlementsService
from app.services.ingest import IngestService
from app.services.summary import SummaryService


@dataclass
class CommandContext:
    bot: discord.Client
    config: Any
    database: Any
    guard: Any
    entitlements: EntitlementsService
    barcello_service: BarcelloService
    barcello_calibration_service: BarcelloCalibrationService
    summary_service: SummaryService
    retention: Any
    backfill: Any
    status: Any
    ingest: IngestService
    ai: Any
    voice_ingest: Any
    daily_resoconto: Any
    trigger_engine: Any
    activity_insights: Any
    inactivity: Any
    daily_activity_report: Any
    inactive_members_moderation: Any
    timezone: ZoneInfo
    message_scheduler: Optional[Any] = None
    aura_eligibility: Optional[Any] = None
    aura_rolling: Optional[Any] = None

    @classmethod
    def from_registry(cls, registry: ServiceRegistry) -> "CommandContext":
        bot: discord.Client = registry.get("bot")
        database = registry.get("database")
        entitlements = EntitlementsService(database)
        registry.register("entitlements", entitlements)
        if registry.has("barcello"):
            barcello = registry.get("barcello")
        else:
            barcello = BarcelloService(database)
            registry.register("barcello", barcello)
        barcello_calibration = BarcelloCalibrationService(database)
        registry.register("barcello_calibration", barcello_calibration)
        summary_service = SummaryService(database, ai_service=registry.get("ai") if registry.has("ai") else None)
        registry.register("summary", summary_service)
        retention = registry.get("retention")
        backfill = registry.get("backfill")
        guard = registry.get("guard")
        status_service = registry.get("status")
        ai_service = registry.get("ai")
        voice_ingest = registry.get("voice_ingest") if registry.has("voice_ingest") else None
        daily_resoconto = registry.get("daily_resoconto") if registry.has("daily_resoconto") else None
        trigger_engine = registry.get("trigger_engine") if registry.has("trigger_engine") else None
        activity_insights = registry.get("activity_insights") if registry.has("activity_insights") else None
        inactivity = registry.get("inactivity") if registry.has("inactivity") else None
        daily_activity_report = registry.get("daily_activity_report") if registry.has("daily_activity_report") else None
        inactive_members_moderation = registry.get("inactive_members_moderation") if registry.has("inactive_members_moderation") else None
        message_scheduler = registry.get("message_scheduler") if registry.has("message_scheduler") else None
        aura_eligibility = registry.get("aura_eligibility") if registry.has("aura_eligibility") else None
        aura_rolling = registry.get("aura_rolling") if registry.has("aura_rolling") else None
        ingest: IngestService = registry.get("ingest")
        config = registry.get("config")
        timezone = ZoneInfo("Europe/Rome")
        return cls(
            bot=bot,
            config=config,
            database=database,
            guard=guard,
            entitlements=entitlements,
            barcello_service=barcello,
            barcello_calibration_service=barcello_calibration,
            summary_service=summary_service,
            retention=retention,
            backfill=backfill,
            status=status_service,
            ingest=ingest,
            ai=ai_service,
            voice_ingest=voice_ingest,
            daily_resoconto=daily_resoconto,
            trigger_engine=trigger_engine,
            activity_insights=activity_insights,
            inactivity=inactivity,
            daily_activity_report=daily_activity_report,
            inactive_members_moderation=inactive_members_moderation,
            message_scheduler=message_scheduler,
            aura_eligibility=aura_eligibility,
            aura_rolling=aura_rolling,
            timezone=timezone,
        )
