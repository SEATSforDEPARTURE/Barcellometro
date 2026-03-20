from __future__ import annotations

import logging
from typing import Iterable

import discord

from app.shared.discord.embed_limits import RETRY_MAX_EMBED_CHARS, normalize_embeds_for_discord
from app.services.footer import FooterService, get_footer_meta
from app.shared.discord.footer_pipeline import finalize_embeds

logger = logging.getLogger(__name__)


def _is_embed_oversize_error(exc: discord.HTTPException) -> bool:
    return getattr(exc, "code", None) == 50035 and "Embed size exceeds maximum size of 6000" in str(exc)


def _build_send_kwargs(
    *,
    content: str | None = None,
    embeds: list[discord.Embed] | None = None,
    files: list[discord.File] | None = None,
    ephemeral: bool | None = None,
) -> dict[str, object]:
    kwargs: dict[str, object] = {}
    if content is not None:
        kwargs["content"] = content
    if embeds:
        kwargs["embeds"] = embeds
    if files:
        kwargs["files"] = files
    if ephemeral is not None:
        kwargs["ephemeral"] = ephemeral
    return kwargs


async def _prepare_embeds_for_send(
    embeds: list[discord.Embed],
    *,
    footer_service: FooterService | None,
    default_service_name: str,
) -> list[discord.Embed]:
    if footer_service is None or not embeds:
        return embeds
    needs_finalize = any(get_footer_meta(embed) is not None or not getattr(embed.footer, "text", None) for embed in embeds)
    if not needs_finalize:
        return embeds
    return await finalize_embeds(embeds, footer_service, default_service_name=default_service_name)


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
    embed_list = await _prepare_embeds_for_send(
        embed_list,
        footer_service=footer_service,
        default_service_name=default_service_name,
    )
    try:
        await interaction.followup.send(
            **_build_send_kwargs(
                content=content,
                embeds=embed_list,
                files=files,
                ephemeral=ephemeral,
            )
        )
    except discord.HTTPException as exc:
        if _is_embed_oversize_error(exc) and embed_list:
            logger.warning("embed oversize in followup, retrying with smaller chunks")
            status_embeds = normalize_embeds_for_discord([embed_list[0]]) if embed_list else []
            detail_embeds = normalize_embeds_for_discord(
                embed_list[1:],
                max_chars=RETRY_MAX_EMBED_CHARS,
            )
            status_embeds = await _prepare_embeds_for_send(
                status_embeds,
                footer_service=footer_service,
                default_service_name=default_service_name,
            )
            detail_embeds = await _prepare_embeds_for_send(
                detail_embeds,
                footer_service=footer_service,
                default_service_name=default_service_name,
            )
            await interaction.followup.send(
                **_build_send_kwargs(
                    content=content,
                    embeds=status_embeds,
                    files=files,
                    ephemeral=ephemeral,
                )
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
    embed_list = await _prepare_embeds_for_send(
        embed_list,
        footer_service=footer_service,
        default_service_name=default_service_name,
    )
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
            footer_service=footer_service,
            default_service_name=default_service_name,
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
            status_embeds = await _prepare_embeds_for_send(
                status_embeds,
                footer_service=footer_service,
                default_service_name=default_service_name,
            )
            detail_embeds = await _prepare_embeds_for_send(
                detail_embeds,
                footer_service=footer_service,
                default_service_name=default_service_name,
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
                    embeds=embed_list,
                    files=files,
                    ephemeral=ephemeral_fallback,
                    footer_service=footer_service,
                    default_service_name=default_service_name,
                )
                return False
        await safe_followup_send(
            interaction,
            content=content,
            embeds=embed_list,
            files=files,
            ephemeral=ephemeral_fallback,
            footer_service=footer_service,
            default_service_name=default_service_name,
        )
        return False
