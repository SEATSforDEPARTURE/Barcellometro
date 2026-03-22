from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import discord

from app.services.footer import FooterService, attach_footer_meta, get_footer_meta
from app.shared.discord.footer_pipeline import finalize_embed, finalize_embeds

FIELD_MAX = 1024
DESC_MAX = 4096


def truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def safe_add_field(embed: discord.Embed, *, name: str, value: str, inline: bool = False) -> None:
    embed.add_field(name=name, value=truncate(value, FIELD_MAX), inline=inline)


def safe_set_description(embed: discord.Embed, desc: str) -> None:
    embed.description = truncate(desc, DESC_MAX)


def extract_persistable_footer_context(embed: discord.Embed) -> dict[str, Any]:
    meta = get_footer_meta(embed)
    if meta is None:
        return {}
    return {
        "service_name": meta.service_name,
        "contributors": list(meta.contributors),
        "used_local_processing": bool(meta.used_local_processing),
        "footer_icon_url": meta.footer_icon_url,
        "minimal": bool(meta.minimal),
    }


def _normalize_persisted_footer_context(
    footer_context: Mapping[str, Any] | None,
    *,
    default_service_name: str,
) -> dict[str, Any]:
    raw = dict(footer_context or {})
    service_name = str(raw.get("service_name") or default_service_name or "unknown").strip() or "unknown"
    contributors = [str(item).strip() for item in raw.get("contributors") or [] if str(item).strip()]
    return {
        "service_name": service_name,
        "contributors": contributors,
        "used_local_processing": bool(raw.get("used_local_processing", not contributors)),
        "footer_icon_url": str(raw.get("footer_icon_url") or "").strip() or None,
        "minimal": bool(raw.get("minimal", False)),
    }


async def hydrate_persisted_embed_with_footer(
    embed: discord.Embed,
    *,
    footer_context: Mapping[str, Any] | None,
    footer_service: FooterService | None = None,
    default_service_name: str = "unknown",
    finalize: bool = False,
) -> discord.Embed:
    context = _normalize_persisted_footer_context(footer_context, default_service_name=default_service_name)
    attach_footer_meta(
        embed,
        service_name=context["service_name"],
        contributors=context["contributors"],
        used_local_processing=bool(context["used_local_processing"]),
        footer_icon_url=context["footer_icon_url"],
        minimal=bool(context["minimal"]),
    )
    if finalize:
        await finalize_embed(embed, footer_service, default_service_name=context["service_name"])
    return embed


async def hydrate_persisted_embeds_with_footer(
    embeds: Iterable[discord.Embed] | None,
    *,
    footer_contexts: Iterable[Mapping[str, Any] | None] | None = None,
    footer_service: FooterService | None = None,
    default_service_name: str = "unknown",
    finalize: bool = False,
) -> list[discord.Embed]:
    embed_list = list(embeds or [])
    contexts = list(footer_contexts or [])
    for index, embed in enumerate(embed_list):
        context = contexts[index] if index < len(contexts) else None
        await hydrate_persisted_embed_with_footer(
            embed,
            footer_context=context,
            footer_service=footer_service,
            default_service_name=default_service_name,
            finalize=False,
        )
    if finalize:
        await finalize_embeds(embed_list, footer_service, default_service_name=default_service_name)
    return embed_list
