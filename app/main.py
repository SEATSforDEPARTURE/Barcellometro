from __future__ import annotations

import asyncio
import logging

from app.core.bot import create_bot, normalize_instance_mode
from app.core.config import load_config
from app.core.logging_setup import setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    config = load_config()
    setup_logging(config.log_level)

    if not config.discord_token:
        raise RuntimeError("DISCORD_TOKEN is missing in environment.")
    if not config.guild_id:
        raise RuntimeError("GUILD_ID is missing in environment.")

    bot, registry = create_bot(config)

    database = registry.get("database")
    instance_mode = normalize_instance_mode(config.instance_mode)
    retention = None
    backfill = None
    ai_service = None
    if instance_mode == "main":
        retention = registry.get("retention")
        backfill = registry.get("backfill")
        ai_service = registry.get("ai")

    async def runner() -> None:
        await database.connect()
        await database.initialize_schema()
        if instance_mode == "main":
            await retention.load_retention()
            await backfill.load_settings()
            await ai_service.load_settings()
            retention.start()
            backfill.start()
        await bot.start(config.discord_token)

    try:
        asyncio.run(runner())
    except KeyboardInterrupt:
        logger.info("Shutting down")


if __name__ == "__main__":
    main()
