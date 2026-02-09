from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo
from typing import Any

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
    timezone: ZoneInfo

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
            timezone=timezone,
        )
