from __future__ import annotations

from collections.abc import Iterable

import discord

from app.services.author import AuthorService
from app.services.footer import FooterService
from app.shared.discord.author_pipeline import _needs_author_finalize, finalize_embed_author
from app.shared.discord.footer_pipeline import _needs_footer_finalize, finalize_embed


async def finalize_embed_rendering(
    embed: discord.Embed,
    *,
    footer_service: FooterService | None,
    author_service: AuthorService | None,
    default_service_name: str = "unknown",
    page_index: int | None = None,
    page_total: int | None = None,
) -> discord.Embed:
    author_enabled = await author_service.is_enabled() if author_service is not None else None
    footer_enabled = await footer_service.is_enabled() if footer_service is not None else None

    if _needs_author_finalize(embed, global_enabled=author_enabled):
        await finalize_embed_author(
            embed,
            author_service,
            default_service_name=default_service_name,
            page_index=page_index,
            page_total=page_total,
        )
    if _needs_footer_finalize(embed, global_enabled=footer_enabled):
        await finalize_embed(embed, footer_service, default_service_name=default_service_name)
    return embed


async def finalize_embeds_rendering(
    embeds: Iterable[discord.Embed] | None,
    *,
    footer_service: FooterService | None,
    author_service: AuthorService | None,
    default_service_name: str = "unknown",
) -> list[discord.Embed]:
    embed_list = list(embeds or [])
    total = len(embed_list)
    for idx, embed in enumerate(embed_list, start=1):
        await finalize_embed_rendering(
            embed,
            footer_service=footer_service,
            author_service=author_service,
            default_service_name=default_service_name,
            page_index=idx if total > 1 else None,
            page_total=total if total > 1 else None,
        )
    return embed_list
