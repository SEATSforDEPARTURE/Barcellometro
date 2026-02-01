from __future__ import annotations

import logging

import discord
from discord.ext import commands

from app.core.config import AppConfig
from app.core.plugin_loader import PluginLoader
from app.core.service_registry import ServiceRegistry
from app.services.ai import AiService
from app.services.backfill import BackfillService
from app.services.database import DatabaseService
from app.services.ingest import IngestService
from app.services.permissions import CommandGuardService
from app.services.retention import RetentionService
from app.services.status import StatusService
from app.services.stt.ai_stt import AiSttService
from app.services.stt.faster_whisper import FasterWhisperSttService
from app.services.translate.ai_translate import AiTranslateService
from app.services.translate.argos import ArgosTranslateService

logger = logging.getLogger(__name__)

DEFAULT_PLUGINS = [
    "app.plugins.discord_adapter",
    "app.plugins.commands",
    "app.plugins.example_consumer",
    "app.plugins.audio_notes_transcribe",
    "app.plugins.voice_ingest",
]


def _parse_plugin_allowlist(raw: str) -> list[str]:
    return [entry.strip() for entry in raw.split(",") if entry.strip()]


def create_bot(config: AppConfig) -> tuple[commands.Bot, ServiceRegistry]:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.reactions = True
    intents.guilds = True
    intents.guild_messages = True
    intents.guild_reactions = True

    bot = commands.Bot(command_prefix="!", intents=intents)
    registry = ServiceRegistry()

    database_service = DatabaseService(config.db_path)
    ingest_service = IngestService(database_service)
    stt_local_service = FasterWhisperSttService(database_service)
    status_service = None
    retention_service = None
    backfill_service = None
    guard_service = None
    ai_service = None
    stt_ai_service = None
    translate_local_service = None
    translate_ai_service = None

    instance_mode = (config.instance_mode or "main").strip().lower()
    if instance_mode not in {"main", "worker"}:
        logger.warning("Unknown INSTANCE_MODE=%s; defaulting to main.", config.instance_mode)
        instance_mode = "main"
    if instance_mode == "main":
        status_service = StatusService(database_service)
        retention_service = RetentionService(database_service, config.default_retention_days)
        backfill_service = BackfillService(database_service, config.default_retention_days)
        guard_service = CommandGuardService(database_service)
        ai_service = AiService(database_service, config.openai_api_key)
        stt_ai_service = AiSttService(database_service, ai_service)
        translate_local_service = ArgosTranslateService()
        translate_ai_service = AiTranslateService(ai_service)

    registry.register("config", config)
    registry.register("bot", bot)
    registry.register("database", database_service)
    registry.register("ingest", ingest_service)
    registry.register("stt.local", stt_local_service)
    if instance_mode == "main":
        registry.register("status", status_service)
        registry.register("retention", retention_service)
        registry.register("backfill", backfill_service)
        registry.register("guard", guard_service)
        registry.register("ai", ai_service)
        registry.register("stt.ai", stt_ai_service)
        registry.register("translate.local", translate_local_service)
        registry.register("translate.ai", translate_ai_service)

    plugin_loader = PluginLoader(registry)
    allowlist_raw = config.plugin_allowlist
    if allowlist_raw:
        allowlist = _parse_plugin_allowlist(allowlist_raw)
        logger.info("PLUGIN_ALLOWLIST active: %s", allowlist)
        plugin_loader.load(allowlist, strict=False)
    else:
        plugin_loader.load(DEFAULT_PLUGINS, strict=True)
    registry.register("plugins", plugin_loader)

    if instance_mode == "main" and status_service is not None:
        status_service.register_component("database", database_service)
        status_service.register_component("ingest", ingest_service)
        status_service.register_component("retention", retention_service)
        status_service.register_component("backfill", backfill_service)
        status_service.register_component("guard", guard_service)
        status_service.register_component("ai", ai_service)
        status_service.register_component("stt.local", stt_local_service)
        status_service.register_component("stt.ai", stt_ai_service)
        status_service.register_component("translate.local", translate_local_service)
        status_service.register_component("translate.ai", translate_ai_service)
        status_service.register_component("plugins", plugin_loader)

    return bot, registry
