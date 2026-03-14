from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import discord

from app.services.database import DatabaseService

logger = logging.getLogger(__name__)

FOOTER_VERSION_KEY = "footer.version"
FOOTER_GLOBAL_PHRASE_KEY = "footer.global_phrase"
FOOTER_SERVICE_PHRASE_PREFIX = "footer.service_phrase."
FOOTER_KNOWN_SERVICES_KEY = "footer.known_services"
FOOTER_KNOWN_SERVICE_SOURCES_KEY = "footer.known_service_sources"
FOOTER_LAST_META_PREFIX = "footer.last_meta."
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

_STARTUP_SERVICE_SCAN_DIRS: tuple[Path, ...] = (
    Path("app/plugins"),
    Path("app/plugins/commands_modular"),
    Path("app/services"),
    Path("app/renderers"),
)

_SERVICE_NAME_OVERRIDES: dict[str, str | None] = {
    "audio_notes_transcribe": "audio_notes",
    "voice_ingest": "voice_ingest",
    "daily_resoconto_renderer": "daily_resoconto",
    "daily_activity_report_renderer": "daily_activity_report",
    "activity_daily_report_renderer": "daily_activity_report",
    "activity_dm_renderer": "activity_dm",
    "user_activity_renderer": "user_activity",
    "channel_summary": "channel_summary",
    "triggers": "triggers",
    "riassunto": "riassunto",
    "resoconto": "resoconto",
    "aura": "aura",
    "aura_render": "aura",
    "attivita": "attivita",
    "barcello": "barcello",
    "message_scheduler": "message_scheduler",
    "admin": None,
    "commands": None,
    "command_helpers": None,
    "ctx": None,
    "settings": None,
    "permissions": None,
    "__init__": None,
}


@dataclass(slots=True)
class FooterMeta:
    service_name: str
    contributors: list[str]
    used_local_processing: bool = False
    footer_icon_url: str | None = None


@dataclass(slots=True)
class ServiceFooterProfile:
    service_name: str
    contributors: list[str]
    used_local_processing: bool
    last_rendered_footer: str | None = None
    updated_at: str | None = None
    origins: set[str] | None = None


_EMBED_META: dict[int, tuple[discord.Embed, FooterMeta]] = {}


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _truncate(text: str, max_len: int = FOOTER_MAX_LEN) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _normalize_service_name_from_stem(stem: str) -> str | None:
    override = _SERVICE_NAME_OVERRIDES.get(stem)
    if override is not None:
        return override
    if stem in _SERVICE_NAME_OVERRIDES and override is None:
        return None

    name = stem
    for suffix in ("_renderer", "_service", "_transcribe", "_render"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    name = name.strip("_")
    return name or None


def attach_footer_meta(
    embed: discord.Embed,
    *,
    service_name: str,
    contributors: Iterable[str] | None = None,
    used_local_processing: bool = False,
    footer_icon_url: str | None = None,
) -> discord.Embed:
    if embed is None:
        raise ValueError("attach_footer_meta requires a discord.Embed instance, got None")

    deduped: list[str] = []
    seen: set[str] = set()
    for entry in contributors or []:
        item = _clean(entry)
        if not item or item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    _EMBED_META[id(embed)] = (
        embed,
        FooterMeta(
            service_name=_clean(service_name) or "unknown",
            contributors=deduped,
            used_local_processing=used_local_processing,
            footer_icon_url=_clean(footer_icon_url) or None,
        ),
    )
    return embed


def attach_footer_meta_to_all(
    embeds: Iterable[discord.Embed] | None,
    *,
    service_name: str,
    contributors: Iterable[str] | None = None,
    used_local_processing: bool = False,
    footer_icon_url: str | None = None,
) -> list[discord.Embed]:
    embed_list = list(embeds or [])
    for embed in embed_list:
        attach_footer_meta(
            embed,
            service_name=service_name,
            contributors=contributors,
            used_local_processing=used_local_processing,
            footer_icon_url=footer_icon_url,
        )
    return embed_list


def get_footer_meta(embed: discord.Embed) -> FooterMeta | None:
    if embed is None:
        return None
    stored = _EMBED_META.get(id(embed))
    if stored is None:
        return None
    stored_embed, meta = stored
    if stored_embed is not embed:
        _EMBED_META.pop(id(embed), None)
        return None
    return meta


def pop_footer_meta(embed: discord.Embed) -> FooterMeta | None:
    if embed is None:
        return None
    stored = _EMBED_META.pop(id(embed), None)
    if stored is None:
        return None
    stored_embed, meta = stored
    if stored_embed is not embed:
        return None
    return meta


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
        self._known_services: set[str] = set()
        self._known_service_sources: dict[str, set[str]] = {}
        self._service_profiles: dict[str, ServiceFooterProfile] = {}
        self._known_services_loaded = False

    async def set_version(self, version: str | None) -> None:
        await self._set_or_clear(FOOTER_VERSION_KEY, version)

    async def set_global_phrase(self, phrase: str | None) -> None:
        await self._set_or_clear(FOOTER_GLOBAL_PHRASE_KEY, phrase)

    async def set_service_phrase(self, service_name: str, phrase: str | None) -> None:
        service = _clean(service_name)
        if not service:
            return
        await self._set_or_clear(f"{FOOTER_SERVICE_PHRASE_PREFIX}{service}", phrase)
        await self.register_known_service(service, source="db")

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

    async def sync_known_services_on_startup(self) -> list[str]:
        startup_services = self._scan_services_from_codebase()
        db_services = await self._load_services_from_phrase_keys()
        persisted_services, persisted_sources = await self._load_known_services_from_settings()

        merged: set[str] = set(startup_services) | set(db_services) | set(persisted_services) | set(SUPPORTED_FOOTER_SERVICES)
        sources: dict[str, set[str]] = {}
        for service in merged:
            origins: set[str] = set()
            if service in startup_services:
                origins.add("startup")
            if service in db_services:
                origins.add("db")
            if service in persisted_services:
                origins.update(persisted_sources.get(service, {"db"}))
            sources[service] = origins or {"startup"}

        self._known_services = merged
        self._known_service_sources = sources
        self._known_services_loaded = True
        await self._persist_known_services()
        logger.info("footer known services sync completed: count=%s", len(self._known_services))
        return self.get_known_services_cached()

    async def register_known_service(self, service_name: str, *, source: str) -> None:
        service = _clean(service_name)
        if not service:
            return
        if not self._known_services_loaded:
            persisted, persisted_sources = await self._load_known_services_from_settings()
            self._known_services = set(persisted)
            self._known_service_sources = {k: set(v) for k, v in persisted_sources.items()}
            self._known_services_loaded = True

        before = service in self._known_services and source in self._known_service_sources.get(service, set())
        self._known_services.add(service)
        self._known_service_sources.setdefault(service, set()).add(source)
        if before:
            return
        await self._persist_known_services()

    async def get_known_services(self) -> list[str]:
        if not self._known_services_loaded:
            persisted, persisted_sources = await self._load_known_services_from_settings()
            self._known_services = set(persisted)
            self._known_service_sources = {k: set(v) for k, v in persisted_sources.items()}
            self._known_services_loaded = True
        return self.get_known_services_cached()

    def get_known_services_cached(self) -> list[str]:
        return sorted(self._known_services)

    async def get_known_service_sources(self) -> dict[str, list[str]]:
        await self.get_known_services()
        return {service: sorted(origins) for service, origins in sorted(self._known_service_sources.items())}

    async def record_service_footer_profile(
        self,
        *,
        service_name: str,
        contributors: Iterable[str],
        used_local_processing: bool,
        last_rendered_footer: str | None = None,
        origin: str = "runtime",
    ) -> ServiceFooterProfile:
        service = _clean(service_name) or "unknown"
        deduped = self._dedupe_contributors(contributors)
        existing = await self.get_service_footer_profile(service)
        origins = set(existing.origins) if existing and existing.origins else set()
        if origin:
            origins.add(_clean(origin) or origin)
        profile = ServiceFooterProfile(
            service_name=service,
            contributors=deduped,
            used_local_processing=used_local_processing,
            last_rendered_footer=_clean(last_rendered_footer) or None,
            updated_at=datetime.now(timezone.utc).isoformat(),
            origins=origins or {"runtime"},
        )
        self._service_profiles[service] = profile
        await self._database.set_setting(
            f"{FOOTER_LAST_META_PREFIX}{service}",
            json.dumps(self._profile_to_dict(profile), ensure_ascii=False),
        )
        await self.register_known_service(service, source=origin)
        return profile

    async def get_service_footer_profile(self, service_name: str) -> ServiceFooterProfile | None:
        service = _clean(service_name)
        if not service:
            return None
        if service in self._service_profiles:
            return self._service_profiles[service]
        raw = await self._database.get_setting(f"{FOOTER_LAST_META_PREFIX}{service}")
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("invalid JSON in %s%s", FOOTER_LAST_META_PREFIX, service)
            return None
        profile = self._parse_profile(service, parsed)
        if profile is None:
            return None
        self._service_profiles[service] = profile
        return profile

    async def get_service_footer_profiles(self) -> dict[str, ServiceFooterProfile]:
        await self.get_known_services()
        profiles: dict[str, ServiceFooterProfile] = {}
        for service in self._known_services:
            profile = await self.get_service_footer_profile(service)
            if profile is not None:
                profiles[service] = profile
        return profiles

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

        if not contributors_deduped or contributors_deduped == ["in loco"]:
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
        meta = pop_footer_meta(embed)
        if meta is None:
            meta = FooterMeta(service_name=_clean(default_service_name) or "unknown", contributors=[], used_local_processing=False)
        await self.register_known_service(meta.service_name, source="runtime")
        text, _ = await self.render_footer(
            service_name=meta.service_name,
            contributors=meta.contributors,
            used_local_processing=meta.used_local_processing,
        )
        await self.record_service_footer_profile(
            service_name=meta.service_name,
            contributors=meta.contributors,
            used_local_processing=meta.used_local_processing,
            last_rendered_footer=text,
            origin="runtime",
        )
        embed.set_footer(text=text, icon_url=meta.footer_icon_url)
        return embed

    def _dedupe_contributors(self, contributors: Iterable[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for item in contributors:
            clean = _clean(item)
            if not clean or clean in seen:
                continue
            out.append(clean)
            seen.add(clean)
        return out

    def _parse_profile(self, service_name: str, payload: object) -> ServiceFooterProfile | None:
        if not isinstance(payload, dict):
            return None
        contributors_raw = payload.get("contributors", [])
        contributors = self._dedupe_contributors(contributors_raw if isinstance(contributors_raw, list) else [])
        used_local_processing = bool(payload.get("used_local_processing", False))
        last_rendered_footer = _clean(str(payload.get("last_rendered_footer") or "")) or None
        updated_at = _clean(str(payload.get("updated_at") or "")) or None
        origins_raw = payload.get("origins", [])
        origins = {
            _clean(str(item))
            for item in origins_raw
            if _clean(str(item))
        } if isinstance(origins_raw, list) else set()
        return ServiceFooterProfile(
            service_name=service_name,
            contributors=contributors,
            used_local_processing=used_local_processing,
            last_rendered_footer=last_rendered_footer,
            updated_at=updated_at,
            origins=origins or {"runtime"},
        )

    def _profile_to_dict(self, profile: ServiceFooterProfile) -> dict[str, object]:
        return {
            "service_name": profile.service_name,
            "contributors": list(profile.contributors),
            "used_local_processing": profile.used_local_processing,
            "last_rendered_footer": profile.last_rendered_footer,
            "updated_at": profile.updated_at,
            "origins": sorted(profile.origins or []),
        }

    def _scan_services_from_codebase(self) -> set[str]:
        found: set[str] = set()
        for directory in _STARTUP_SERVICE_SCAN_DIRS:
            if not directory.exists():
                continue
            for path in directory.glob("*.py"):
                stem = path.stem
                service_name = _normalize_service_name_from_stem(stem)
                if not service_name:
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                if "discord.Embed" not in text and "attach_footer_meta(" not in text:
                    continue
                found.add(service_name)
        return found

    async def _load_services_from_phrase_keys(self) -> set[str]:
        phrases = await self.get_service_phrases()
        return set(phrases.keys())

    async def _load_known_services_from_settings(self) -> tuple[list[str], dict[str, set[str]]]:
        raw = await self._database.get_setting(FOOTER_KNOWN_SERVICES_KEY)
        raw_sources = await self._database.get_setting(FOOTER_KNOWN_SERVICE_SOURCES_KEY)

        services: list[str] = []
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    services = sorted({_clean(str(item)) for item in parsed if _clean(str(item))})
            except json.JSONDecodeError:
                logger.warning("invalid JSON in %s", FOOTER_KNOWN_SERVICES_KEY)

        sources: dict[str, set[str]] = {}
        if raw_sources:
            try:
                parsed_sources = json.loads(raw_sources)
                if isinstance(parsed_sources, dict):
                    for service, origin_list in parsed_sources.items():
                        service_clean = _clean(str(service))
                        if not service_clean:
                            continue
                        if isinstance(origin_list, list):
                            cleaned_origins = {_clean(str(origin)) for origin in origin_list if _clean(str(origin))}
                            if cleaned_origins:
                                sources[service_clean] = cleaned_origins
            except json.JSONDecodeError:
                logger.warning("invalid JSON in %s", FOOTER_KNOWN_SERVICE_SOURCES_KEY)

        for service in services:
            sources.setdefault(service, {"db"})
        return services, sources

    async def _persist_known_services(self) -> None:
        services = sorted(self._known_services)
        sources = {service: sorted(self._known_service_sources.get(service, {"startup"})) for service in services}
        await self._database.set_setting(FOOTER_KNOWN_SERVICES_KEY, json.dumps(services, ensure_ascii=False))
        await self._database.set_setting(FOOTER_KNOWN_SERVICE_SOURCES_KEY, json.dumps(sources, ensure_ascii=False))

    async def _set_or_clear(self, key: str, value: str | None) -> None:
        cleaned = _clean(value)
        if not cleaned:
            await self._database.execute("DELETE FROM settings WHERE key = ?", (key,))
            await self._database.commit()
            return
        await self._database.set_setting(key, cleaned)
