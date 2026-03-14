from __future__ import annotations

from typing import Any

import discord

from app.services.campaign_content_formatter import SIGN_EMOJIS, SIGN_ORDER


class CampaignContentPaginationView(discord.ui.View):
    def __init__(self, service: Any, *, current_index: int = 0, total_pages: int = 1) -> None:
        super().__init__(timeout=None)
        self._service = service
        self._current_index = current_index
        self._total_pages = max(1, total_pages)
        self._sync()

    def _sync(self) -> None:
        is_first = self._current_index <= 0
        is_last = self._current_index >= self._total_pages - 1
        self.start_button.disabled = is_first
        self.prev_button.disabled = is_first
        self.next_button.disabled = is_last

    async def _navigate(self, interaction: discord.Interaction, target: int) -> None:
        message = interaction.message
        if message is None:
            await interaction.response.send_message("Messaggio non disponibile.", ephemeral=True)
            return
        record = await self._service.load_message_record(str(message.id))
        if record is None:
            await interaction.response.send_message("Navigazione non disponibile.", ephemeral=True)
            return
        embeds = record.get("embeds", [])
        target_index = max(0, min(target, len(embeds) - 1))
        self._current_index = target_index
        self._total_pages = len(embeds)
        self._sync()
        await self._service.persist_current_index(str(message.id), target_index)
        await interaction.response.edit_message(embed=discord.Embed.from_dict(embeds[target_index]), view=self)

    @discord.ui.button(label="⏮️ INIZIO", style=discord.ButtonStyle.secondary, custom_id="campaign_content:nav:start")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        _ = button
        await self._navigate(interaction, 0)

    @discord.ui.button(label="⬅️ INDIETRO", style=discord.ButtonStyle.secondary, custom_id="campaign_content:nav:prev")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        _ = button
        await self._navigate(interaction, self._current_index - 1)

    @discord.ui.button(label="➡️ AVANTI", style=discord.ButtonStyle.primary, custom_id="campaign_content:nav:next")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        _ = button
        await self._navigate(interaction, self._current_index + 1)


class HoroscopeNavButton(discord.ui.Button["HoroscopePaginationView"]):
    def __init__(self, *, label: str, custom_id: str, target_index: int, row: int, style: discord.ButtonStyle = discord.ButtonStyle.primary) -> None:
        super().__init__(label=label, style=style, custom_id=custom_id, row=row)
        self._target_index = target_index

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if view is None:
            await interaction.response.send_message("Navigazione non disponibile.", ephemeral=True)
            return
        await view._go_to(interaction, self._target_index)


class HoroscopePaginationView(discord.ui.View):
    def __init__(self, service: Any) -> None:
        super().__init__(timeout=None)
        self._service = service
        self.add_item(
            HoroscopeNavButton(
                label="OVERVIEW",
                style=discord.ButtonStyle.secondary,
                custom_id="campaign_content:sign:overview",
                target_index=0,
                row=0,
            )
        )
        for index, sign in enumerate(SIGN_ORDER, start=1):
            row = 1 + ((index - 1) // 5)
            self.add_item(
                HoroscopeNavButton(
                    label=f"{SIGN_EMOJIS.get(sign, '✨')} {sign.upper()}",
                    custom_id=f"campaign_content:sign:{sign.lower()}",
                    target_index=index,
                    row=row,
                )
            )

    async def _go_to(self, interaction: discord.Interaction, index: int) -> None:
        message = interaction.message
        if message is None:
            await interaction.response.send_message("Messaggio non disponibile.", ephemeral=True)
            return
        record = await self._service.load_message_record(str(message.id))
        if record is None:
            await interaction.response.send_message("Navigazione non disponibile.", ephemeral=True)
            return
        embeds = record.get("embeds", [])
        if index >= len(embeds):
            await interaction.response.send_message("Pagina non disponibile.", ephemeral=True)
            return
        await self._service.persist_current_index(str(message.id), index)
        await interaction.response.edit_message(embed=discord.Embed.from_dict(embeds[index]), view=self)
