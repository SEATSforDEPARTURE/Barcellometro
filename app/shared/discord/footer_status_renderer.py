from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import logging

import discord

from app.services.footer import FooterService, FooterStatusServiceEntry, FooterStatusSnapshot, ServiceFooterProfile, ServiceFooterVariant
from app.services.author import AuthorService, attach_author_meta
from app.services.footer import attach_footer_meta
from app.shared.discord.embed_limits import (
    DISCORD_MAX_EMBED_DESCRIPTION,
    DISCORD_MAX_FIELD_NAME,
    DISCORD_MAX_FIELD_VALUE,
    DISCORD_MAX_FIELDS,
    MAX_EMBED_CHARS,
    _estimate_embed_size,
    normalize_embeds_for_discord,
)
from app.shared.discord.embed_rendering import finalize_embeds_rendering
from app.shared.discord.embed_body import format_standard_field_name, format_standard_title

logger = logging.getLogger(__name__)

_CATEGORY_TITLES: dict[int, str] = {
    0: "STANDARD SERVICES",
    1: "EDITORIAL CAMPAIGNS",
    2: "PROMPT CAMPAIGNS",
    3: "TIMER CAMPAIGNS",
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
        lines.append(f"Diff: {mode} [{_compact_join(keys, limit=3)}]{contributor_part} → `{footer_preview}`")
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
        f"• Footer effettivo: `{_clip(effective_footer, _MAX_FOOTER_PREVIEW)}`",
        f"• Sorgente: **{source}** · Varianti: **{len(entry.persisted_variants)}** · Profilo: **{profile_kind}**",
        f"• Modalità: {variant_summary}",
    ]

    contributors = _contributors_summary(entry)
    if contributors is not None:
        label = "Profilo runtime" if profile and profile.contributors and not entry.persisted_variants else "Contributor"
        lines.append(f"• {label}: {contributors}")

    for delta_line in _variant_difference_lines(entry, effective_footer):
        lines.append(f"• {delta_line}")

    if meta_parts:
        lines.append(f"• Meta: {_clip(' · '.join(meta_parts), 220)}")

    value = "\n".join(lines)
    return FooterStatusField(
        name=_clip(format_standard_field_name(_human_service_name(entry.service_name), emoji="🧾"), DISCORD_MAX_FIELD_NAME),
        value=_clip(value, DISCORD_MAX_FIELD_VALUE),
    )


def _overview_description(snapshot: FooterStatusSnapshot) -> str:
    _ = snapshot
    return _clip("Stato e diagnostica del footer embed.", DISCORD_MAX_EMBED_DESCRIPTION)


def _overview_fields(snapshot: FooterStatusSnapshot) -> list[FooterStatusField]:
    service_override_count = sum(1 for entry in snapshot.services if _has_service_override(entry))
    source_counts = Counter(effective_config_source(entry, snapshot) for entry in snapshot.services)

    status_lines = [
        f"• Footer: **{'ON' if snapshot.enabled else 'OFF'}**",
        f"• Template: **{_clip(snapshot.global_phrase, 120)}**",
        f"• Thumbnail: **{'sì' if snapshot.global_thumbnail else 'no'}**",
    ]

    service_lines = [
        f"• Totali: **{len(snapshot.services)}**",
        f"• Override: **{service_override_count}**",
        f"• Global: **{source_counts.get('global', 0)}**",
        f"• Runtime: **{source_counts.get('runtime', 0)}**",
        f"• Fallback: **{source_counts.get('fallback', 0)}**",
    ]

    group_lines: list[str] = []
    for category, title in _CATEGORY_TITLES.items():
        entries = [entry for entry in snapshot.services if entry.category == category]
        if not entries:
            continue
        variant_total = sum(len(entry.persisted_variants) for entry in entries)
        group_lines.append(f"• {title}: **{len(entries)}** servizi ({variant_total} varianti)")

    config_lines = [
        f"• Template globale: **{'attivo' if _has_global_template(snapshot) else 'assente'}**",
        f"• Sorgenti note: **{sum(1 for entry in snapshot.services if entry.known_sources)}**",
        f"• Runtime persistito: **{sum(1 for entry in snapshot.services if _has_runtime_data(entry))}**",
    ]

    return [
        FooterStatusField(name=format_standard_field_name("Stato", emoji="ℹ️"), value="\n".join(status_lines)),
        FooterStatusField(name=format_standard_field_name("Servizi", emoji="📊"), value="\n".join(service_lines)),
        FooterStatusField(name=format_standard_field_name("Famiglie", emoji="📂"), value="\n".join(group_lines) or "• Nessuna famiglia disponibile."),
        FooterStatusField(name=format_standard_field_name("Configurazione", emoji="⚙️"), value="\n".join(config_lines)),
    ]


def _build_group_description(title: str, entries: list[FooterStatusServiceEntry], snapshot: FooterStatusSnapshot) -> str:
    override_count = sum(1 for entry in entries if _has_service_override(entry))
    runtime_count = sum(1 for entry in entries if effective_config_source(entry, snapshot) == "runtime")
    return (
        f"Dettaglio categoria {title.lower()}: servizi={len(entries)}, "
        f"override={override_count}, runtime={runtime_count}."
    )


def _render_page_description(page: FooterStatusPage, *, page_index: int, total_pages: int) -> str:
    _ = (page_index, total_pages)
    base = page.description.strip() if page.description else ""
    if not base or base == "—":
        base = "Stato footer embed."
    return _clip(f"*{base}*", DISCORD_MAX_EMBED_DESCRIPTION)


def _build_embed_for_page(page: FooterStatusPage, *, page_index: int, total_pages: int) -> discord.Embed:
    embed = discord.Embed(
        title=format_standard_title(page.title, emoji="📦"),
        description=_render_page_description(page, page_index=page_index, total_pages=total_pages),
        color=discord.Color.blurple(),
    )
    info_lines = [
        f"• Pagina: **{page_index}/{total_pages}**",
        "• Navigazione: **INIZIO / INDIETRO / AVANTI**",
    ]
    embed.add_field(
        name=format_standard_field_name("INFO", emoji="ℹ️"),
        value=_clip("\n".join(info_lines), DISCORD_MAX_FIELD_VALUE),
        inline=False,
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
        if current_fields and (len(candidate_fields) >= DISCORD_MAX_FIELDS or _estimate_embed_size(probe) > _PAGE_EMBED_MAX):
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
            title="FOOTER STATUS",
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
        pages.extend(_paginate_group(f"FOOTER STATUS · {title}", description, fields))

    uncategorized_entries = [entry for entry in snapshot.services if entry.category not in _CATEGORY_TITLES]
    if uncategorized_entries:
        fields = [build_service_status_field(entry, snapshot) for entry in uncategorized_entries]
        pages.extend(_paginate_group("FOOTER STATUS · OTHER SERVICES", "• Servizi aggiuntivi rilevati nel renderer.", fields))

    return pages


async def build_footer_status_embeds(
    snapshot: FooterStatusSnapshot,
    *,
    footer_service: FooterService | None = None,
    author_service: AuthorService | None = None,
) -> list[discord.Embed]:
    pages = build_footer_status_pages(snapshot)
    total_pages = len(pages)
    embeds = [_build_embed_for_page(page, page_index=index, total_pages=total_pages) for index, page in enumerate(pages, start=1)]
    for embed in embeds:
        attach_footer_meta(embed, service_name="status")
        attach_author_meta(embed, service_name="status", canonical_top_level_command="embed")
    await finalize_embeds_rendering(
        embeds,
        footer_service=footer_service,
        author_service=author_service,
        default_service_name="status",
    )
    normalized = normalize_embeds_for_discord(embeds, max_chars=MAX_EMBED_CHARS)
    if len(normalized) != len(embeds):
        logger.warning("footer_status_renderer_normalized_embeds before=%s after=%s", len(embeds), len(normalized))
    if normalized is not embeds:
        for embed in normalized:
            attach_footer_meta(embed, service_name="status")
            attach_author_meta(embed, service_name="status", canonical_top_level_command="embed")
        await finalize_embeds_rendering(
            normalized,
            footer_service=footer_service,
            author_service=author_service,
            default_service_name="status",
        )
    return normalized
