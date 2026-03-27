from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PublicEmbedService:
    key: str
    aliases: tuple[str, ...] = ()


_PUBLIC_EMBED_SERVICES: tuple[PublicEmbedService, ...] = (
    PublicEmbedService(key="audio", aliases=("audio_notes", "audio_notes_transcribe")),
    PublicEmbedService(key="aura"),
    PublicEmbedService(key="riassunto"),
    PublicEmbedService(key="resoconto", aliases=("channel_summary",)),
    PublicEmbedService(key="attivita", aliases=("activity_dm", "daily_activity_report", "user_activity")),
    PublicEmbedService(key="barcello"),
    PublicEmbedService(
        key="campagne",
        aliases=(
            "campaigns",
            "campagne_notizie",
            "campagne_meteo",
            "campagne_oroscopo",
            "campagne_prompt",
            "campagne_timer",
        ),
    ),
    PublicEmbedService(key="qna"),
    PublicEmbedService(key="status"),
)

_CANONICAL_BY_ALIAS: dict[str, str] = {}
_ALIASES_BY_CANONICAL: dict[str, tuple[str, ...]] = {}
for entry in _PUBLIC_EMBED_SERVICES:
    canonical = entry.key
    aliases = {canonical, *entry.aliases}
    normalized_aliases = tuple(sorted(alias.strip().lower() for alias in aliases if alias.strip()))
    _ALIASES_BY_CANONICAL[canonical] = normalized_aliases
    for alias in normalized_aliases:
        _CANONICAL_BY_ALIAS[alias] = canonical


def list_public_embed_service_keys() -> list[str]:
    return [entry.key for entry in _PUBLIC_EMBED_SERVICES]


def is_public_embed_service_key(value: str | None) -> bool:
    return resolve_public_embed_service_key(value) is not None


def resolve_public_embed_service_key(value: str | None) -> str | None:
    normalized = (value or "").strip().lower()
    if not normalized:
        return None
    return _CANONICAL_BY_ALIAS.get(normalized)


def list_embed_service_aliases(public_service_key: str) -> tuple[str, ...]:
    canonical = resolve_public_embed_service_key(public_service_key)
    if canonical is None:
        return ()
    return _ALIASES_BY_CANONICAL.get(canonical, ())
