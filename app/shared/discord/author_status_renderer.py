from __future__ import annotations

from dataclasses import dataclass

import discord

from app.services.author import (
    AuthorService,
    AuthorStatusServiceEntry,
    AuthorStatusSnapshot,
    attach_author_meta,
    human_author_service_name,
)
from app.services.footer import attach_footer_meta
from app.shared.discord.author_pipeline import apply_author_metadata_to_embeds
from app.shared.discord.embed_limits import MAX_EMBED_CHARS, normalize_embeds_for_discord
from app.shared.discord.footer_pipeline import finalize_embeds as finalize_footer_embeds

_CATEGORY_TITLES: dict[int, str] = {
    0: "STANDARD SERVICES",
    1: "EDITORIAL CAMPAIGNS",
    2: "PROMPT CAMPAIGNS",
    3: "TIMER CAMPAIGNS",
}


@dataclass(slots=True)
class AuthorStatusField:
    name: str
    value: str


@dataclass(slots=True)
class AuthorStatusPage:
    title: str
    description: str
    fields: list[AuthorStatusField]



def _clip(text: str | None, limit: int = 220) -> str:
    value = str(text or "").strip()
    if not value:
        return "—"
    if len(value) <= limit:
        return value
    return f"{value[: max(0, limit - 1)].rstrip()}…"



def build_service_status_field(entry: AuthorStatusServiceEntry) -> AuthorStatusField:
    source = "service" if entry.service_phrase_override or entry.service_thumbnail_override else ("global" if entry.phrase_origin == "global" or entry.rendered_thumbnail else "fallback")
    last_runtime = entry.persisted_profile.last_rendered_author if entry.persisted_profile else None
    lines = [
        f"• Author effettivo: `{_clip(entry.rendered_author, 120)}`",
        f"• Sorgente: `{source}` · frase `{entry.phrase_origin}`",
        f"• Thumbnail: `{_clip(entry.rendered_thumbnail, 100)}`",
        f"• URL: `{_clip(entry.rendered_url, 100)}`",
        f"• Override: `phrase={entry.service_phrase_override}` · `thumbnail={entry.service_thumbnail_override}` · `url={entry.service_url_override}`",
        f"• Runtime ultimo render: `{_clip(last_runtime, 120)}`",
        f"• Origini note: `{', '.join(entry.known_sources) if entry.known_sources else '—'}`",
    ]
    return AuthorStatusField(name=human_author_service_name(entry.service_name).upper(), value="\n".join(lines))



def build_author_status_pages(snapshot: AuthorStatusSnapshot) -> list[AuthorStatusPage]:
    overview_lines = [
        "• Vista amministrativa della sezione author embed.",
        f"• Stato: `{'on' if snapshot.enabled else 'off'}`",
        f"• Versione author: `{_clip(snapshot.version, 80)}`",
        f"• Frase globale: `{_clip(snapshot.global_phrase, 120)}`",
        f"• Thumbnail globale: `{_clip(snapshot.global_thumbnail, 100)}`",
        f"• URL globale: `{_clip(snapshot.global_url, 100)}`",
        "• Regola fallback: `servizio <NOME CANONICO INGLESE>`; le pagine multi-embed aggiungono `· (Pag. X/Y)`.",
    ]
    pages = [AuthorStatusPage(title="📦 EMBED", description="\n".join(overview_lines), fields=[])]
    grouped: dict[int, list[AuthorStatusServiceEntry]] = {}
    for entry in snapshot.services:
        grouped.setdefault(entry.category, []).append(entry)
    for category, entries in sorted(grouped.items()):
        current_fields: list[AuthorStatusField] = []
        current_chars = 0
        title = _CATEGORY_TITLES.get(category, "SERVICES")
        for entry in entries:
            field = build_service_status_field(entry)
            field_size = len(field.name) + len(field.value)
            if current_fields and (len(current_fields) >= 8 or current_chars + field_size > 3600):
                pages.append(
                    AuthorStatusPage(
                        title="📦 EMBED",
                        description=f"• Author status · {title}",
                        fields=current_fields,
                    )
                )
                current_fields = []
                current_chars = 0
            current_fields.append(field)
            current_chars += field_size
        if current_fields:
            pages.append(
                AuthorStatusPage(
                    title="📦 EMBED",
                    description=f"• Author status · {title}",
                    fields=current_fields,
                )
            )
    total = len(pages)
    for index, page in enumerate(pages, start=1):
        page.description = f"{page.description}\n• Pagina {index}/{total}"
    return pages


async def build_author_status_embeds(
    snapshot: AuthorStatusSnapshot,
    *,
    footer_service=None,
    author_service: AuthorService | None = None,
) -> list[discord.Embed]:
    pages = build_author_status_pages(snapshot)
    embeds: list[discord.Embed] = []
    for page in pages:
        embed = discord.Embed(title=page.title, description=page.description, color=0x3498DB)
        for field in page.fields:
            embed.add_field(name=field.name, value=field.value, inline=False)
        attach_footer_meta(embed, service_name="status")
        attach_author_meta(embed, service_name="status")
        embeds.append(embed)
    await finalize_footer_embeds(embeds, footer_service, default_service_name="status")
    await apply_author_metadata_to_embeds(embeds, author_service, default_service_name="status")
    normalized = normalize_embeds_for_discord(embeds, max_chars=MAX_EMBED_CHARS)
    if normalized is not embeds:
        await finalize_footer_embeds(normalized, footer_service, default_service_name="status")
        await apply_author_metadata_to_embeds(normalized, author_service, default_service_name="status")
    return normalized
