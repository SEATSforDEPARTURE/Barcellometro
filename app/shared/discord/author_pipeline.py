from __future__ import annotations

from collections.abc import Iterable
import logging
from typing import Any

import discord

from app.services.author import AuthorMeta, AuthorService, get_author_meta, render_author_name
from app.services.footer import get_footer_meta

logger = logging.getLogger(__name__)


def _needs_author_finalize(embed: discord.Embed) -> bool:
    has_meta_before = get_author_meta(embed) is not None
    author_name_before = getattr(embed.author, "name", None)
    needs_finalize = has_meta_before or not author_name_before
    logger.debug(
        "author finalize: has_meta_before=%s author_name_before=%r needs_finalize=%s",
        has_meta_before,
        author_name_before,
        needs_finalize,
    )
    return needs_finalize


async def finalize_embed_author(
    embed: discord.Embed,
    author_service: AuthorService | None,
    *,
    default_service_name: str = "unknown",
) -> discord.Embed:
    meta = get_author_meta(embed)
    footer_meta = get_footer_meta(embed)
    author_name_before = getattr(embed.author, "name", None)
    if meta is None and author_name_before:
        logger.debug("author finalize: skipped_preserving_explicit_author=true")
        return embed
    if meta is None:
        service_name = getattr(footer_meta, "service_name", None) or default_service_name
        meta = AuthorMeta(service_name=service_name, preserve_existing=True)
    if meta.skip:
        logger.debug("author finalize: skipped_due_to_meta_skip=true service=%s", meta.service_name)
        return embed
    if author_service is None:
        if not getattr(embed.author, "name", None):
            embed.set_author(name=render_author_name(service_name=meta.service_name))
        return embed
    try:
        if not await author_service.is_enabled():
            return embed
        return await author_service.apply(embed, default_service_name=default_service_name)
    except Exception as exc:  # noqa: BLE001
        if "database is locked" in str(exc).lower():
            logger.warning("Author finalize skipped due to SQLite lock")
        else:
            logger.warning("Author finalize failed: %s", exc)
        if not getattr(embed.author, "name", None):
            embed.set_author(name=render_author_name(service_name=meta.service_name))
        return embed


async def finalize_embeds_author(
    embeds: Iterable[discord.Embed] | None,
    author_service: AuthorService | None,
    *,
    default_service_name: str = "unknown",
) -> list[discord.Embed]:
    embed_list = list(embeds or [])
    for embed in embed_list:
        await finalize_embed_author(embed, author_service, default_service_name=default_service_name)
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
        if embed is not None and _needs_author_finalize(embed):
            await finalize_embed_author(embed, author_service)
        if embeds is not None:
            embeds_to_finalize = [candidate for candidate in embeds if _needs_author_finalize(candidate)]
            if embeds_to_finalize:
                await finalize_embeds_author(embeds_to_finalize, author_service)

    orig_interaction_send = discord.InteractionResponse.send_message

    async def patched_interaction_send(self: discord.InteractionResponse, *args: Any, **kwargs: Any):
        await _finalize(kwargs)
        return await orig_interaction_send(self, *args, **kwargs)

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
    discord.Webhook.send = patched_followup_send
    discord.Message.reply = patched_message_reply
    discord.Message.edit = patched_message_edit
    discord.abc.Messageable.send = patched_channel_send
    setattr(discord, "_barcellometro_author_patched", True)
