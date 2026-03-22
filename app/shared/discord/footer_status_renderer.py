from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import logging

import discord

from app.services.footer import FooterService, FooterStatusServiceEntry, FooterStatusSnapshot, ServiceFooterProfile, ServiceFooterVariant
from app.shared.discord.embed_limits import (
    DISCORD_MAX_EMBED_DESCRIPTION,
    DISCORD_MAX_FIELD_NAME,
    DISCORD_MAX_FIELD_VALUE,
    DISCORD_MAX_FIELDS,
    MAX_EMBED_CHARS,
    _estimate_embed_size,
    normalize_embeds_for_discord,
)
from app.shared.discord.footer_pipeline import finalize_embeds

logger = logging.getLogger(__name__)

_CATEGORY_TITLES: dict[int, str] = {
    0: "Standard services",
    1: "Editorial campaigns",
    2: "Prompt campaigns",
    3: "Timer campaigns",
}
_PAGE_EMBED_MAX = 5000
_MAX_FOOTER_PREVIEW = 220
_MAX_KEYS_PREVIEW = 5


@dataclass(slots=True)
class FooterStatusField:
    name: str
    value: str


@dataclass(slots=True)
class FooterStatusPage:
    title: str
    description: str
    fields: list[FooterStatusField]


def _human_service_name(service_name: str) -> str:
    labels = {
        "campagne_notizie": "Campagne notizie",
        "campagne_meteo": "Campagne meteo",
        "campagne_oroscopo": "Campagne oroscopo",
        "campagne_prompt": "Campagne prompt",
        "campagne_timer": "Campagne timer",
    }
    return labels.get(service_name, service_name.replace("_", " ").title())


def _clip(text: str | None, limit: int) -> str:
    value = str(text or "").strip()
    if not value:
        return "—"
    if len(value) <= limit:
        return value
    return f"{value[: max(0, limit - 1)].rstrip()}…"


def _compact_join(items: list[str], *, limit: int = _MAX_KEYS_PREVIEW) -> str:
    cleaned = [item.strip() for item in items if item and item.strip()]
    if not cleaned:
        return "—"
    if len(cleaned) <= limit:
        return ", ".join(cleaned)
    hidden = len(cleaned) - limit
    return f"{', '.join(cleaned[:limit])} +{hidden}"


def _resolved_profile(entry: FooterStatusServiceEntry) -> tuple[str, ServiceFooterProfile | None]:
    if entry.persisted_profile is not None:
        return "runtime", entry.persisted_profile
    if entry.inferred_profile is not None:
        return "runtime", entry.inferred_profile
    return "fallback", None


def _has_service_override(entry: FooterStatusServiceEntry) -> bool:
    return entry.service_phrase_override or entry.service_thumbnail_override


def _has_global_template(snapshot: FooterStatusSnapshot) -> bool:
    return bool(snapshot.global_phrase or snapshot.global_thumbnail)


def _has_runtime_data(entry: FooterStatusServiceEntry) -> bool:
    return bool(entry.persisted_variants or entry.persisted_profile or entry.inferred_profile)


def effective_config_source(entry: FooterStatusServiceEntry, snapshot: FooterStatusSnapshot) -> str:
    if _has_service_override(entry):
        return "service"
    if _has_global_template(snapshot):
        return "global"
    if _has_runtime_data(entry):
        return "runtime"
    return "fallback"


def _effective_footer(entry: FooterStatusServiceEntry) -> str:
    candidate_texts = [
        entry.rendered_footer,
        entry.persisted_profile.last_rendered_footer if entry.persisted_profile else None,
        entry.inferred_profile.last_rendered_footer if entry.inferred_profile else None,
    ]
    for value in candidate_texts:
        if value and value.strip():
            return value.strip()

    rendered_variants = [variant.last_rendered_footer.strip() for variant in entry.persisted_variants if variant.last_rendered_footer and variant.last_rendered_footer.strip()]
    if rendered_variants:
        return Counter(rendered_variants).most_common(1)[0][0]
    return "Footer non ancora renderizzato"


def _latest_updated(entry: FooterStatusServiceEntry) -> str | None:
    timestamps = [
        timestamp
        for timestamp in [
            entry.persisted_profile.updated_at if entry.persisted_profile else None,
            entry.inferred_profile.updated_at if entry.inferred_profile else None,
            *[variant.updated_at for variant in entry.persisted_variants],
        ]
        if timestamp
    ]
    return max(timestamps) if timestamps else None


def _origin_summary(entry: FooterStatusServiceEntry) -> str | None:
    origins: set[str] = set()
    if entry.persisted_profile and entry.persisted_profile.origins:
        origins.update(entry.persisted_profile.origins)
    if entry.inferred_profile and entry.inferred_profile.origins:
        origins.update(entry.inferred_profile.origins)
    for variant in entry.persisted_variants:
        if variant.origins:
            origins.update(variant.origins)
    return ", ".join(sorted(origins)) if origins else None


def _contributors_summary(entry: FooterStatusServiceEntry) -> str | None:
    profile = entry.persisted_profile or entry.inferred_profile
    if profile and profile.contributors:
        return _compact_join(profile.contributors)

    contributors: list[str] = []
    seen: set[str] = set()
    for variant in entry.persisted_variants:
        for contributor in variant.contributors:
            clean = contributor.strip()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            contributors.append(clean)
    return _compact_join(contributors) if contributors else None


def _variant_mode_groups(variants: list[ServiceFooterVariant]) -> str:
    if not variants:
        return "nessuna persistita"

    grouped: dict[str, list[str]] = {"local": [], "remote": []}
    for variant in variants:
        key = variant.variant_key.strip() or "default"
        mode = "local" if variant.used_local_processing else "remote"
        grouped[mode].append(key)

    parts: list[str] = []
    for mode in ("local", "remote"):
        keys = grouped[mode]
        if not keys:
            continue
        parts.append(f"{mode} ({len(keys)}): {_compact_join(keys)}")
    return " · ".join(parts) if parts else "nessuna persistita"


def _variant_difference_lines(entry: FooterStatusServiceEntry, primary_footer: str) -> list[str]:
    groups: dict[tuple[str, str, str], list[str]] = {}
    for variant in entry.persisted_variants:
        variant_footer = (variant.last_rendered_footer or "").strip()
        if not variant_footer or variant_footer == primary_footer:
            continue
        mode = "local" if variant.used_local_processing else "remote"
        contributors = _compact_join(variant.contributors)
        key = (mode, contributors, _clip(variant_footer, 90))
        groups.setdefault(key, []).append(variant.variant_key.strip() or "default")

    lines: list[str] = []
    for (mode, contributors, footer_preview), keys in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1], item[0][2])):
        contributor_part = f" · {contributors}" if contributors != "—" else ""
        lines.append(f"Δ {mode} [{_compact_join(keys, limit=3)}]{contributor_part} → `{footer_preview}`")
        if len(lines) >= 2:
            break
    return lines


def _override_summary(entry: FooterStatusServiceEntry) -> str | None:
    override_bits: list[str] = []
    if entry.service_phrase_override:
        override_bits.append("frase")
    if entry.service_thumbnail_override:
        override_bits.append("thumbnail")
    if not override_bits:
        return None
    return ", ".join(override_bits)


def build_service_status_field(entry: FooterStatusServiceEntry, snapshot: FooterStatusSnapshot) -> FooterStatusField:
    effective_footer = _effective_footer(entry)
    source = effective_config_source(entry, snapshot)
    variant_summary = _variant_mode_groups(entry.persisted_variants)
    profile_kind, profile = _resolved_profile(entry)
    meta_parts: list[str] = []

    override_summary = _override_summary(entry)
    if override_summary is not None:
        meta_parts.append(f"override {override_summary}")
    if entry.known_sources:
        meta_parts.append(f"scoperta {_compact_join(entry.known_sources, limit=3)}")
    origin_summary = _origin_summary(entry)
    if origin_summary is not None:
        meta_parts.append(f"origini {origin_summary}")
    updated = _latest_updated(entry)
    if updated is not None:
        meta_parts.append(f"agg. {updated}")

    lines = [
        f"**Footer:** `{_clip(effective_footer, _MAX_FOOTER_PREVIEW)}`",
        f"**Sorgente:** **{source}** · varianti **{len(entry.persisted_variants)}** · profilo **{profile_kind}**",
        f"**Varianti:** {variant_summary}",
    ]

    contributors = _contributors_summary(entry)
    if contributors is not None:
        label = "Profilo runtime" if profile and profile.contributors and not entry.persisted_variants else "Contributor"
        lines.append(f"**{label}:** {contributors}")

    lines.extend(_variant_difference_lines(entry, effective_footer))

    if meta_parts:
        lines.append(f"**Meta:** {_clip(' · '.join(meta_parts), 220)}")

    value = "\n".join(lines)
    return FooterStatusField(
        name=_clip(_human_service_name(entry.service_name), DISCORD_MAX_FIELD_NAME),
        value=_clip(value, DISCORD_MAX_FIELD_VALUE),
    )


def _overview_description(snapshot: FooterStatusSnapshot) -> str:
    service_override_count = sum(1 for entry in snapshot.services if _has_service_override(entry))
    source_counts = Counter(effective_config_source(entry, snapshot) for entry in snapshot.services)

    lines = [
        "Pannello amministrativo compatto del footer embed.",
        "",
        f"• Stato footer: **{'ON' if snapshot.enabled else 'OFF'}**",
        f"• Template globale effettivo: **{_clip(snapshot.global_phrase, 140)}**",
        f"• Thumbnail globale: **{'Sì' if snapshot.global_thumbnail else 'No'}**",
        f"• Servizi noti: **{len(snapshot.services)}**",
        f"• Override dedicati: **{service_override_count}**",
        f"• Uso globale: **{source_counts.get('global', 0)}**",
        f"• Uso runtime: **{source_counts.get('runtime', 0)}**",
        f"• Fallback puro: **{source_counts.get('fallback', 0)}**",
    ]
    return _clip("\n".join(lines), DISCORD_MAX_EMBED_DESCRIPTION)


def _overview_fields(snapshot: FooterStatusSnapshot) -> list[FooterStatusField]:
    service_override_count = sum(1 for entry in snapshot.services if _has_service_override(entry))
    group_breakdown = []
    for category, title in _CATEGORY_TITLES.items():
        entries = [entry for entry in snapshot.services if entry.category == category]
        if not entries:
            continue
        override_count = sum(1 for entry in entries if _has_service_override(entry))
        persisted_count = sum(1 for entry in entries if entry.persisted_variants)
        group_breakdown.append(f"• {title}: **{len(entries)}** servizi · override **{override_count}** · varianti persistite **{persisted_count}**")

    source_counts = Counter(effective_config_source(entry, snapshot) for entry in snapshot.services)
    return [
        FooterStatusField(
            name="Breakdown gruppi",
            value="\n".join(group_breakdown) or "Nessun gruppo disponibile.",
        ),
        FooterStatusField(
            name="Distribuzione configurazione",
            value="\n".join(
                [
                    f"• Service override: **{service_override_count}**",
                    f"• Global template: **{source_counts.get('global', 0)}**",
                    f"• Runtime profile: **{source_counts.get('runtime', 0)}**",
                    f"• Fallback profile: **{source_counts.get('fallback', 0)}**",
                ]
            ),
        ),
        FooterStatusField(
            name="Navigazione",
            value="Usa i bottoni **INIZIO**, **INDIETRO** e **AVANTI** per passare dalla panoramica ai gruppi di servizi senza generare nuovi messaggi.",
        ),
    ]


def _build_group_description(title: str, entries: list[FooterStatusServiceEntry], snapshot: FooterStatusSnapshot) -> str:
    override_count = sum(1 for entry in entries if _has_service_override(entry))
    runtime_count = sum(1 for entry in entries if effective_config_source(entry, snapshot) == "runtime")
    return "\n".join(
        [
            f"Vista compatta del gruppo **{title}**.",
            f"Servizi nel gruppo: **{len(entries)}** · override dedicati **{override_count}** · uso runtime **{runtime_count}**",
        ]
    )


def _build_embed_for_page(page: FooterStatusPage, *, page_index: int, total_pages: int) -> discord.Embed:
    embed = discord.Embed(
        title=_clip(f"Footer status · {page.title} ({page_index}/{total_pages})", 256),
        description=_clip(page.description, DISCORD_MAX_EMBED_DESCRIPTION),
        color=discord.Color.blurple(),
    )
    for field in page.fields:
        embed.add_field(
            name=_clip(field.name, DISCORD_MAX_FIELD_NAME),
            value=_clip(field.value, DISCORD_MAX_FIELD_VALUE),
            inline=False,
        )
    return embed


def _paginate_group(title: str, description: str, fields: list[FooterStatusField]) -> list[FooterStatusPage]:
    if not fields:
        return [FooterStatusPage(title=title, description=description, fields=[])]

    pages: list[FooterStatusPage] = []
    current_fields: list[FooterStatusField] = []
    current_index = 0

    for field in fields:
        candidate_fields = [*current_fields, field]
        probe = _build_embed_for_page(
            FooterStatusPage(title=title, description=description, fields=candidate_fields),
            page_index=current_index + 1,
            total_pages=current_index + 1,
        )
        if current_fields and (len(candidate_fields) > DISCORD_MAX_FIELDS or _estimate_embed_size(probe) > _PAGE_EMBED_MAX):
            pages.append(FooterStatusPage(title=title, description=description, fields=current_fields))
            current_index += 1
            current_fields = [field]
            continue
        current_fields = candidate_fields

    if current_fields:
        pages.append(FooterStatusPage(title=title, description=description, fields=current_fields))
    return pages


def build_footer_status_pages(snapshot: FooterStatusSnapshot) -> list[FooterStatusPage]:
    pages = [
        FooterStatusPage(
            title="Overview",
            description=_overview_description(snapshot),
            fields=_overview_fields(snapshot),
        )
    ]

    for category, title in _CATEGORY_TITLES.items():
        entries = [entry for entry in snapshot.services if entry.category == category]
        if not entries:
            continue
        fields = [build_service_status_field(entry, snapshot) for entry in entries]
        description = _build_group_description(title, entries, snapshot)
        pages.extend(_paginate_group(title, description, fields))

    uncategorized_entries = [entry for entry in snapshot.services if entry.category not in _CATEGORY_TITLES]
    if uncategorized_entries:
        fields = [build_service_status_field(entry, snapshot) for entry in uncategorized_entries]
        pages.extend(_paginate_group("Other services", "Servizi aggiuntivi rilevati nel renderer.", fields))

    return pages


async def build_footer_status_embeds(
    snapshot: FooterStatusSnapshot,
    *,
    footer_service: FooterService | None = None,
) -> list[discord.Embed]:
    pages = build_footer_status_pages(snapshot)
    total_pages = len(pages)
    embeds = [_build_embed_for_page(page, page_index=index, total_pages=total_pages) for index, page in enumerate(pages, start=1)]
    await finalize_embeds(embeds, footer_service, default_service_name="status")
    normalized = normalize_embeds_for_discord(embeds, max_chars=MAX_EMBED_CHARS)
    if len(normalized) != len(embeds):
        logger.warning("footer_status_renderer_normalized_embeds before=%s after=%s", len(embeds), len(normalized))
    return normalized
