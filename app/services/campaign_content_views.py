from __future__ import annotations

from typing import Any

import discord


class PageJumpButton(discord.ui.Button["BaseCampaignNavigatorView"]):
    def __init__(self, *, label: str, custom_id: str, target_index: int, row: int, style: discord.ButtonStyle = discord.ButtonStyle.secondary) -> None:
        super().__init__(label=label, style=style, custom_id=custom_id, row=row)
        self._target_index = target_index

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is None:
            await interaction.response.send_message("Navigazione non disponibile.", ephemeral=True)
            return
        await self.view.navigate(interaction, self._target_index)


class BaseCampaignNavigatorView(discord.ui.View):
    def __init__(self, service: Any, *, embeds: list[dict[str, Any]], page_map: list[dict[str, Any]], current_index: int = 0, timeout: float | None = None) -> None:
        super().__init__(timeout=timeout)
        self._service = service
        self._embeds = embeds
        self._page_map = page_map
        self._current_index = max(0, min(current_index, max(0, len(embeds) - 1)))
        self._build_nav_buttons()
        self._build_dynamic_buttons()
        self._sync_controls()

    def _build_nav_buttons(self) -> None:
        self.add_item(PageJumpButton(label="⏮️ INIZIO", custom_id=f"campaign_content:nav:start:{id(self)}", target_index=0, row=0))
        self.add_item(PageJumpButton(label="⬅️ INDIETRO", custom_id=f"campaign_content:nav:prev:{id(self)}", target_index=max(0, self._current_index - 1), row=0))
        self.add_item(PageJumpButton(label="➡️ AVANTI", custom_id=f"campaign_content:nav:next:{id(self)}", target_index=min(len(self._embeds) - 1, self._current_index + 1), row=0, style=discord.ButtonStyle.primary))

    def _build_dynamic_buttons(self) -> None:
        dynamic = [entry for entry in self._page_map if entry.get("type") not in {"overview"}]
        for idx, entry in enumerate(dynamic):
            row = 1 + (idx // 5)
            label = str(entry.get("label") or "Pagina")[:80]
            key = str(entry.get("key") or idx)
            self.add_item(
                PageJumpButton(
                    label=label,
                    custom_id=f"campaign_content:jump:{key}:{id(self)}",
                    target_index=int(entry.get("page", 0)),
                    row=row,
                )
            )

    def _sync_controls(self) -> None:
        first = self._current_index <= 0
        last = self._current_index >= len(self._embeds) - 1
        nav_buttons = [item for item in self.children if isinstance(item, PageJumpButton)][:3]
        if len(nav_buttons) == 3:
            nav_buttons[0].disabled = first
            nav_buttons[0]._target_index = 0
            nav_buttons[1].disabled = first
            nav_buttons[1]._target_index = max(0, self._current_index - 1)
            nav_buttons[2].disabled = last
            nav_buttons[2]._target_index = min(len(self._embeds) - 1, self._current_index + 1)

    async def navigate(self, interaction: discord.Interaction, target_index: int) -> None:
        self._current_index = max(0, min(target_index, len(self._embeds) - 1))
        self._sync_controls()
        await interaction.response.edit_message(embed=discord.Embed.from_dict(self._embeds[self._current_index]), view=self)


class PersistentCampaignLauncherView(discord.ui.View):
    def __init__(self, service: Any, *, service_type: str, total_pages: int, page_map: list[dict[str, Any]]) -> None:
        super().__init__(timeout=None)
        self._service = service
        self._service_type = service_type
        self._total_pages = total_pages
        self._page_map = page_map
        self._build()

    def _build(self) -> None:
        self.add_item(PageJumpButton(label="⏮️ INIZIO", custom_id=f"campaign_content:{self._service_type}:start", target_index=0, row=0))
        self.add_item(PageJumpButton(label="⬅️ INDIETRO", custom_id=f"campaign_content:{self._service_type}:prev", target_index=0, row=0))
        self.add_item(PageJumpButton(label="➡️ AVANTI", custom_id=f"campaign_content:{self._service_type}:next", target_index=min(1, self._total_pages - 1), row=0, style=discord.ButtonStyle.primary))
        dynamic = [entry for entry in self._page_map if entry.get("type") != "overview"]
        for idx, entry in enumerate(dynamic):
            row = 1 + (idx // 5)
            self.add_item(PageJumpButton(label=str(entry.get("label") or "Pagina")[:80], custom_id=f"campaign_content:{self._service_type}:jump:{entry.get('key', idx)}", target_index=int(entry.get("page", 0)), row=row))
        self._sync()

    def _sync(self) -> None:
        nav = [item for item in self.children if isinstance(item, PageJumpButton)][:3]
        if len(nav) == 3:
            nav[0].disabled = True
            nav[1].disabled = True
            nav[2].disabled = self._total_pages <= 1

    async def _open_ephemeral(self, interaction: discord.Interaction, target_index: int) -> None:
        ok = await self._service.open_personal_navigator(interaction, target_index=target_index, service_type=self._service_type)
        if ok:
            return
        # fallback legacy
        await self._service.edit_public_message(interaction, target_index=target_index)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True


# patch button callback routing for launcher buttons
PageJumpButton._orig_callback = PageJumpButton.callback  # type: ignore[attr-defined]


async def _page_jump_callback(self: PageJumpButton, interaction: discord.Interaction) -> None:
    view = self.view
    if isinstance(view, PersistentCampaignLauncherView):
        await view._open_ephemeral(interaction, self._target_index)
        return
    if isinstance(view, BaseCampaignNavigatorView):
        await view.navigate(interaction, self._target_index)
        return
    await interaction.response.send_message("Navigazione non disponibile.", ephemeral=True)


PageJumpButton.callback = _page_jump_callback  # type: ignore[method-assign]
