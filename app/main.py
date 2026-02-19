from __future__ import annotations

import asyncio
import logging
import os

from app.core.bot import create_bot, normalize_instance_mode
from app.core.config import load_config
from app.core.logging_setup import setup_logging
from app.services.config_overrides import ConfigOverridesService

logger = logging.getLogger(__name__)


def main() -> None:
    config = load_config()
    setup_logging(config.log_level)

    if not config.discord_token:
        raise RuntimeError("DISCORD_TOKEN is missing in environment.")
    if not config.guild_id:
        logger.warning("GUILD_ID is missing or invalid; app commands will be registered globally.")

    bot, registry = create_bot(config)

    database = registry.get("database")
    instance_mode = normalize_instance_mode(config.instance_mode)
    retention = None
    backfill = None
    ai_service = None
    daily_resoconto = None
    daily_activity_report = None
    trigger_engine = None
    if instance_mode == "main":
        retention = registry.get("retention")
        backfill = registry.get("backfill")
        ai_service = registry.get("ai")
        daily_resoconto = registry.get("daily_resoconto") if registry.has("daily_resoconto") else None
        daily_activity_report = registry.get("daily_activity_report") if registry.has("daily_activity_report") else None
        trigger_engine = registry.get("trigger_engine") if registry.has("trigger_engine") else None

    async def runner() -> None:
        await database.connect()
        await database.initialize_schema()
        config_overrides = ConfigOverridesService(database)
        await config_overrides.apply_overrides_once()
        if os.getenv("ENTITLEMENTS_CONFIG_RELOAD", "").lower() in {"1", "true", "yes", "y"}:
            asyncio.create_task(config_overrides.watch_for_changes())
        if instance_mode == "main":
            await retention.load_retention()
            await backfill.load_settings()
            await ai_service.load_settings()
            retention.start()
            backfill.start()
            if daily_resoconto:
                daily_resoconto.start()
            if daily_activity_report:
                daily_activity_report.start()
            if trigger_engine:
                trigger_engine.start(bot)
            calibration = registry.get("barcello_calibration") if registry.has("barcello_calibration") else None
            if calibration:
                async def _calibration_loop() -> None:
                    while True:
                        try:
                            await calibration.run_calibration(days=14, min_samples=20)
                        except Exception:
                            logger.exception("Calibration loop failed")
                        await asyncio.sleep(60 * 60 * 24)

                asyncio.create_task(_calibration_loop())
        await bot.start(config.discord_token)

    try:
        asyncio.run(runner())
    except KeyboardInterrupt:
        logger.info("Shutting down")


if __name__ == "__main__":
    main()
