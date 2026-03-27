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
    PublicEmbedService(
        key="audio",
        label="AUDIO",
        aliases=("audio_notes", "audio_notes_transcribe", "audio_transcribe"),
    ),
    PublicEmbedService(
        key="triggers",
        label="TRIGGERS",
        aliases=("frasi", "phrases", "barcello", "barcello_trigger", "trigger_phrases", "trigger_barcello"),
    ),
    PublicEmbedService(
        key="greetings",
        label="GREETINGS",
        aliases=("greeting", "member_flow_notifications", "welcome", "goodbye"),
    ),
    PublicEmbedService(
        key="channelsummary",
        label="CHANNELSUMMARY",
        aliases=("channel_summary", "resoconto", "daily_resoconto"),
    ),
    PublicEmbedService(
        key="serversummary",
        label="SERVERSUMMARY",
        aliases=("server_summary", "serversummary_report", "server_report"),
    ),
    PublicEmbedService(
        key="dmchannelsummary",
        label="DMCHANNELSUMMARY",
        aliases=("dm_channel_summary", "riassunto", "channel_highlights", "detail_embeds"),
    ),
    PublicEmbedService(
        key="dmserversummary",
        label="DMSERVERSUMMARY",
        aliases=("dm_server_summary", "dmserversummary_report", "attivita", "activity_dm", "daily_activity_report", "user_activity", "aura"),
    ),
    PublicEmbedService(
        key="campaigns",
        label="CAMPAIGNS",
        aliases=(
            "campagne",
            "campagne_prompt",
            "campaign_prompt",
            "campagne_notizie",
            "campagne_meteo",
            "campagne_oroscopo",
            "campagne_timer",
            "message_campaigns",
        ),
    ),
    PublicEmbedService(
        key="qna",
        label="QNA",
        aliases=("ask", "domanda", "question_answer"),
    ),
    PublicEmbedService(
        key="inactivity",
        label="INACTIVITY",
        aliases=("inactive", "inattivi"),
    ),
    PublicEmbedService(
        key="embed",
        label="EMBED",
        aliases=("footer", "author", "description_template", "images_template"),
    ),
    PublicEmbedService(
        key="commandguard",
        label="COMMANDGUARD",
        aliases=("command_guard", "guards"),
    ),
    PublicEmbedService(
        key="database",
        label="DATABASE",
        aliases=("db", "retention", "backfill"),
    ),
    PublicEmbedService(
        key="status",
        label="STATUS",
        aliases=("mood", "presence"),
    ),
    PublicEmbedService(
        key="ai",
        label="AI",
        aliases=("model", "fallback_model", "ai_model"),
    ),
)



def _normalize_service_alias(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if not normalized:
        return ""
    return normalized.replace(" ", "_")


_CANONICAL_BY_ALIAS: dict[str, str] = {}
_ALIASES_BY_CANONICAL: dict[str, tuple[str, ...]] = {}
_SERVICE_BY_KEY: dict[str, PublicEmbedService] = {}
for entry in _PUBLIC_TOP_LEVEL_EMBED_SERVICES:
    canonical = entry.key
    aliases = {canonical, *entry.aliases}
    normalized_aliases = tuple(sorted({_normalize_service_alias(alias) for alias in aliases if _normalize_service_alias(alias)}))
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
    normalized = _normalize_service_alias(value)
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
