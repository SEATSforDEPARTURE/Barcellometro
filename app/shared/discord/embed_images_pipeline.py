from __future__ import annotations

from collections.abc import Iterable
import logging
from typing import Any

import discord

from app.services.embed_images import EmbedImagesService, get_embed_images_meta

logger = logging.getLogger(__name__)


def _needs_images_finalize(embed: discord.Embed, *, global_enabled: bool | None = None) -> bool:
    has_meta = get_embed_images_meta(embed) is not None
    has_runtime_image = bool(getattr(embed.image, "url", None))
    has_runtime_thumb = bool(getattr(embed.thumbnail, "url", None))
    if global_enabled is False:
        return has_meta or has_runtime_image or has_runtime_thumb
    return True


async def finalize_embed_images(
    embed: discord.Embed,
    embed_images_service: EmbedImagesService | None,
    *,
    default_service_name: str = "unknown",
) -> discord.Embed:
    if embed_images_service is None:
        return embed
    try:
        return await embed_images_service.apply(embed, default_service_name=default_service_name)
    except Exception as exc:  # noqa: BLE001
        if "database is locked" in str(exc).lower():
            logger.warning("Embed images finalize skipped due to SQLite lock")
        else:
            logger.warning("Embed images finalize failed: %s", exc)
        return embed


async def finalize_embeds_images(
    embeds: Iterable[discord.Embed] | None,
    embed_images_service: EmbedImagesService | None,
    *,
    default_service_name: str = "unknown",
) -> list[discord.Embed]:
    embed_list = list(embeds or [])
    for embed in embed_list:
        await finalize_embed_images(embed, embed_images_service, default_service_name=default_service_name)
    return embed_list


def install_embed_images_auto_finalize(embed_images_service: EmbedImagesService) -> None:
    if getattr(discord, "_barcellometro_embed_images_patched", False):
        return

    async def _finalize(kwargs: dict[str, Any]) -> None:
        embed = kwargs.get("embed")
        embeds = kwargs.get("embeds")
        global_enabled = await embed_images_service.is_enabled()
        if embed is not None and _needs_images_finalize(embed, global_enabled=global_enabled):
            await finalize_embed_images(embed, embed_images_service)
        if embeds is not None:
            embeds_to_finalize = [candidate for candidate in embeds if _needs_images_finalize(candidate, global_enabled=global_enabled)]
            if embeds_to_finalize:
                await finalize_embeds_images(embeds_to_finalize, embed_images_service)

    orig_interaction_send = discord.InteractionResponse.send_message
    orig_interaction_edit = discord.InteractionResponse.edit_message
    orig_followup_send = discord.Webhook.send
    orig_message_reply = discord.Message.reply
    orig_message_edit = discord.Message.edit
    orig_channel_send = discord.abc.Messageable.send

    async def patched_interaction_send(self: discord.InteractionResponse, *args: Any, **kwargs: Any):
        await _finalize(kwargs)
        return await orig_interaction_send(self, *args, **kwargs)

    async def patched_interaction_edit(self: discord.InteractionResponse, *args: Any, **kwargs: Any):
        await _finalize(kwargs)
        return await orig_interaction_edit(self, *args, **kwargs)

    async def patched_followup_send(self: discord.Webhook, *args: Any, **kwargs: Any):
        await _finalize(kwargs)
        return await orig_followup_send(self, *args, **kwargs)

    async def patched_message_reply(self: discord.Message, *args: Any, **kwargs: Any):
        await _finalize(kwargs)
        return await orig_message_reply(self, *args, **kwargs)

    async def patched_message_edit(self: discord.Message, *args: Any, **kwargs: Any):
        await _finalize(kwargs)
        return await orig_message_edit(self, *args, **kwargs)

    async def patched_channel_send(self: discord.abc.Messageable, *args: Any, **kwargs: Any):
        await _finalize(kwargs)
        return await orig_channel_send(self, *args, **kwargs)

    discord.InteractionResponse.send_message = patched_interaction_send
    discord.InteractionResponse.edit_message = patched_interaction_edit
    discord.Webhook.send = patched_followup_send
    discord.Message.reply = patched_message_reply
    discord.Message.edit = patched_message_edit
    discord.abc.Messageable.send = patched_channel_send
    setattr(discord, "_barcellometro_embed_images_patched", True)
