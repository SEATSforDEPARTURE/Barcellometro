from __future__ import annotations

import logging

import discord
from discord.ext import commands

from app.core.config import AppConfig
from app.core.plugin_loader import PluginLoader
from app.core.service_registry import ServiceRegistry
from app.services.ai import AiService
from app.services.backfill import BackfillService
from app.services.community_insights import CommunityInsightsService
from app.services.database import DatabaseService
from app.services.ingest import IngestService
from app.services.permissions import CommandGuardService
from app.services.retention import RetentionService
from app.services.barcello import BarcelloService
from app.services.message_scheduler import MessageSchedulerService
from app.services.status import StatusService
from app.services.summary import SummaryService
from app.services.daily_resoconto import DailyResocontoService
from app.services.daily_activity_report import DailyActivityReportService
from app.services.entitlements import EntitlementsService
from app.services.inactivity import InactivityService
from app.services.activity_insights import ActivityInsightsService
from app.services.inactive_members_moderation import InactiveMembersModerationService
from app.services.stt.ai_stt import AiSttService
from app.services.stt.faster_whisper import FasterWhisperSttService
from app.services.triggers import TriggerEngineService
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


def _unique(seq: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in seq:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def normalize_instance_mode(raw: str | None) -> str:
    value = (raw or "main").strip().lower()
    if not value or value == "main":
        return "main"
    if value.startswith("worker"):
        return "worker"
    return value


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
    message_scheduler = None
    barcello_service = None
    community_insights = None
    daily_resoconto = None
    trigger_engine = None
    inactivity_service = None
    activity_insights = None
    daily_activity_report = None
    inactive_members_moderation = None

    instance_mode = normalize_instance_mode(config.instance_mode)
    logger.info("Instance mode raw=%s normalized=%s", config.instance_mode, instance_mode)
    logger.info("Configured GUILD_ID=%s", config.guild_id)
    if config.guild_id <= 0:
        logger.warning("GUILD_ID=%s: commands plugin will use global app command registration", config.guild_id)
    if instance_mode not in {"main", "worker"}:
        logger.warning("Unknown INSTANCE_MODE=%s; defaulting to main.", config.instance_mode)
        instance_mode = "main"
    if instance_mode == "main":
        status_service = StatusService(database_service)
        retention_service = RetentionService(database_service, config.default_retention_days)
        backfill_service = BackfillService(database_service, config.default_retention_days)
        guard_service = CommandGuardService(database_service)
        ai_service = AiService(database_service, config.openai_api_key)
        barcello_service = BarcelloService(database_service)
        community_insights = CommunityInsightsService(ai_service)
        stt_ai_service = AiSttService(database_service, ai_service)
        translate_local_service = ArgosTranslateService()
        translate_ai_service = AiTranslateService(ai_service)
        message_scheduler = MessageSchedulerService(
            database_service,
            bot,
            community_insights=community_insights,
            barcello_service=barcello_service,
            ai_service=ai_service,
        )
        summary_service = SummaryService(database_service, ai_service=ai_service)
        daily_resoconto = DailyResocontoService(database_service, bot, summary_service, barcello_service, ai_service=ai_service)
        entitlements_service = EntitlementsService(database_service)
        trigger_engine = TriggerEngineService(database_service, barcello_service, entitlements_service, ai_service, community_insights)
        inactivity_service = InactivityService(database_service)
        activity_insights = ActivityInsightsService(database_service)
        inactive_members_moderation = InactiveMembersModerationService(database_service, bot)
        daily_activity_report = DailyActivityReportService(database_service, bot, activity_insights, inactive_members_moderation=inactive_members_moderation)

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
        registry.register("barcello", barcello_service)
        registry.register("community_insights", community_insights)
        registry.register("message_scheduler", message_scheduler)
        registry.register("daily_resoconto", daily_resoconto)
        registry.register("trigger_engine", trigger_engine)
        registry.register("inactivity", inactivity_service)
        registry.register("activity_insights", activity_insights)
        registry.register("daily_activity_report", daily_activity_report)
        registry.register("inactive_members_moderation", inactive_members_moderation)
        registry.register("stt.ai", stt_ai_service)
        registry.register("translate.local", translate_local_service)
        registry.register("translate.ai", translate_ai_service)

    plugin_loader = PluginLoader(registry)
    mandatory_plugins = ["app.plugins.discord_adapter"]
    if instance_mode == "main":
        mandatory_plugins.append("app.plugins.commands")

    allowlist_raw = config.plugin_allowlist
    if allowlist_raw:
        allowlist = _parse_plugin_allowlist(allowlist_raw)
        plugin_list_final = _unique(allowlist + DEFAULT_PLUGINS)
    else:
        allowlist = []
        plugin_list_final = list(DEFAULT_PLUGINS)

    logger.info(
        "Plugin loading plan: instance_mode=%s allowlist_raw=%s parsed_allowlist=%s plugin_list_final=%s",
        instance_mode,
        allowlist_raw,
        allowlist,
        plugin_list_final,
    )

    logger.info("Loading mandatory plugins strict=True: %s", mandatory_plugins)
    plugin_loader.load(mandatory_plugins, strict=True)

    rest = [p for p in plugin_list_final if p not in mandatory_plugins]
    logger.info("Loading remaining plugins strict=False: %s", rest)
    plugin_loader.load(rest, strict=False)

    logger.info("Plugins loaded: %s", plugin_loader.loaded)
    if instance_mode == "main" and "app.plugins.commands" not in plugin_loader.loaded:
        logger.error("Commands plugin not loaded; slash commands will not work.")
        logger.error("Check PLUGIN_ALLOWLIST / GUILD_ID / INSTANCE_MODE")
    registry.register("plugins", plugin_loader)

    if instance_mode == "main" and status_service is not None:
        status_service.register_component("database", database_service)
        status_service.register_component("ingest", ingest_service)
        status_service.register_component("retention", retention_service)
        status_service.register_component("backfill", backfill_service)
        status_service.register_component("guard", guard_service)
        status_service.register_component("ai", ai_service)
        status_service.register_component("barcello", barcello_service)
        status_service.register_component("community_insights", community_insights)
        status_service.register_component("message_scheduler", message_scheduler)
        status_service.register_component("daily_resoconto", daily_resoconto)
        status_service.register_component("trigger_engine", trigger_engine)
        status_service.register_component("daily_activity_report", daily_activity_report)
        status_service.register_component("stt.local", stt_local_service)
        status_service.register_component("stt.ai", stt_ai_service)
        status_service.register_component("translate.local", translate_local_service)
        status_service.register_component("translate.ai", translate_ai_service)
        status_service.register_component("plugins", plugin_loader)

    if instance_mode == "main" and message_scheduler is not None:
        async def handle_ready() -> None:
            message_scheduler.start()
            if daily_activity_report is not None:
                daily_activity_report.start()
            if inactive_members_moderation is not None:
                inactive_members_moderation.start()

        bot.add_listener(handle_ready, "on_ready")

    return bot, registry
