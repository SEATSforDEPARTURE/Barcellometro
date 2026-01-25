from __future__ import annotations

import logging

import discord
from discord.ext import commands

from app.core.config import AppConfig
from app.core.plugin_loader import PluginLoader
from app.core.service_registry import ServiceRegistry
from app.services.database import DatabaseService
from app.services.ingest import IngestService
from app.services.retention import RetentionService
from app.services.status import StatusService

logger = logging.getLogger(__name__)


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
    status_service = StatusService(database_service)
    retention_service = RetentionService(database_service, config.default_retention_days)

    registry.register("config", config)
    registry.register("bot", bot)
    registry.register("database", database_service)
    registry.register("ingest", ingest_service)
    registry.register("status", status_service)
    registry.register("retention", retention_service)

    plugin_loader = PluginLoader(registry)
    plugin_loader.load(
        [
            "app.plugins.discord_adapter",
            "app.plugins.commands",
            "app.plugins.example_consumer",
        ]
    )
    registry.register("plugins", plugin_loader)

    status_service.register_component("database", database_service)
    status_service.register_component("ingest", ingest_service)
    status_service.register_component("retention", retention_service)
    status_service.register_component("plugins", plugin_loader)

    return bot, registry
