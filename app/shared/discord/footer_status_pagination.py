from __future__ import annotations

import discord

from app.shared.discord.component_notices import send_standard_component_notice


class FooterStatusPaginationView(discord.ui.View):
    def __init__(self, embeds: list[discord.Embed], *, current_index: int = 0, timeout: float | None = 300) -> None:
        super().__init__(timeout=timeout)
        self._embeds = list(embeds)
        self._current_index = min(max(0, int(current_index)), max(0, len(self._embeds) - 1))
        self._sync_button_states()

    @property
    def current_index(self) -> int:
        return self._current_index

    def _sync_button_states(self) -> None:
        is_first = self._current_index <= 0
        is_last = self._current_index >= len(self._embeds) - 1
        self.start_button.disabled = is_first
        self.prev_button.disabled = is_first
        self.next_button.disabled = is_last

    async def _navigate(self, interaction: discord.Interaction, *, target_index: int) -> None:
        if not self._embeds:
            await send_standard_component_notice(
                interaction,
                area="footer status navigation",
                message="Pagine dello status footer non disponibili.",
                kind="warning",
            )
            return

        self._current_index = min(max(0, int(target_index)), len(self._embeds) - 1)
        self._sync_button_states()
        await interaction.response.edit_message(embed=self._embeds[self._current_index], view=self)

    @discord.ui.button(label="INIZIO", style=discord.ButtonStyle.secondary)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        _ = button
        await self._navigate(interaction, target_index=0)

    @discord.ui.button(label="INDIETRO", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        _ = button
        await self._navigate(interaction, target_index=self._current_index - 1)

    @discord.ui.button(label="AVANTI", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        _ = button
        await self._navigate(interaction, target_index=self._current_index + 1)
