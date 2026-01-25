from __future__ import annotations

import asyncio
import logging

from app.core.bot import create_bot
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
    retention = registry.get("retention")

    async def runner() -> None:
        await database.connect()
        await database.initialize_schema()
        await retention.load_retention()
        retention.start()
        await bot.start(config.discord_token)

    try:
        asyncio.run(runner())
    except KeyboardInterrupt:
        logger.info("Shutting down")


if __name__ == "__main__":
    main()
