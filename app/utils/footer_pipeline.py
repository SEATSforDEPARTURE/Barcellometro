from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import discord

from app.services.footer import FooterService


async def finalize_embed(embed: discord.Embed, footer_service: FooterService, *, default_service_name: str = "unknown") -> discord.Embed:
    return await footer_service.apply(embed, default_service_name=default_service_name)


async def finalize_embeds(
    embeds: Iterable[discord.Embed] | None,
    footer_service: FooterService,
    *,
    default_service_name: str = "unknown",
) -> list[discord.Embed]:
    embed_list = list(embeds or [])
    for embed in embed_list:
        await finalize_embed(embed, footer_service, default_service_name=default_service_name)
    return embed_list


def install_footer_auto_finalize(footer_service: FooterService) -> None:
    if getattr(discord, "_barcellometro_footer_patched", False):
        return

    async def _finalize(kwargs: dict[str, Any]) -> None:
        embed = kwargs.get("embed")
        embeds = kwargs.get("embeds")
        if embed is not None:
            await finalize_embed(embed, footer_service)
        if embeds is not None:
            await finalize_embeds(embeds, footer_service)

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
    setattr(discord, "_barcellometro_footer_patched", True)
