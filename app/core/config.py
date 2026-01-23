from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]

@dataclass(frozen=True)
class Settings:
    DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
    GUILD_ID: int = int(os.getenv("GUILD_ID", "0") or "0")
    PLUGINS: list[str] = None  # type: ignore
    DB_URL: str = os.getenv("DB_URL", "sqlite:///barcellometro.sqlite")
    DB_ECHO: bool = os.getenv("DB_ECHO", "0") in ("1", "true", "True", "yes", "YES")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    def __post_init__(self):
        object.__setattr__(self, "PLUGINS", _csv(os.getenv("PLUGINS", "status")))

def load_settings() -> Settings:
    s = Settings()
    if not s.DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN mancante. Inseriscilo nel file .env")
    return s
