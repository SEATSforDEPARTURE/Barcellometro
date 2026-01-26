from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class AppConfig:
    discord_token: str
    guild_id: int
    db_path: str
    default_retention_days: int
    ignore_bots: bool
    log_level: str


def load_config() -> AppConfig:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN", "").strip()
    guild_id_raw = os.getenv("GUILD_ID", "").strip()
    if not guild_id_raw:
        guild_id = 0
    else:
        guild_id = int(guild_id_raw)
    db_path = os.getenv("DB_PATH", "bot.sqlite")
    retention = int(os.getenv("DEFAULT_RETENTION_DAYS", "30"))
    ignore_bots = os.getenv("IGNORE_BOTS", "true").lower() in {"1", "true", "yes", "y"}
    log_level = os.getenv("LOG_LEVEL", "INFO")
    return AppConfig(
        discord_token=token,
        guild_id=guild_id,
        db_path=db_path,
        default_retention_days=retention,
        ignore_bots=ignore_bots,
        log_level=log_level,
    )
