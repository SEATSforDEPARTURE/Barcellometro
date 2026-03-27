from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Iterable

import discord

from app.services.database import DatabaseService
from app.services.footer import SUPPORTED_FOOTER_SERVICES, footer_service_category, get_footer_meta, normalize_footer_thumbnail

logger = logging.getLogger(__name__)

AUTHOR_ENABLED_KEY = "author.enabled"
AUTHOR_VERSION_KEY = "author.version"
AUTHOR_GLOBAL_PHRASE_KEY = "author.global_phrase"
AUTHOR_GLOBAL_THUMBNAIL_KEY = "author.global_thumbnail"
AUTHOR_GLOBAL_URL_KEY = "author.global_url"
AUTHOR_SERVICE_PHRASE_PREFIX = "author.service_phrase."
AUTHOR_SERVICE_THUMBNAIL_PREFIX = "author.service_thumbnail."
AUTHOR_SERVICE_URL_PREFIX = "author.service_url."
AUTHOR_KNOWN_SERVICES_KEY = "author.known_services"
AUTHOR_KNOWN_SERVICE_SOURCES_KEY = "author.known_service_sources"
AUTHOR_LAST_META_PREFIX = "author.last_meta."
AUTHOR_SEPARATOR = " · "
AUTHOR_MAX_LEN = 256

SUPPORTED_AUTHOR_SERVICES: tuple[str, ...] = SUPPORTED_FOOTER_SERVICES

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
    "inactive_members_moderation": "inactivity_moderation",
    "member_flow_notifications": "member_flow_notifications",
    "author": None,
    "footer": None,
    "admin": None,
    "commands": None,
    "ctx": None,
    "settings": None,
    "permissions": None,
    "__init__": None,
}

_SERVICE_CANONICAL_TOP_LEVEL_FALLBACKS: dict[str, str] = {
    "status": "embed",
    "embed": "embed",
    "riassunto": "dmchannelsummary",
    "barcello": "dmchannelsummary",
    "activity_dm": "dmserversummary",
    "attivita": "dmserversummary",
    "resoconto": "channelsummary",
    "daily_resoconto": "serversummary",
    "daily_activity_report": "serversummary",
    "user_activity": "serversummary",
    "audio_notes": "audionotes",
    "audio_notes_transcribe": "audionotes",
    "channel_summary": "channelsummary",
    "server_summary": "serversummary",
    "aura": "dmserversummary",
    "voice_ingest": "voiceingest",
}

_CANONICAL_TOP_LEVEL_ALIASES: dict[str, str] = {
    "ask": "qna",
    "domanda": "qna",
    "riassunto": "dmchannelsummary",
    "aura": "dmserversummary",
    "dmsummary": "dmchannelsummary",
    "barcellosummary": "dmchannelsummary",
    "aurasummary": "dmserversummary",
    "activitysummary": "dmserversummary",
    "resocontocanale": "channelsummary",
    "resocontoserver": "serversummary",
}

_CANONICAL_TOP_LEVEL_LABELS: dict[str, str] = {
    "channelsummary": "CHANNEL SUMMARY",
    "serversummary": "SERVER SUMMARY",
    "dmchannelsummary": "DM CHANNEL SUMMARY",
    "audionotes": "AUDIO NOTES",
    "dmserversummary": "DM SERVER SUMMARY",
    "commandguard": "COMMAND GUARD",
    "voiceingest": "VOICE INGEST",
    "qna": "QNA",
    "embed": "EMBED",
}


@dataclass(slots=True)
class AuthorMeta:
    service_name: str
    canonical_top_level_command: str | None = None
    author_icon_url: str | None = None
    author_url: str | None = None
    minimal: bool = False
    skip: bool = False
    preserve_existing: bool = False


@dataclass(slots=True)
class ServiceAuthorProfile:
    service_name: str
    last_rendered_author: str | None = None
    last_icon_url: str | None = None
    updated_at: str | None = None
    origins: set[str] | None = None


@dataclass(slots=True)
class AuthorStatusServiceEntry:
    service_name: str
    category: int
    known_sources: list[str]
    phrase: str | None
    phrase_origin: str
    rendered_author: str
    rendered_url: str | None
    rendered_thumbnail: str | None
    service_phrase_override: bool = False
    service_thumbnail_override: bool = False
    service_url_override: bool = False
    persisted_profile: ServiceAuthorProfile | None = None


@dataclass(slots=True)
class AuthorStatusSnapshot:
    enabled: bool
    version: str | None
    global_phrase: str | None
    global_thumbnail: str | None
    global_url: str | None
    services: list[AuthorStatusServiceEntry]


_EMBED_META: dict[int, tuple[discord.Embed, AuthorMeta]] = {}


class InvalidAuthorThumbnailError(ValueError):
    pass


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _truncate(text: str, max_len: int = AUTHOR_MAX_LEN) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _is_persistable_service_name(name: str | None) -> bool:
    service = _clean(name)
    return bool(service and service not in {"unknown", "default", "fallback"})


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


def normalize_author_thumbnail(value: str | None) -> str:
    try:
        return normalize_footer_thumbnail(value)
    except ValueError as exc:
        raise InvalidAuthorThumbnailError(str(exc)) from exc


def _normalize_optional_thumbnail(value: str | None) -> str | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    return normalize_author_thumbnail(cleaned)


def _normalize_canonical_top_level_command(value: str | None) -> str | None:
    normalized = _clean(value).lower()
    if not normalized:
        return None
    return _CANONICAL_TOP_LEVEL_ALIASES.get(normalized, normalized)


def resolve_canonical_top_level_command(
    *,
    canonical_top_level_command: str | None = None,
    service_name: str | None = None,
) -> str:
    canonical = _normalize_canonical_top_level_command(canonical_top_level_command)
    if canonical:
        return canonical
    normalized_service = _clean(service_name).lower()
    if normalized_service in _SERVICE_CANONICAL_TOP_LEVEL_FALLBACKS:
        mapped = _SERVICE_CANONICAL_TOP_LEVEL_FALLBACKS[normalized_service]
        canonical_fallback = _normalize_canonical_top_level_command(mapped)
        if canonical_fallback:
            return canonical_fallback
    return _normalize_canonical_top_level_command(normalized_service) or "unknown"


def human_author_service_name(service_name: str, canonical_top_level_command: str | None = None) -> str:
    canonical = resolve_canonical_top_level_command(
        canonical_top_level_command=canonical_top_level_command,
        service_name=service_name,
    )
    if canonical in _CANONICAL_TOP_LEVEL_LABELS:
        return _CANONICAL_TOP_LEVEL_LABELS[canonical]
    return canonical.replace("_", " ").upper()


def render_author_name(
    *,
    service_name: str,
    canonical_top_level_command: str | None = None,
    phrase: str | None = None,
    version: str | None = None,
) -> str:
    clean_phrase = _clean(phrase)
    clean_version = _clean(version)
    if clean_phrase:
        parts = [clean_phrase]
        if clean_version:
            parts.append(clean_version)
        return _truncate(AUTHOR_SEPARATOR.join(parts))
    return _truncate(
        f"servizio {human_author_service_name(service_name=service_name, canonical_top_level_command=canonical_top_level_command)}"
    )


def render_author_name_with_page(
    *,
    service_name: str,
    canonical_top_level_command: str | None = None,
    phrase: str | None = None,
    version: str | None = None,
    page_index: int | None = None,
    page_total: int | None = None,
) -> str:
    base = render_author_name(
        service_name=service_name,
        canonical_top_level_command=canonical_top_level_command,
        phrase=phrase,
        version=version,
    )
    if page_index is not None and page_total is not None and page_total > 1:
        return _truncate(f"{base}{AUTHOR_SEPARATOR}(Pag. {page_index}/{page_total})")
    return base



def attach_author_meta(
    embed: discord.Embed,
    *,
    service_name: str,
    canonical_top_level_command: str | None = None,
    author_icon_url: str | None = None,
    author_url: str | None = None,
    minimal: bool = False,
    skip: bool = False,
    preserve_existing: bool = False,
) -> discord.Embed:
    if embed is None:
        raise ValueError("attach_author_meta requires a discord.Embed instance, got None")
    _EMBED_META[id(embed)] = (
        embed,
        AuthorMeta(
            service_name=_clean(service_name) or "unknown",
            canonical_top_level_command=_normalize_canonical_top_level_command(canonical_top_level_command),
            author_icon_url=_clean(author_icon_url) or None,
            author_url=_clean(author_url) or None,
            minimal=bool(minimal),
            skip=bool(skip),
            preserve_existing=bool(preserve_existing),
        ),
    )
    return embed



def attach_author_meta_to_all(
    embeds: Iterable[discord.Embed] | None,
    *,
    service_name: str,
    canonical_top_level_command: str | None = None,
    author_icon_url: str | None = None,
    author_url: str | None = None,
    minimal: bool = False,
    skip: bool = False,
    preserve_existing: bool = False,
) -> list[discord.Embed]:
    embed_list = list(embeds or [])
    for embed in embed_list:
        attach_author_meta(
            embed,
            service_name=service_name,
            canonical_top_level_command=canonical_top_level_command,
            author_icon_url=author_icon_url,
            author_url=author_url,
            minimal=minimal,
            skip=skip,
            preserve_existing=preserve_existing,
        )
    return embed_list



def get_author_meta(embed: discord.Embed) -> AuthorMeta | None:
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



def pop_author_meta(embed: discord.Embed) -> AuthorMeta | None:
    if embed is None:
        return None
    stored = _EMBED_META.pop(id(embed), None)
    if stored is None:
        return None
    stored_embed, meta = stored
    if stored_embed is not embed:
        return None
    return meta



def copy_author_meta(source: discord.Embed, target: discord.Embed) -> discord.Embed:
    meta = get_author_meta(source)
    if meta is None:
        return target
    return attach_author_meta(
        target,
        service_name=meta.service_name,
        canonical_top_level_command=meta.canonical_top_level_command,
        author_icon_url=meta.author_icon_url,
        author_url=meta.author_url,
        minimal=meta.minimal,
        skip=meta.skip,
        preserve_existing=meta.preserve_existing,
    )


class AuthorService:
    def __init__(self, database: DatabaseService) -> None:
        self._database = database
        self._known_services: set[str] = set()
        self._known_service_sources: dict[str, set[str]] = {}
        self._service_profiles: dict[str, ServiceAuthorProfile] = {}
        self._known_services_loaded = False

    async def set_enabled(self, enabled: bool) -> None:
        await self._database.set_setting(AUTHOR_ENABLED_KEY, "true" if enabled else "false")

    async def is_enabled(self) -> bool:
        stored = await self._database.get_setting(AUTHOR_ENABLED_KEY)
        if stored is None:
            await self._database.set_setting(AUTHOR_ENABLED_KEY, "true")
            return True
        return stored.lower() in {"1", "true", "yes", "y"}

    async def set_version(self, version: str | None) -> None:
        await self._set_or_clear(AUTHOR_VERSION_KEY, version)

    async def set_global_phrase(self, phrase: str | None) -> None:
        await self._set_or_clear(AUTHOR_GLOBAL_PHRASE_KEY, phrase)

    async def set_global_thumbnail(self, thumbnail: str | None) -> None:
        await self._set_or_clear(AUTHOR_GLOBAL_THUMBNAIL_KEY, _normalize_optional_thumbnail(thumbnail))

    async def set_global_url(self, url: str | None) -> None:
        await self._set_or_clear(AUTHOR_GLOBAL_URL_KEY, url)

    async def set_service_phrase(self, service_name: str, phrase: str | None) -> None:
        service = _clean(service_name)
        if not service:
            return
        await self._set_or_clear(f"{AUTHOR_SERVICE_PHRASE_PREFIX}{service}", phrase)
        await self.register_known_service(service, source="db")

    async def set_service_thumbnail(self, service_name: str, thumbnail: str | None) -> None:
        service = _clean(service_name)
        if not service:
            return
        await self._set_or_clear(f"{AUTHOR_SERVICE_THUMBNAIL_PREFIX}{service}", _normalize_optional_thumbnail(thumbnail))
        await self.register_known_service(service, source="db")

    async def set_service_url(self, service_name: str, url: str | None) -> None:
        service = _clean(service_name)
        if not service:
            return
        await self._set_or_clear(f"{AUTHOR_SERVICE_URL_PREFIX}{service}", url)
        await self.register_known_service(service, source="db")

    async def get_version(self) -> str | None:
        return _clean(await self._database.get_setting(AUTHOR_VERSION_KEY)) or None

    async def get_global_phrase(self) -> str | None:
        return _clean(await self._database.get_setting(AUTHOR_GLOBAL_PHRASE_KEY)) or None

    async def get_global_thumbnail(self) -> str | None:
        return _clean(await self._database.get_setting(AUTHOR_GLOBAL_THUMBNAIL_KEY)) or None

    async def get_global_url(self) -> str | None:
        return _clean(await self._database.get_setting(AUTHOR_GLOBAL_URL_KEY)) or None

    async def get_service_phrases(self) -> dict[str, str]:
        return await self._get_prefixed_settings(AUTHOR_SERVICE_PHRASE_PREFIX)

    async def get_service_thumbnails(self) -> dict[str, str]:
        return await self._get_prefixed_settings(AUTHOR_SERVICE_THUMBNAIL_PREFIX)

    async def get_service_urls(self) -> dict[str, str]:
        return await self._get_prefixed_settings(AUTHOR_SERVICE_URL_PREFIX)

    async def _get_prefixed_settings(self, prefix: str) -> dict[str, str]:
        rows = await self._database.fetchall(
            "SELECT key, value FROM settings WHERE key LIKE ? ORDER BY key",
            (f"{prefix}%",),
        )
        out: dict[str, str] = {}
        for row in rows:
            key = row["key"]
            value = _clean(row["value"])
            if not value:
                continue
            out[key.replace(prefix, "", 1)] = value
        return out

    async def sync_known_services_on_startup(self) -> list[str]:
        startup_services = self._scan_services_from_codebase()
        db_services = await self._load_services_from_template_keys()
        persisted_services, persisted_sources = await self._load_known_services_from_settings()
        merged: set[str] = {
            service
            for service in (set(startup_services) | set(db_services) | set(persisted_services) | set(SUPPORTED_AUTHOR_SERVICES))
            if _is_persistable_service_name(service)
        }
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
        logger.info("author known services sync completed: count=%s", len(self._known_services))
        return self.get_known_services_cached()

    async def register_known_service(self, service_name: str, *, source: str) -> None:
        service = _clean(service_name)
        if not _is_persistable_service_name(service):
            return
        if not self._known_services_loaded:
            persisted, persisted_sources = await self._load_known_services_from_settings()
            self._known_services = set(persisted)
            self._known_service_sources = {k: set(v) for k, v in persisted_sources.items()}
            self._known_services_loaded = True
        before = service in self._known_services and source in self._known_service_sources.get(service, set())
        self._known_services.add(service)
        self._known_service_sources.setdefault(service, set()).add(source)
        if not before:
            await self._persist_known_services()

    async def get_known_services(self) -> list[str]:
        if not self._known_services_loaded:
            persisted, persisted_sources = await self._load_known_services_from_settings()
            self._known_services = set(persisted)
            self._known_service_sources = {k: set(v) for k, v in persisted_sources.items()}
            self._known_services_loaded = True
        return self.get_known_services_cached()

    def get_known_services_cached(self) -> list[str]:
        return sorted(service for service in self._known_services if _is_persistable_service_name(service))

    async def get_known_service_sources(self) -> dict[str, list[str]]:
        await self.get_known_services()
        return {
            service: sorted(origins)
            for service, origins in sorted(self._known_service_sources.items())
            if _is_persistable_service_name(service)
        }

    async def record_service_author(
        self,
        *,
        service_name: str,
        last_rendered_author: str,
        last_icon_url: str | None,
        origin: str = "runtime",
    ) -> ServiceAuthorProfile | None:
        service = _clean(service_name)
        if not _is_persistable_service_name(service):
            return None
        existing = await self.get_service_profile(service)
        origins = set(existing.origins) if existing and existing.origins else set()
        if origin:
            origins.add(_clean(origin) or origin)
        profile = ServiceAuthorProfile(
            service_name=service,
            last_rendered_author=_clean(last_rendered_author) or None,
            last_icon_url=_clean(last_icon_url) or None,
            updated_at=datetime.now(timezone.utc).isoformat(),
            origins=origins or {"runtime"},
        )
        self._service_profiles[service] = profile
        await self._database.set_setting(
            f"{AUTHOR_LAST_META_PREFIX}{service}",
            json.dumps(self._profile_to_dict(profile), ensure_ascii=False),
        )
        await self.register_known_service(service, source=origin)
        return profile

    async def get_service_profile(self, service_name: str) -> ServiceAuthorProfile | None:
        service = _clean(service_name)
        if not service:
            return None
        if service in self._service_profiles:
            return self._service_profiles[service]
        raw = await self._database.get_setting(f"{AUTHOR_LAST_META_PREFIX}{service}")
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("invalid JSON in %s%s", AUTHOR_LAST_META_PREFIX, service)
            return None
        profile = self._parse_profile(service, parsed)
        if profile is not None:
            self._service_profiles[service] = profile
        return profile

    async def get_service_profiles(self) -> dict[str, ServiceAuthorProfile]:
        await self.get_known_services()
        profiles: dict[str, ServiceAuthorProfile] = {}
        for service in self._known_services:
            profile = await self.get_service_profile(service)
            if profile is not None:
                profiles[service] = profile
        return profiles

    async def _resolve_phrase(self, service_name: str) -> tuple[str | None, str]:
        service_phrases = await self.get_service_phrases()
        global_phrase = await self.get_global_phrase()
        if service_name in service_phrases:
            return service_phrases[service_name], "service"
        if global_phrase:
            return global_phrase, "global"
        return None, "fallback"

    async def _resolve_thumbnail(self, service_name: str, *, explicit_icon_url: str | None = None) -> str | None:
        if _clean(explicit_icon_url):
            return _clean(explicit_icon_url) or None
        service_thumbnails = await self.get_service_thumbnails()
        if service_thumbnails.get(service_name):
            return service_thumbnails[service_name]
        return await self.get_global_thumbnail()

    async def _resolve_url(self, service_name: str, *, explicit_url: str | None = None) -> str | None:
        if _clean(explicit_url):
            return _clean(explicit_url) or None
        service_urls = await self.get_service_urls()
        if service_urls.get(service_name):
            return service_urls[service_name]
        return await self.get_global_url()

    async def render_author(
        self,
        *,
        service_name: str,
        canonical_top_level_command: str | None = None,
        explicit_icon_url: str | None = None,
        explicit_url: str | None = None,
        minimal: bool = False,
        page_index: int | None = None,
        page_total: int | None = None,
    ) -> tuple[str, str | None, str | None, str]:
        icon_url = await self._resolve_thumbnail(service_name, explicit_icon_url=explicit_icon_url)
        url = await self._resolve_url(service_name, explicit_url=explicit_url)
        if minimal:
            return (
                render_author_name_with_page(
                    service_name=service_name,
                    canonical_top_level_command=canonical_top_level_command,
                    page_index=page_index,
                    page_total=page_total,
                ),
                icon_url,
                url,
                "fallback",
            )
        phrase, phrase_origin = await self._resolve_phrase(service_name)
        version = await self.get_version()
        return (
            render_author_name_with_page(
                service_name=service_name,
                canonical_top_level_command=canonical_top_level_command,
                phrase=phrase,
                version=version,
                page_index=page_index,
                page_total=page_total,
            ),
            icon_url,
            url,
            phrase_origin,
        )

    async def apply(
        self,
        embed: discord.Embed,
        *,
        default_service_name: str = "unknown",
        page_index: int | None = None,
        page_total: int | None = None,
    ) -> discord.Embed:
        author_name_before = getattr(embed.author, "name", None)
        meta = pop_author_meta(embed)
        if meta is None:
            footer_meta = get_footer_meta(embed)
            service_name = footer_meta.service_name if footer_meta is not None else _clean(default_service_name) or "unknown"
            meta = AuthorMeta(service_name=service_name, preserve_existing=True)
        if meta.skip:
            return embed
        if author_name_before and meta.preserve_existing:
            return embed
        persistable = _is_persistable_service_name(meta.service_name)
        if persistable:
            await self.register_known_service(meta.service_name, source="runtime")
        author_name, resolved_icon_url, resolved_url, _ = await self.render_author(
            service_name=meta.service_name,
            canonical_top_level_command=meta.canonical_top_level_command,
            explicit_icon_url=meta.author_icon_url,
            explicit_url=meta.author_url,
            minimal=meta.minimal,
            page_index=page_index,
            page_total=page_total,
        )
        embed.set_author(name=author_name, icon_url=resolved_icon_url, url=resolved_url)
        if persistable:
            try:
                await self.record_service_author(
                    service_name=meta.service_name,
                    last_rendered_author=author_name,
                    last_icon_url=resolved_icon_url,
                    origin="runtime",
                )
            except Exception as exc:  # noqa: BLE001
                if "database is locked" in str(exc).lower():
                    logger.warning("Author profile persistence skipped due to SQLite lock service=%s", meta.service_name)
                else:
                    logger.warning("Author profile persistence failed service=%s err=%s", meta.service_name, exc)
        return embed

    async def build_status_snapshot(self) -> AuthorStatusSnapshot:
        enabled = await self.is_enabled()
        version = await self.get_version()
        global_phrase = await self.get_global_phrase()
        global_thumbnail = await self.get_global_thumbnail()
        global_url = await self.get_global_url()
        service_phrases = await self.get_service_phrases()
        service_thumbnails = await self.get_service_thumbnails()
        service_urls = await self.get_service_urls()
        known_services = await self.get_known_services()
        service_sources = await self.get_known_service_sources()
        profile_map = await self.get_service_profiles()

        entries: list[AuthorStatusServiceEntry] = []
        services = sorted(set(known_services), key=lambda name: (footer_service_category(name), name))
        for service_name in services:
            if not _is_persistable_service_name(service_name):
                continue
            rendered_author, rendered_thumbnail, rendered_url, phrase_origin = await self.render_author(service_name=service_name)
            phrase = service_phrases.get(service_name) if service_name in service_phrases else global_phrase
            entries.append(
                AuthorStatusServiceEntry(
                    service_name=service_name,
                    category=footer_service_category(service_name),
                    known_sources=service_sources.get(service_name, []),
                    phrase=phrase,
                    phrase_origin="service" if service_name in service_phrases else ("global" if global_phrase else "fallback"),
                    rendered_author=rendered_author,
                    rendered_url=rendered_url,
                    rendered_thumbnail=rendered_thumbnail,
                    service_phrase_override=service_name in service_phrases,
                    service_thumbnail_override=service_name in service_thumbnails,
                    service_url_override=service_name in service_urls,
                    persisted_profile=profile_map.get(service_name),
                )
            )
        return AuthorStatusSnapshot(
            enabled=enabled,
            version=version,
            global_phrase=global_phrase,
            global_thumbnail=global_thumbnail,
            global_url=global_url,
            services=entries,
        )

    def _scan_services_from_codebase(self) -> set[str]:
        found: set[str] = set()
        for directory in _STARTUP_SERVICE_SCAN_DIRS:
            if not directory.exists():
                continue
            for path in directory.glob("*.py"):
                stem = path.stem
                service_name = _normalize_service_name_from_stem(stem)
                if not service_name or not _is_persistable_service_name(service_name):
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                if "attach_footer_meta(" not in text and "attach_author_meta(" not in text and "set_author(" not in text:
                    continue
                found.add(service_name)
        return found

    async def _load_services_from_template_keys(self) -> set[str]:
        phrases = await self.get_service_phrases()
        thumbnails = await self.get_service_thumbnails()
        urls = await self.get_service_urls()
        return set(phrases.keys()) | set(thumbnails.keys()) | set(urls.keys())

    async def _load_known_services_from_settings(self) -> tuple[list[str], dict[str, set[str]]]:
        raw = await self._database.get_setting(AUTHOR_KNOWN_SERVICES_KEY)
        raw_sources = await self._database.get_setting(AUTHOR_KNOWN_SERVICE_SOURCES_KEY)
        services: list[str] = []
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    services = sorted({s for item in parsed if _is_persistable_service_name(s := _clean(str(item)))})
            except json.JSONDecodeError:
                logger.warning("invalid JSON in %s", AUTHOR_KNOWN_SERVICES_KEY)
        sources: dict[str, set[str]] = {}
        if raw_sources:
            try:
                parsed_sources = json.loads(raw_sources)
                if isinstance(parsed_sources, dict):
                    for service, origin_list in parsed_sources.items():
                        service_clean = _clean(str(service))
                        if not _is_persistable_service_name(service_clean):
                            continue
                        if isinstance(origin_list, list):
                            cleaned_origins = {_clean(str(origin)) for origin in origin_list if _clean(str(origin))}
                            if cleaned_origins:
                                sources[service_clean] = cleaned_origins
            except json.JSONDecodeError:
                logger.warning("invalid JSON in %s", AUTHOR_KNOWN_SERVICE_SOURCES_KEY)
        for service in services:
            sources.setdefault(service, {"db"})
        return services, sources

    async def _persist_known_services(self) -> None:
        services = sorted(service for service in self._known_services if _is_persistable_service_name(service))
        sources = {service: sorted(self._known_service_sources.get(service, {"startup"})) for service in services}
        await self._database.set_setting(AUTHOR_KNOWN_SERVICES_KEY, json.dumps(services, ensure_ascii=False))
        await self._database.set_setting(AUTHOR_KNOWN_SERVICE_SOURCES_KEY, json.dumps(sources, ensure_ascii=False))

    async def _set_or_clear(self, key: str, value: str | None) -> None:
        cleaned = _clean(value)
        if not cleaned:
            delete_setting = getattr(self._database, "delete_setting", None)
            if callable(delete_setting):
                await delete_setting(key)
            else:
                await self._database.execute("DELETE FROM settings WHERE key = ?", (key,))
            return
        await self._database.set_setting(key, cleaned)

    def _parse_profile(self, service_name: str, payload: object) -> ServiceAuthorProfile | None:
        if not isinstance(payload, dict):
            return None
        origins_raw = payload.get("origins", [])
        origins = {
            _clean(str(item))
            for item in origins_raw
            if _clean(str(item))
        } if isinstance(origins_raw, list) else set()
        return ServiceAuthorProfile(
            service_name=service_name,
            last_rendered_author=_clean(str(payload.get("last_rendered_author") or "")) or None,
            last_icon_url=_clean(str(payload.get("last_icon_url") or "")) or None,
            updated_at=_clean(str(payload.get("updated_at") or "")) or None,
            origins=origins or {"runtime"},
        )

    def _profile_to_dict(self, profile: ServiceAuthorProfile) -> dict[str, object]:
        return {
            "service_name": profile.service_name,
            "last_rendered_author": profile.last_rendered_author,
            "last_icon_url": profile.last_icon_url,
            "updated_at": profile.updated_at,
            "origins": sorted(profile.origins or []),
        }
