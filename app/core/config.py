from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppConfig:
    discord_token: str
    guild_id: int
    db_path: str
    default_retention_days: int
    ignore_bots: bool
    log_level: str
    openai_api_key: str
    instance_mode: str
    plugin_allowlist: str
    riassunto_max_minutes: int
    riassunto_max_hours: int
    riassunto_max_days: int
    riassunto_max_weeks: int
    riassunto_range_max_days: int
    name_policy_text_show_names_always: bool
    name_policy_voice_show_names_for_chat_messages: bool
    name_policy_voice_show_names_for_voice_transcripts_when_green_only: bool


def load_config() -> AppConfig:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN", "").strip()
    guild_id_raw = os.getenv("GUILD_ID", "").strip()
    if not guild_id_raw:
        guild_id = 0
        logger.warning("GUILD_ID not set; defaulting to 0 (global app commands mode)")
    else:
        guild_id = int(guild_id_raw)
    db_path = os.getenv("DB_PATH", "bot.sqlite")
    retention = int(os.getenv("DEFAULT_RETENTION_DAYS", "30"))
    ignore_bots = os.getenv("IGNORE_BOTS", "true").lower() in {"1", "true", "yes", "y"}
    log_level = os.getenv("LOG_LEVEL", "INFO")
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    instance_mode = os.getenv("INSTANCE_MODE", "main").strip()
    plugin_allowlist = os.getenv("PLUGIN_ALLOWLIST", "").strip()
    riassunto_max_minutes = int(os.getenv("RIASSUNTO_MAX_MINUTES", "60"))
    riassunto_max_hours = int(os.getenv("RIASSUNTO_MAX_HOURS", "24"))
    riassunto_max_days = int(os.getenv("RIASSUNTO_MAX_DAYS", "30"))
    riassunto_max_weeks = int(os.getenv("RIASSUNTO_MAX_WEEKS", "4"))
    riassunto_range_max_days = int(os.getenv("RIASSUNTO_RANGE_MAX_DAYS", "30"))
    name_policy_text_show_names_always = os.getenv("NAME_POLICY_TEXT_SHOW_NAMES_ALWAYS", "true").lower() in {
        "1",
        "true",
        "yes",
        "y",
    }
    name_policy_voice_show_names_for_chat_messages = os.getenv(
        "NAME_POLICY_VOICE_SHOW_NAMES_FOR_CHAT_MESSAGES", "true"
    ).lower() in {"1", "true", "yes", "y"}
    name_policy_voice_show_names_for_voice_transcripts_when_green_only = os.getenv(
        "NAME_POLICY_VOICE_SHOW_NAMES_FOR_VOICE_TRANSCRIPTS_WHEN_GREEN_ONLY", "true"
    ).lower() in {"1", "true", "yes", "y"}
    return AppConfig(
        discord_token=token,
        guild_id=guild_id,
        db_path=db_path,
        default_retention_days=retention,
        ignore_bots=ignore_bots,
        log_level=log_level,
        openai_api_key=openai_api_key,
        instance_mode=instance_mode,
        plugin_allowlist=plugin_allowlist,
        riassunto_max_minutes=riassunto_max_minutes,
        riassunto_max_hours=riassunto_max_hours,
        riassunto_max_days=riassunto_max_days,
        riassunto_max_weeks=riassunto_max_weeks,
        riassunto_range_max_days=riassunto_range_max_days,
        name_policy_text_show_names_always=name_policy_text_show_names_always,
        name_policy_voice_show_names_for_chat_messages=name_policy_voice_show_names_for_chat_messages,
        name_policy_voice_show_names_for_voice_transcripts_when_green_only=(
            name_policy_voice_show_names_for_voice_transcripts_when_green_only
        ),
    )
