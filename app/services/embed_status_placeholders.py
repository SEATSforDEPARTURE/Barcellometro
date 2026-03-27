from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EmbedTemplateSystem = Literal["description", "author", "footer"]


@dataclass(frozen=True, slots=True)
class EmbedStatusPlaceholder:
    name: str
    description: str
    systems: tuple[EmbedTemplateSystem, ...]


_PLACEHOLDER_REGISTRY: tuple[EmbedStatusPlaceholder, ...] = (
    EmbedStatusPlaceholder(
        name="service_name",
        description="chiave pubblica del servizio",
        systems=("author", "footer", "description"),
    ),
    EmbedStatusPlaceholder(
        name="service_label",
        description="label leggibile del servizio",
        systems=("author", "footer"),
    ),
    EmbedStatusPlaceholder(
        name="bot_version",
        description="versione configurata del bot",
        systems=("author", "footer"),
    ),
    EmbedStatusPlaceholder(
        name="user_name",
        description="nome visuale utente senza mention",
        systems=("description",),
    ),
    EmbedStatusPlaceholder(
        name="user_bold",
        description="nome utente già in grassetto",
        systems=("description",),
    ),
    EmbedStatusPlaceholder(
        name="ordinal_today",
        description="ordinale giornaliero in testo",
        systems=("description",),
    ),
    EmbedStatusPlaceholder(
        name="ordinal_today_bold",
        description="ordinale giornaliero in grassetto",
        systems=("description",),
    ),
    EmbedStatusPlaceholder(
        name="audio_intro",
        description="intro audio standard (solo audio)",
        systems=("description",),
    ),
    EmbedStatusPlaceholder(
        name="is_first_today",
        description="flag primo audio del giorno (solo audio)",
        systems=("description",),
    ),
    EmbedStatusPlaceholder(
        name="count_today",
        description="conteggio audio del giorno (solo audio)",
        systems=("description",),
    ),
)


def list_embed_status_placeholders() -> tuple[EmbedStatusPlaceholder, ...]:
    return _PLACEHOLDER_REGISTRY


def list_placeholders_for_system(system: EmbedTemplateSystem) -> list[EmbedStatusPlaceholder]:
    return [item for item in _PLACEHOLDER_REGISTRY if system in item.systems]


def placeholder_names_for_system(system: EmbedTemplateSystem) -> set[str]:
    return {item.name for item in list_placeholders_for_system(system)}


def format_placeholder_status_lines(system: EmbedTemplateSystem) -> list[tuple[str, str]]:
    placeholders = list_placeholders_for_system(system)
    return [(f"{{{item.name}}}", item.description) for item in placeholders]


def render_supported_placeholders(template: str, values: dict[str, str], *, system: EmbedTemplateSystem) -> str:
    rendered = template
    for key in sorted(placeholder_names_for_system(system), key=len, reverse=True):
        rendered = rendered.replace(f"{{{key}}}", values.get(key, "—"))
    return rendered
