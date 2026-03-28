from __future__ import annotations

from collections.abc import Iterable

import discord

from app.services.author import attach_author_meta
from app.services.discord_embed_utils import safe_add_field, safe_set_description
from app.services.footer import attach_footer_meta
from app.shared.discord.embed_body import format_standard_field_name, format_standard_title
from app.shared.discord.embed_rendering import finalize_embeds_rendering


async def build_standard_dm_embed(
    *,
    service_name: str,
    canonical_top_level_command: str | None,
    title: str,
    title_emoji: str,
    description: str,
    color: discord.Colour,
    fields: Iterable[tuple[str, str, bool]] | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=format_standard_title(title, emoji=title_emoji),
        color=color,
    )
    safe_set_description(embed, description)
    for field_name, field_value, inline in fields or []:
        safe_add_field(
            embed,
            name=format_standard_field_name(field_name),
            value=field_value,
            inline=inline,
        )
    attach_author_meta(
        embed,
        service_name=service_name,
        canonical_top_level_command=canonical_top_level_command,
    )
    attach_footer_meta(embed, service_name=service_name, used_local_processing=True)
    await finalize_embeds_rendering(
        [embed],
        footer_service=None,
        author_service=None,
        default_service_name=service_name,
    )
    return embed
