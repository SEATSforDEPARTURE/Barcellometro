from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from weakref import WeakKeyDictionary

import discord

from app.services.database import DatabaseService

FOOTER_VERSION_KEY = "footer.version"
FOOTER_GLOBAL_PHRASE_KEY = "footer.global_phrase"
FOOTER_SERVICE_PHRASE_PREFIX = "footer.service_phrase."
FOOTER_SEPARATOR = " · "
FOOTER_MAX_LEN = 2048

SUPPORTED_FOOTER_SERVICES: tuple[str, ...] = (
    "riassunto",
    "resoconto",
    "audio_notes",
    "aura",
    "attivita",
    "barcello",
    "qna",
    "frasi",
    "campagne",
    "status",
    "privacy",
    "voice_ingest",
    "triggers",
    "message_scheduler",
    "daily_resoconto",
    "daily_activity_report",
    "activity_dm",
    "user_activity",
    "channel_summary",
)


@dataclass(slots=True)
class FooterMeta:
    service_name: str
    contributors: list[str]
    used_local_processing: bool = False
    footer_icon_url: str | None = None


_EMBED_META: WeakKeyDictionary[discord.Embed, FooterMeta] = WeakKeyDictionary()


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _truncate(text: str, max_len: int = FOOTER_MAX_LEN) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def attach_footer_meta(
    embed: discord.Embed,
    *,
    service_name: str,
    contributors: Iterable[str] | None = None,
    used_local_processing: bool = False,
    footer_icon_url: str | None = None,
) -> discord.Embed:
    deduped: list[str] = []
    seen: set[str] = set()
    for entry in contributors or []:
        item = _clean(entry)
        if not item or item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    _EMBED_META[embed] = FooterMeta(
        service_name=_clean(service_name) or "unknown",
        contributors=deduped,
        used_local_processing=used_local_processing,
        footer_icon_url=_clean(footer_icon_url) or None,
    )
    return embed


def get_footer_meta(embed: discord.Embed) -> FooterMeta | None:
    return _EMBED_META.get(embed)


def copy_footer_meta(source: discord.Embed, target: discord.Embed) -> discord.Embed:
    meta = get_footer_meta(source)
    if meta is None:
        return target
    return attach_footer_meta(
        target,
        service_name=meta.service_name,
        contributors=meta.contributors,
        used_local_processing=meta.used_local_processing,
        footer_icon_url=meta.footer_icon_url,
    )


class FooterService:
    def __init__(self, database: DatabaseService) -> None:
        self._database = database

    async def set_version(self, version: str | None) -> None:
        await self._set_or_clear(FOOTER_VERSION_KEY, version)

    async def set_global_phrase(self, phrase: str | None) -> None:
        await self._set_or_clear(FOOTER_GLOBAL_PHRASE_KEY, phrase)

    async def set_service_phrase(self, service_name: str, phrase: str | None) -> None:
        await self._set_or_clear(f"{FOOTER_SERVICE_PHRASE_PREFIX}{_clean(service_name)}", phrase)

    async def get_version(self) -> str | None:
        return _clean(await self._database.get_setting(FOOTER_VERSION_KEY)) or None

    async def get_global_phrase(self) -> str | None:
        return _clean(await self._database.get_setting(FOOTER_GLOBAL_PHRASE_KEY)) or None

    async def get_service_phrases(self) -> dict[str, str]:
        rows = await self._database.fetchall(
            "SELECT key, value FROM settings WHERE key LIKE ? ORDER BY key",
            (f"{FOOTER_SERVICE_PHRASE_PREFIX}%",),
        )
        out: dict[str, str] = {}
        for row in rows:
            key = row["key"]
            value = _clean(row["value"])
            if not value:
                continue
            out[key.replace(FOOTER_SERVICE_PHRASE_PREFIX, "", 1)] = value
        return out

    async def render_footer(self, *, service_name: str, contributors: Iterable[str], used_local_processing: bool) -> tuple[str, str | None]:
        version = await self.get_version()
        global_phrase = await self.get_global_phrase()
        service_phrases = await self.get_service_phrases()
        phrase = service_phrases.get(service_name) or global_phrase

        brand = f"Barcellometro {version}" if version else "Barcellometro"
        contributors_deduped: list[str] = []
        seen: set[str] = set()
        for item in contributors:
            clean = _clean(item)
            if not clean or clean in seen:
                continue
            seen.add(clean)
            contributors_deduped.append(clean)
        if used_local_processing and "in loco" not in seen:
            contributors_deduped.append("in loco")

        if not contributors_deduped:
            processing = "Dati elaborati in loco"
        elif contributors_deduped == ["in loco"]:
            processing = "Dati elaborati in loco"
        elif len(contributors_deduped) == 1:
            processing = f"Dati elaborati con {contributors_deduped[0]}"
        elif len(contributors_deduped) == 2:
            processing = f"Dati elaborati con {contributors_deduped[0]} e {contributors_deduped[1]}"
        else:
            processing = f"Dati elaborati con {', '.join(contributors_deduped[:-1])} e {contributors_deduped[-1]}"

        parts = [brand, processing]
        if phrase:
            parts.append(phrase)
        return _truncate(FOOTER_SEPARATOR.join(parts)), phrase

    async def apply(self, embed: discord.Embed, *, default_service_name: str = "unknown") -> discord.Embed:
        meta = get_footer_meta(embed)
        if meta is None:
            meta = FooterMeta(service_name=default_service_name, contributors=[], used_local_processing=False)
        text, _ = await self.render_footer(
            service_name=meta.service_name,
            contributors=meta.contributors,
            used_local_processing=meta.used_local_processing,
        )
        embed.set_footer(text=text, icon_url=meta.footer_icon_url)
        return embed

    async def _set_or_clear(self, key: str, value: str | None) -> None:
        cleaned = _clean(value)
        if not cleaned:
            await self._database.execute("DELETE FROM settings WHERE key = ?", (key,))
            await self._database.commit()
            return
        await self._database.set_setting(key, cleaned)
