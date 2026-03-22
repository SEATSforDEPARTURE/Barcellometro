from __future__ import annotations

from collections.abc import Iterable
import logging
from typing import Any

import discord

from app.services.footer import FooterService, get_footer_meta, render_footer_text

logger = logging.getLogger(__name__)


def _needs_footer_finalize(embed: discord.Embed, *, global_enabled: bool | None = None) -> bool:
    has_meta_before = get_footer_meta(embed) is not None
    footer_text_before = getattr(embed.footer, "text", None)
    needs_finalize = has_meta_before or not footer_text_before or (global_enabled is False and bool(footer_text_before))
    logger.debug(
        "footer finalize: has_meta_before=%s footer_text_before=%r global_enabled=%s needs_finalize=%s",
        has_meta_before,
        footer_text_before,
        global_enabled,
        needs_finalize,
    )
    return needs_finalize


async def finalize_embed(
    embed: discord.Embed,
    footer_service: FooterService | None,
    *,
    default_service_name: str = "unknown",
) -> discord.Embed:
    meta = get_footer_meta(embed)
    footer_text_before = getattr(embed.footer, "text", None)
    has_meta_before = meta is not None
    logger.debug(
        "footer finalize: has_meta_before=%s footer_text_before=%r",
        has_meta_before,
        footer_text_before,
    )
    if footer_service is None:
        contributors = getattr(meta, "contributors", ())
        text, _ = render_footer_text(version=None, phrase=None, contributors=contributors)
        if not getattr(embed.footer, "text", None):
            embed.set_footer(text=text)
        return embed
    try:
        enabled = await footer_service.is_enabled()
        if meta is None and footer_text_before:
            if not enabled:
                embed.remove_footer()
            return embed
        if not enabled:
            embed.remove_footer()
            return embed
        return await footer_service.apply(embed, default_service_name=default_service_name)
    except Exception as exc:  # noqa: BLE001
        if "database is locked" in str(exc).lower():
            logger.warning("Footer finalize skipped due to SQLite lock")
        else:
            logger.warning("Footer finalize failed: %s", exc)
        if not getattr(embed.footer, "text", None):
            fallback_text, _ = render_footer_text(
                version=None,
                phrase=None,
                contributors=getattr(meta, "contributors", ()),
            )
            embed.set_footer(text=fallback_text)
        return embed


async def finalize_embeds(
    embeds: Iterable[discord.Embed] | None,
    footer_service: FooterService | None,
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
        global_enabled = await footer_service.is_enabled()
        if embed is not None:
            if _needs_footer_finalize(embed, global_enabled=global_enabled):
                await finalize_embed(embed, footer_service)
        if embeds is not None:
            embeds_to_finalize = [candidate for candidate in embeds if _needs_footer_finalize(candidate, global_enabled=global_enabled)]
            if embeds_to_finalize:
                await finalize_embeds(embeds_to_finalize, footer_service)

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
    setattr(discord, "_barcellometro_footer_patched", True)
