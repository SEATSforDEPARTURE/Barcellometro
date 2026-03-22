from __future__ import annotations

import logging
from typing import Iterable

import discord

from app.shared.discord.embed_limits import RETRY_MAX_EMBED_CHARS, normalize_embeds_for_discord
from app.services.author import AuthorService, copy_author_meta
from app.services.footer import FooterService, copy_footer_meta
from app.shared.discord.author_pipeline import _needs_author_finalize, finalize_embeds_author
from app.shared.discord.footer_pipeline import _needs_footer_finalize, finalize_embeds

logger = logging.getLogger(__name__)


def _is_embed_oversize_error(exc: discord.HTTPException) -> bool:
    return getattr(exc, "code", None) == 50035 and "Embed size exceeds maximum size of 6000" in str(exc)


def _build_send_kwargs(
    *,
    content: str | None = None,
    embeds: list[discord.Embed] | None = None,
    files: list[discord.File] | None = None,
    view: discord.ui.View | None = None,
    ephemeral: bool | None = None,
) -> dict[str, object]:
    kwargs: dict[str, object] = {}
    if content is not None:
        kwargs["content"] = content
    if embeds:
        kwargs["embeds"] = embeds
    if files:
        kwargs["files"] = files
    if view is not None:
        kwargs["view"] = view
    if ephemeral is not None:
        kwargs["ephemeral"] = ephemeral
    return kwargs


def _clone_embeds_for_retry(embeds: Iterable[discord.Embed] | None) -> list[discord.Embed]:
    clones: list[discord.Embed] = []
    for embed in embeds or []:
        clone = discord.Embed.from_dict(embed.to_dict())
        copy_footer_meta(embed, clone)
        copy_author_meta(embed, clone)
        clones.append(clone)
    return clones


async def _prepare_embeds_for_send(
    embeds: list[discord.Embed],
    *,
    footer_service: FooterService | None,
    author_service: AuthorService | None = None,
    default_service_name: str,
) -> list[discord.Embed]:
    if not embeds:
        return embeds
    author_enabled = await author_service.is_enabled() if author_service is not None else None
    footer_enabled = await footer_service.is_enabled() if footer_service is not None else None
    if any(_needs_author_finalize(embed, global_enabled=author_enabled) for embed in embeds):
        embeds = await finalize_embeds_author(embeds, author_service, default_service_name=default_service_name)
    if any(_needs_footer_finalize(embed, global_enabled=footer_enabled) for embed in embeds):
        embeds = await finalize_embeds(embeds, footer_service, default_service_name=default_service_name)
    return embeds


async def safe_followup_send(
    interaction: discord.Interaction,
    *,
    embeds: Iterable[discord.Embed] | None = None,
    content: str | None = None,
    files: list[discord.File] | None = None,
    view: discord.ui.View | None = None,
    ephemeral: bool = True,
    footer_service: FooterService | None = None,
    author_service: AuthorService | None = None,
    default_service_name: str = "unknown",
) -> None:
    embed_list = list(embeds) if embeds is not None else []
    retry_embeds = _clone_embeds_for_retry(embed_list)
    embed_list = await _prepare_embeds_for_send(
        embed_list,
        footer_service=footer_service,
        author_service=author_service,
        default_service_name=default_service_name,
    )
    try:
        await interaction.followup.send(
            **_build_send_kwargs(
                content=content,
                embeds=embed_list,
                files=files,
                view=view,
                ephemeral=ephemeral,
            )
        )
    except discord.HTTPException as exc:
        if _is_embed_oversize_error(exc) and embed_list:
            logger.warning("embed oversize in followup, retrying with smaller chunks")
            status_embeds = normalize_embeds_for_discord([retry_embeds[0]]) if retry_embeds else []
            detail_embeds = normalize_embeds_for_discord(
                retry_embeds[1:],
                max_chars=RETRY_MAX_EMBED_CHARS,
            )
            status_embeds = await _prepare_embeds_for_send(
                status_embeds,
                footer_service=footer_service,
                author_service=author_service,
                default_service_name=default_service_name,
            )
            detail_embeds = await _prepare_embeds_for_send(
                detail_embeds,
                footer_service=footer_service,
                author_service=author_service,
                default_service_name=default_service_name,
            )
            await interaction.followup.send(
                **_build_send_kwargs(
                    content=content,
                    embeds=status_embeds,
                    files=files,
                    view=view,
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
    view: discord.ui.View | None = None,
    ephemeral_fallback: bool = True,
    footer_service: FooterService | None = None,
    author_service: AuthorService | None = None,
    default_service_name: str = "unknown",
) -> bool:
    embed_list = list(embeds) if embeds is not None else []
    retry_embeds = _clone_embeds_for_retry(embed_list)
    embed_list = await _prepare_embeds_for_send(
        embed_list,
        footer_service=footer_service,
        author_service=author_service,
        default_service_name=default_service_name,
    )
    try:
        if embed_list or files:
            await interaction.user.send(embeds=embed_list if embed_list else None, files=files, view=view)
        else:
            await interaction.user.send(content or "", view=view)
        return True
    except discord.Forbidden:
        await safe_followup_send(
            interaction,
            content=content,
            embeds=retry_embeds if retry_embeds else None,
            files=files,
            view=view,
            ephemeral=ephemeral_fallback,
            footer_service=footer_service,
            author_service=author_service,
            default_service_name=default_service_name,
        )
        return False
    except discord.HTTPException as exc:
        if _is_embed_oversize_error(exc) and embed_list:
            logger.warning("embed oversize in DM, retrying with smaller chunks")
            status_embeds = normalize_embeds_for_discord([retry_embeds[0]])
            detail_embeds = normalize_embeds_for_discord(
                retry_embeds[1:],
                max_chars=RETRY_MAX_EMBED_CHARS,
            )
            status_embeds = await _prepare_embeds_for_send(
                status_embeds,
                footer_service=footer_service,
                author_service=author_service,
                default_service_name=default_service_name,
            )
            detail_embeds = await _prepare_embeds_for_send(
                detail_embeds,
                footer_service=footer_service,
                author_service=author_service,
                default_service_name=default_service_name,
            )
            try:
                await interaction.user.send(embeds=status_embeds if status_embeds else None, files=files, view=view)
                if detail_embeds:
                    await interaction.user.send(embeds=detail_embeds)
                return True
            except (discord.Forbidden, discord.HTTPException):
                await safe_followup_send(
                    interaction,
                    content=content,
                    embeds=retry_embeds,
                    files=files,
                    view=view,
                    ephemeral=ephemeral_fallback,
                    footer_service=footer_service,
                    author_service=author_service,
                    default_service_name=default_service_name,
                )
                return False
        await safe_followup_send(
            interaction,
            content=content,
            embeds=retry_embeds,
            files=files,
            view=view,
            ephemeral=ephemeral_fallback,
            footer_service=footer_service,
            author_service=author_service,
            default_service_name=default_service_name,
        )
        return False
