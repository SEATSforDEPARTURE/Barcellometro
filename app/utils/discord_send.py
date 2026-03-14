from __future__ import annotations

import logging
from typing import Iterable

import discord

from app.utils.embed_limits import RETRY_MAX_EMBED_CHARS, normalize_embeds_for_discord
from app.services.footer import FooterService
from app.utils.footer_pipeline import finalize_embeds

logger = logging.getLogger(__name__)


def _is_embed_oversize_error(exc: discord.HTTPException) -> bool:
    return getattr(exc, "code", None) == 50035 and "Embed size exceeds maximum size of 6000" in str(exc)


async def safe_followup_send(
    interaction: discord.Interaction,
    *,
    embeds: Iterable[discord.Embed] | None = None,
    content: str | None = None,
    files: list[discord.File] | None = None,
    ephemeral: bool = True,
    footer_service: FooterService | None = None,
    default_service_name: str = "unknown",
) -> None:
    embed_list = list(embeds) if embeds is not None else []
    if footer_service is not None and embed_list:
        embed_list = await finalize_embeds(embed_list, footer_service, default_service_name=default_service_name)
    try:
        await interaction.followup.send(
            content=content,
            embeds=embed_list if embed_list else None,
            files=files,
            ephemeral=ephemeral,
        )
    except discord.HTTPException as exc:
        if _is_embed_oversize_error(exc) and embed_list:
            logger.warning("embed oversize in followup, retrying with smaller chunks")
            status_embeds = normalize_embeds_for_discord([embed_list[0]]) if embed_list else []
            detail_embeds = normalize_embeds_for_discord(
                embed_list[1:],
                max_chars=RETRY_MAX_EMBED_CHARS,
            )
            await interaction.followup.send(
                content=content,
                embeds=status_embeds if status_embeds else None,
                files=files,
                ephemeral=ephemeral,
            )
            if detail_embeds:
                await interaction.followup.send(embeds=detail_embeds, ephemeral=ephemeral)
        else:
            raise


async def send_dm_or_followup(
    interaction: discord.Interaction,
    *,
    embeds: Iterable[discord.Embed] | None = None,
    content: str | None = None,
    files: list[discord.File] | None = None,
    ephemeral_fallback: bool = True,
    footer_service: FooterService | None = None,
    default_service_name: str = "unknown",
) -> bool:
    embed_list = list(embeds) if embeds is not None else []
    if footer_service is not None and embed_list:
        embed_list = await finalize_embeds(embed_list, footer_service, default_service_name=default_service_name)
    try:
        if embed_list or files:
            await interaction.user.send(embeds=embed_list if embed_list else None, files=files)
        else:
            await interaction.user.send(content or "")
        return True
    except discord.Forbidden:
        await safe_followup_send(
            interaction,
            content=content,
            embeds=embed_list if embed_list else None,
            files=files,
            ephemeral=ephemeral_fallback,
        )
        return False
    except discord.HTTPException as exc:
        if _is_embed_oversize_error(exc) and embed_list:
            logger.warning("embed oversize in DM, retrying with smaller chunks")
            status_embeds = normalize_embeds_for_discord([embed_list[0]])
            detail_embeds = normalize_embeds_for_discord(
                embed_list[1:],
                max_chars=RETRY_MAX_EMBED_CHARS,
            )
            try:
                await interaction.user.send(embeds=status_embeds if status_embeds else None, files=files)
                if detail_embeds:
                    await interaction.user.send(embeds=detail_embeds)
                return True
            except (discord.Forbidden, discord.HTTPException):
                await safe_followup_send(
                    interaction,
                    content=content,
                    embeds=embed_list if embed_list else None,
                    files=files,
                    ephemeral=ephemeral_fallback,
                )
                return False
        await safe_followup_send(
            interaction,
            content=content,
            embeds=embed_list if embed_list else None,
            files=files,
            ephemeral=ephemeral_fallback,
        )
        return False
