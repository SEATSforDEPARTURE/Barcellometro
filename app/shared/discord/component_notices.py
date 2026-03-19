from __future__ import annotations

from typing import Any

import discord

from app.shared.discord.command_embeds import build_command_embed


async def send_standard_component_notice(
    interaction: discord.Interaction,
    *,
    message: str,
    kind: str = "info",
    area: str = "component",
    detail_key: str = "dettaglio",
    ephemeral: bool = True,
) -> None:
    embed = await build_command_embed(
        top_level="commandguard",
        subcommand_path=area,
        lines=[(detail_key, str(message or "").strip() or "Nessun dettaglio disponibile.")],
        kind=kind,  # type: ignore[arg-type]
    )
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
