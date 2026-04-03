from __future__ import annotations

from collections.abc import Iterable
import logging
from typing import Any

import discord

from app.services.author import AuthorMeta, AuthorService, attach_author_meta, get_author_meta, render_author_name_with_page
from app.services.footer import get_footer_meta

logger = logging.getLogger(__name__)


def _needs_author_finalize(embed: discord.Embed, *, global_enabled: bool | None = None) -> bool:
    has_meta_before = get_author_meta(embed) is not None
    author_name_before = getattr(embed.author, "name", None)
    needs_finalize = has_meta_before or not author_name_before or (global_enabled is False and bool(author_name_before))
    logger.debug(
        "author finalize: has_meta_before=%s author_name_before=%r global_enabled=%s needs_finalize=%s",
        has_meta_before,
        author_name_before,
        global_enabled,
        needs_finalize,
    )
    return needs_finalize


async def finalize_embed_author(
    embed: discord.Embed,
    author_service: AuthorService | None,
    *,
    default_service_name: str = "unknown",
    page_index: int | None = None,
    page_total: int | None = None,
) -> discord.Embed:
    meta = get_author_meta(embed)
    footer_meta = get_footer_meta(embed)
    author_name_before = getattr(embed.author, "name", None)
    has_explicit_author_before = meta is None and bool(author_name_before)
    if meta is None:
        service_name = getattr(footer_meta, "service_name", None) or default_service_name
        meta = AuthorMeta(service_name=service_name, preserve_existing=True)
    if meta.skip:
        logger.debug("author finalize: skipped_due_to_meta_skip=true service=%s", meta.service_name)
        return embed
    resolved_page_index = meta.logical_page_index if meta.logical_page_index is not None else page_index
    resolved_page_total = meta.logical_page_total if meta.logical_page_total is not None else page_total
    if author_service is None:
        if not getattr(embed.author, "name", None):
            embed.set_author(
                name=render_author_name_with_page(
                    service_name=meta.service_name,
                    canonical_top_level_command=meta.canonical_top_level_command,
                    page_index=resolved_page_index,
                    page_total=resolved_page_total,
                )
            )
        return embed
    try:
        enabled = await author_service.is_enabled()
        if has_explicit_author_before:
            if not enabled:
                embed.remove_author()
            return embed
        if not enabled:
            embed.remove_author()
            return embed
        return await author_service.apply(
            embed,
            default_service_name=default_service_name,
            page_index=resolved_page_index,
            page_total=resolved_page_total,
        )
    except Exception as exc:  # noqa: BLE001
        if "database is locked" in str(exc).lower():
            logger.warning("Author finalize skipped due to SQLite lock")
        else:
            logger.warning("Author finalize failed: %s", exc)
        if not getattr(embed.author, "name", None):
            embed.set_author(
                name=render_author_name_with_page(
                    service_name=meta.service_name,
                    canonical_top_level_command=meta.canonical_top_level_command,
                    page_index=resolved_page_index,
                    page_total=resolved_page_total,
                )
            )
        return embed


def set_logical_author_pagination(embeds: Iterable[discord.Embed] | None) -> list[discord.Embed]:
    embed_list = list(embeds or [])
    total = len(embed_list)
    for idx, embed in enumerate(embed_list, start=1):
        meta = get_author_meta(embed)
        if meta is None:
            continue
        attach_author_meta(
            embed,
            service_name=meta.service_name,
            canonical_top_level_command=meta.canonical_top_level_command,
            author_icon_url=meta.author_icon_url,
            author_url=meta.author_url,
            logical_page_index=idx if total > 1 else None,
            logical_page_total=total if total > 1 else None,
            minimal=meta.minimal,
            skip=meta.skip,
            preserve_existing=meta.preserve_existing,
        )
    return embed_list


async def finalize_embeds_author(
    embeds: Iterable[discord.Embed] | None,
    author_service: AuthorService | None,
    *,
    default_service_name: str = "unknown",
) -> list[discord.Embed]:
    embed_list = set_logical_author_pagination(embeds)
    total = len(embed_list)
    for idx, embed in enumerate(embed_list, start=1):
        await finalize_embed_author(
            embed,
            author_service,
            default_service_name=default_service_name,
            page_index=idx if total > 1 else None,
            page_total=total if total > 1 else None,
        )
    return embed_list


async def apply_author_metadata(
    embed: discord.Embed,
    author_service: AuthorService | None,
    *,
    default_service_name: str = "unknown",
) -> discord.Embed:
    return await finalize_embed_author(embed, author_service, default_service_name=default_service_name)


async def apply_author_metadata_to_embeds(
    embeds: Iterable[discord.Embed] | None,
    author_service: AuthorService | None,
    *,
    default_service_name: str = "unknown",
) -> list[discord.Embed]:
    return await finalize_embeds_author(embeds, author_service, default_service_name=default_service_name)



def install_author_auto_finalize(author_service: AuthorService) -> None:
    if getattr(discord, "_barcellometro_author_patched", False):
        return

    async def _finalize(kwargs: dict[str, Any]) -> None:
        embed = kwargs.get("embed")
        embeds = kwargs.get("embeds")
        global_enabled = await author_service.is_enabled()
        if embed is not None and _needs_author_finalize(embed, global_enabled=global_enabled):
            await finalize_embed_author(embed, author_service)
        if embeds is not None:
            embeds_to_finalize = [candidate for candidate in embeds if _needs_author_finalize(candidate, global_enabled=global_enabled)]
            if embeds_to_finalize:
                await finalize_embeds_author(embeds_to_finalize, author_service)

    orig_interaction_send = discord.InteractionResponse.send_message

    async def patched_interaction_send(self: discord.InteractionResponse, *args: Any, **kwargs: Any):
        await _finalize(kwargs)
        return await orig_interaction_send(self, *args, **kwargs)

    orig_interaction_edit = discord.InteractionResponse.edit_message

    async def patched_interaction_edit(self: discord.InteractionResponse, *args: Any, **kwargs: Any):
        await _finalize(kwargs)
        return await orig_interaction_edit(self, *args, **kwargs)

    orig_followup_send = discord.Webhook.send

    async def patched_followup_send(self: discord.Webhook, *args: Any, **kwargs: Any):
        await _finalize(kwargs)
        return await orig_followup_send(self, *args, **kwargs)

    orig_message_reply = discord.Message.reply

    async def patched_message_reply(self: discord.Message, *args: Any, **kwargs: Any):
        await _finalize(kwargs)
        return await orig_message_reply(self, *args, **kwargs)

    orig_message_edit = discord.Message.edit

    async def patched_message_edit(self: discord.Message, *args: Any, **kwargs: Any):
        await _finalize(kwargs)
        return await orig_message_edit(self, *args, **kwargs)

    orig_channel_send = discord.abc.Messageable.send

    async def patched_channel_send(self: discord.abc.Messageable, *args: Any, **kwargs: Any):
        await _finalize(kwargs)
        return await orig_channel_send(self, *args, **kwargs)

    discord.InteractionResponse.send_message = patched_interaction_send
    discord.InteractionResponse.edit_message = patched_interaction_edit
    discord.Webhook.send = patched_followup_send
    discord.Message.reply = patched_message_reply
    discord.Message.edit = patched_message_edit
    discord.abc.Messageable.send = patched_channel_send
    setattr(discord, "_barcellometro_author_patched", True)
