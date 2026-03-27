from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EmbedTemplateSystem = Literal["author", "footer", "description", "images"]


@dataclass(frozen=True, slots=True)
class PublicEmbedService:
    key: str
    label: str
    aliases: tuple[str, ...] = ()
    systems: tuple[EmbedTemplateSystem, ...] = ("author", "footer", "description", "images")
    visible_embed: bool = True


_PUBLIC_TOP_LEVEL_EMBED_SERVICES: tuple[PublicEmbedService, ...] = (
    PublicEmbedService(key="audio", label="AUDIO", aliases=("audio_notes", "audio_notes_transcribe")),
    PublicEmbedService(key="aura", label="AURA"),
    PublicEmbedService(key="riassunto", label="RIASSUNTO"),
    PublicEmbedService(key="resoconto", label="RESOCONTO", aliases=("channel_summary",)),
    PublicEmbedService(key="attivita", label="ATTIVITÀ", aliases=("activity_dm", "daily_activity_report", "user_activity")),
    PublicEmbedService(key="barcello", label="BARCELLO"),
    PublicEmbedService(
        key="campagne",
        label="CAMPAGNE",
        aliases=(
            "campaigns",
            "campagne_notizie",
            "campagne_meteo",
            "campagne_oroscopo",
            "campagne_prompt",
            "campagne_timer",
        ),
    ),
    PublicEmbedService(key="qna", label="QNA"),
    PublicEmbedService(key="status", label="STATUS"),
    PublicEmbedService(key="triggers", label="TRIGGERS", aliases=("frasi",)),
)

_CANONICAL_BY_ALIAS: dict[str, str] = {}
_ALIASES_BY_CANONICAL: dict[str, tuple[str, ...]] = {}
_SERVICE_BY_KEY: dict[str, PublicEmbedService] = {}
for entry in _PUBLIC_TOP_LEVEL_EMBED_SERVICES:
    canonical = entry.key
    aliases = {canonical, *entry.aliases}
    normalized_aliases = tuple(sorted(alias.strip().lower() for alias in aliases if alias.strip()))
    _ALIASES_BY_CANONICAL[canonical] = normalized_aliases
    _SERVICE_BY_KEY[canonical] = entry
    for alias in normalized_aliases:
        _CANONICAL_BY_ALIAS[alias] = canonical


def list_public_embed_services(
    *,
    system: EmbedTemplateSystem | None = None,
    visible_embed_only: bool = True,
) -> list[PublicEmbedService]:
    services = list(_PUBLIC_TOP_LEVEL_EMBED_SERVICES)
    if visible_embed_only:
        services = [service for service in services if service.visible_embed]
    if system is not None:
        services = [service for service in services if system in service.systems]
    return services


def list_public_embed_service_keys(
    *,
    system: EmbedTemplateSystem | None = None,
    visible_embed_only: bool = True,
) -> list[str]:
    return [service.key for service in list_public_embed_services(system=system, visible_embed_only=visible_embed_only)]


def get_public_embed_service(public_service_key: str | None) -> PublicEmbedService | None:
    canonical = resolve_public_embed_service_key(public_service_key)
    if canonical is None:
        return None
    return _SERVICE_BY_KEY.get(canonical)


def is_public_embed_service_key(value: str | None, *, system: EmbedTemplateSystem | None = None) -> bool:
    return resolve_public_embed_service_key(value, system=system) is not None


def resolve_public_embed_service_key(value: str | None, *, system: EmbedTemplateSystem | None = None) -> str | None:
    normalized = (value or "").strip().lower()
    if not normalized:
        return None
    canonical = _CANONICAL_BY_ALIAS.get(normalized)
    if canonical is None:
        return None
    service = _SERVICE_BY_KEY.get(canonical)
    if service is None:
        return None
    if system is not None and system not in service.systems:
        return None
    if not service.visible_embed:
        return None
    return canonical


def list_embed_service_aliases(public_service_key: str) -> tuple[str, ...]:
    canonical = resolve_public_embed_service_key(public_service_key)
    if canonical is None:
        return ()
    return _ALIASES_BY_CANONICAL.get(canonical, ())
