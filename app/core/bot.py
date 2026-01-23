from __future__ import annotations
import logging
import discord
from discord.ext import commands

from app.core.config import load_settings
from app.core.logging import setup_logging
from app.core.service_registry import ServiceRegistry
from app.core.plugin_loader import load_plugins

from app.db.session import create_engine_and_session
from app.db.models.meta import Base
from app.services.db_health import DBHealthService

# Import models so metadata includes them
from app.db.models import core as _core_models  # noqa: F401

log = logging.getLogger("barcellometro.core")

class BarcellometroBot(commands.Bot):
    def __init__(self):
        self.settings = load_settings()
        setup_logging(self.settings)

        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

        self.registry = ServiceRegistry()
        self.plugin_manifests: dict[str, dict] = {}

    async def setup_hook(self) -> None:
        engine, SessionLocal = create_engine_and_session(self.settings.DB_URL, echo=self.settings.DB_ECHO)
        Base.metadata.create_all(bind=engine)

        self.registry.register("settings", self.settings)
        self.registry.register("db_engine", engine)
        self.registry.register("db_session_factory", SessionLocal)
        self.registry.register("db_health", DBHealthService(engine))

        plugin_names = list(dict.fromkeys(["status", *self.settings.PLUGINS]))
        self.plugin_manifests = load_plugins(self, self.registry, plugin_names)

        # Sync slash commands
        try:
            if self.settings.GUILD_ID:
                guild = discord.Object(id=self.settings.GUILD_ID)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                log.info("Comandi sincronizzati su guild %s", self.settings.GUILD_ID)
            else:
                await self.tree.sync()
                log.info("Comandi sincronizzati globalmente")
        except Exception:
            log.exception("Sync comandi fallita (non blocca il bot)")

    async def on_ready(self) -> None:
        log.info("ONLINE come %s (id=%s)", self.user, getattr(self.user, "id", "?"))

def create_bot() -> BarcellometroBot:
    return BarcellometroBot()
