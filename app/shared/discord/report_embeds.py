from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import discord

from app.services.footer import attach_footer_meta, attach_footer_meta_to_all


def build_report_cover_embed(
    *,
    title: str,
    description: str | None = None,
    color: int = 0x5865F2,
    service_name: str,
    lines: Sequence[tuple[str, Any]] | None = None,
) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    for label, value in lines or []:
        text = str(value or "—").strip() or "—"
        embed.add_field(name=str(label), value=text[:1024], inline=False)
    attach_footer_meta(embed, service_name=service_name, used_local_processing=True)
    return embed


def apply_standard_report_style(
    embeds: Iterable[discord.Embed] | None,
    *,
    service_name: str,
    cover_title: str | None = None,
    cover_color: int | None = None,
) -> list[discord.Embed]:
    embed_list = list(embeds or [])
    if not embed_list:
        return []
    if cover_title:
        embed_list[0].title = cover_title
    if cover_color is not None and embed_list[0].color != discord.Color(cover_color):
        embed_list[0].color = discord.Color(cover_color)
    attach_footer_meta_to_all(embed_list, service_name=service_name, used_local_processing=True)
    return embed_list


async def send_report_dm_chunks(
    destination: discord.abc.Messageable,
    *,
    embeds: Sequence[discord.Embed],
    files: list[discord.File] | None = None,
    chunk_size: int = 10,
) -> None:
    embed_list = list(embeds)
    if not embed_list:
        if files:
            await destination.send(files=files)
        return
    for idx in range(0, len(embed_list), chunk_size):
        batch_files = files if idx == 0 else None
        await destination.send(embeds=embed_list[idx : idx + chunk_size], files=batch_files)
