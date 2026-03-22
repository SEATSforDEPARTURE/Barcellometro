from __future__ import annotations

from dataclasses import dataclass
import logging

import discord

from app.services.footer import FooterStatusServiceEntry, FooterStatusSnapshot, ServiceFooterProfile, ServiceFooterVariant
from app.shared.discord.command_embeds import CommandEmbedSection, build_command_embeds, format_bullet
from app.shared.discord.embed_limits import MAX_EMBED_CHARS, normalize_embeds_for_discord
from app.shared.discord.embed_status_helpers import _chunk_status_blocks

logger = logging.getLogger(__name__)
_DEFAULT_PAGE_BODY_MAX = 3200

_CATEGORY_TITLES: dict[int, str] = {
    0: "Standard services",
    1: "Editorial campaigns",
    2: "Prompt campaigns",
    3: "Timer campaigns",
}


@dataclass(slots=True)
class FooterStatusPage:
    title: str
    lines: list[tuple[str, object]]
    body: str | None = None


def _human_service_name(service_name: str) -> str:
    labels = {
        "campagne_notizie": "campagne_notizie",
        "campagne_meteo": "campagne_meteo",
        "campagne_oroscopo": "campagne_oroscopo",
        "campagne_prompt": "campagne_prompt",
        "campagne_timer": "campagne_timer",
    }
    return labels.get(service_name, service_name.replace("_", " ").title())


def _format_contributors(contributors: list[str]) -> str:
    return " + ".join(contributors) if contributors else "(none)"


def _format_phrase(entry: FooterStatusServiceEntry) -> str:
    value = entry.phrase or "(none)"
    return f"{value} [{entry.phrase_origin}]"


def _format_variant_block(variant: ServiceFooterVariant) -> str:
    mode = "local" if variant.used_local_processing else "remote"
    footer_text = variant.last_rendered_footer or "(footer not rendered yet)"
    origins = ",".join(sorted(variant.origins or [])) or "(n/a)"
    updated = variant.updated_at or "(n/a)"
    return (
        f"variant: {mode} | {_format_contributors(variant.contributors)}\n"
        f"footer: {footer_text}\n"
        f"origin: {origins}\n"
        f"updated: {updated}\n"
        f"key: {variant.variant_key}"
    )


def _resolved_profile(entry: FooterStatusServiceEntry) -> tuple[str, ServiceFooterProfile | None]:
    if entry.persisted_profile is not None:
        return "persisted", entry.persisted_profile
    if entry.inferred_profile is not None:
        return "inferred", entry.inferred_profile
    return "fallback", None


def _format_non_persisted_block(entry: FooterStatusServiceEntry) -> str:
    profile_kind, profile = _resolved_profile(entry)
    contributors = _format_contributors(profile.contributors if profile else [])
    mode = "local" if (profile.used_local_processing if profile else True) else "remote"
    profile_origins = sorted(profile.origins or []) if profile else []
    combined_origins = sorted(set(entry.known_sources) | set(profile_origins))
    updated = profile.updated_at if profile else None
    return (
        f"**{entry.service_name}**\n"
        f"label: {_human_service_name(entry.service_name)}\n"
        f"technical alias: `{entry.service_name}`\n"
        f"sources: {','.join(entry.known_sources) if entry.known_sources else '(n/a)'}\n"
        f"profile: {profile_kind}\n"
        f"mode: {mode}\n"
        f"contributors: {contributors}\n"
        f"footer: {entry.rendered_footer or '(footer not rendered yet)'}\n"
        f"phrase: {_format_phrase(entry)}\n"
        f"origin: {','.join(combined_origins) if combined_origins else '(n/a)'}\n"
        f"updated: {updated or '(n/a)'}"
    )


def _format_persisted_service_block(entry: FooterStatusServiceEntry) -> str:
    header = (
        f"**{entry.service_name}**\n"
        f"label: {_human_service_name(entry.service_name)}\n"
        f"technical alias: `{entry.service_name}`\n"
        f"sources: {','.join(entry.known_sources) if entry.known_sources else '(n/a)'}\n"
        f"phrase: {_format_phrase(entry)}\n"
        f"persisted variants: {len(entry.persisted_variants)}"
    )
    return f"{header}\n\n" + "\n\n".join(_format_variant_block(variant) for variant in entry.persisted_variants)


def build_footer_status_pages(snapshot: FooterStatusSnapshot, *, max_len: int = _DEFAULT_PAGE_BODY_MAX) -> list[FooterStatusPage]:
    persisted_entries = [entry for entry in snapshot.services if entry.persisted_variants]
    inferred_entries = [entry for entry in snapshot.services if not entry.persisted_variants]

    category_counts = {
        title: len([entry for entry in persisted_entries if entry.category == category])
        for category, title in _CATEGORY_TITLES.items()
    }
    overview_sections = [
        f"persisted services: {len(persisted_entries)}",
        f"services without persisted variants: {len(inferred_entries)}",
        *[f"{title}: {count}" for title, count in category_counts.items() if count],
    ]
    pages = [
        FooterStatusPage(
            title="Overview",
            lines=[
                ("footer_rendering", "on" if snapshot.enabled else "off"),
                ("known_services", len(snapshot.services)),
                ("services_with_persisted_variants", len(persisted_entries)),
                ("services_without_persisted_variants", len(inferred_entries)),
                ("global_phrase", snapshot.global_phrase or "(none)"),
            ],
            body="\n".join(overview_sections),
        )
    ]

    for category, title in _CATEGORY_TITLES.items():
        category_blocks = [_format_persisted_service_block(entry) for entry in persisted_entries if entry.category == category]
        chunks = _chunk_status_blocks(category_blocks, max_len=max_len)
        if len(chunks) > 1:
            logger.info("footer_status_renderer_split_category title=%s services=%s pages=%s", title, len(category_blocks), len(chunks))
        for chunk in chunks:
            pages.append(
                FooterStatusPage(
                    title=title,
                    lines=[("services_in_group", len([entry for entry in persisted_entries if entry.category == category]))],
                    body=chunk,
                )
            )

    if inferred_entries:
        inferred_blocks = [_format_non_persisted_block(entry) for entry in inferred_entries]
        chunks = _chunk_status_blocks(inferred_blocks, max_len=max_len)
        if len(chunks) > 1:
            logger.info("footer_status_renderer_split_inferred services=%s pages=%s", len(inferred_entries), len(chunks))
        for chunk in chunks:
            pages.append(
                FooterStatusPage(
                    title="Services without persisted variants",
                    lines=[("services_in_group", len(inferred_entries))],
                    body=chunk,
                )
            )

    return pages


def _footer_status_line_formatter(label: str, value: object) -> str:
    if label == "_raw":
        return str(value)
    return format_bullet(label, value, kind="info")


async def build_footer_status_embeds(snapshot: FooterStatusSnapshot) -> list[discord.Embed]:
    pages = build_footer_status_pages(snapshot)
    total_pages = len(pages)
    embeds: list[discord.Embed] = []
    for index, page in enumerate(pages, start=1):
        sections = [CommandEmbedSection(title=page.title, lines=[("_raw", page.body)])] if page.body else None
        embeds.extend(
            await build_command_embeds(
                top_level="embed",
                subcommand_path="footer status",
                lines=[("page", f"{index}/{total_pages}"), *page.lines],
                sections=sections,
                line_formatter=_footer_status_line_formatter,
            )
        )
    normalized = normalize_embeds_for_discord(embeds, max_chars=MAX_EMBED_CHARS)
    if len(normalized) != len(embeds):
        logger.warning(
            "footer_status_renderer_normalized_embeds before=%s after=%s",
            len(embeds),
            len(normalized),
        )
    return normalized
