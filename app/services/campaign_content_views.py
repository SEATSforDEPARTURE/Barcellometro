from __future__ import annotations

from typing import Any

import discord

from app.services.discord_embed_utils import hydrate_persisted_embed_with_footer
from app.services.embed_public_service_keys import resolve_public_embed_service_key
from app.shared.discord.component_notices import send_standard_component_notice


def _fallback_campaign_footer_context(service: Any, *, service_type: str, metadata: dict[str, Any] | None) -> dict[str, Any]:
    resolved_service_name = None
    if hasattr(service, "_campaign_footer_service_name"):
        resolved_service_name = service._campaign_footer_service_name(service_type)  # type: ignore[attr-defined]
    if not resolved_service_name:
        mapped_service = {
            "NEWS": "campagne_notizie",
            "WEATHER": "campagne_meteo",
            "HOROSCOPE": "campagne_oroscopo",
        }.get(str(service_type or "").upper())
        if mapped_service:
            resolved_service_name = mapped_service
        elif resolve_public_embed_service_key(str(service_type or ""), system="author") == "campaigns":
            resolved_service_name = "campagne_notizie"
        else:
            resolved_service_name = "campagne_notizie"

    contributors: list[str] = []
    if hasattr(service, "_campaign_footer_contributors"):
        contributors = list(service._campaign_footer_contributors(metadata))  # type: ignore[attr-defined]
    elif isinstance(metadata, dict):
        seen: set[str] = set()
        for source in metadata.get("used_sources") or metadata.get("configured_sources") or []:
            token = str(source or "").strip()
            if token and token not in seen:
                contributors.append(token)
                seen.add(token)
        model = str(metadata.get("used_model") or metadata.get("ai_model_used") or "").strip()
        if model and model not in {"unknown"} and model not in seen:
            contributors.append(model)

    return {
        "service_name": resolved_service_name,
        "contributors": contributors,
        "used_local_processing": not contributors,
    }


class PageJumpButton(discord.ui.Button["BaseCampaignNavigatorView"]):
    def __init__(self, *, label: str, custom_id: str, target_index: int, row: int, style: discord.ButtonStyle = discord.ButtonStyle.secondary) -> None:
        super().__init__(label=label, style=style, custom_id=custom_id, row=row)
        self._target_index = target_index

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is None:
            await send_standard_component_notice(interaction, area="campaign navigation", message="Navigazione non disponibile.", kind="warning", ephemeral=True)
            return
        await self.view.navigate(interaction, self._target_index)


class BaseCampaignNavigatorView(discord.ui.View):
    def __init__(
        self,
        service: Any,
        *,
        embeds: list[dict[str, Any]],
        page_map: list[dict[str, Any]],
        service_type: str,
        metadata: dict[str, Any] | None = None,
        current_index: int = 0,
        timeout: float | None = None,
    ) -> None:
        super().__init__(timeout=timeout)
        self._service = service
        self._embeds = embeds
        self._page_map = page_map
        self._service_type = service_type
        self._metadata = metadata
        self._current_index = max(0, min(current_index, max(0, len(embeds) - 1)))
        self._build_dynamic_buttons()
        self._sync_controls()

    def _build_dynamic_buttons(self) -> None:
        dynamic = [entry for entry in self._page_map if entry.get("type") not in {"overview"}]
        for idx, entry in enumerate(dynamic):
            row = idx // 5
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
        for item in self.children:
            if isinstance(item, PageJumpButton):
                item.disabled = item._target_index == self._current_index

    async def navigate(self, interaction: discord.Interaction, target_index: int) -> None:
        self._current_index = max(0, min(target_index, len(self._embeds) - 1))
        self._sync_controls()
        embed_payload = self._embeds[self._current_index]
        if hasattr(self._service, "_hydrate_stored_campaign_embed"):
            embed = await self._service._hydrate_stored_campaign_embed(  # type: ignore[attr-defined]
                service_type=self._service_type,
                embed_payload=embed_payload,
                metadata=self._metadata,
            )
        else:
            embed = discord.Embed.from_dict(embed_payload)
            footer_context = _fallback_campaign_footer_context(
                self._service,
                service_type=self._service_type,
                metadata=self._metadata,
            )
            await hydrate_persisted_embed_with_footer(
                embed,
                footer_context=footer_context,
                default_service_name=str(footer_context.get("service_name") or "campagne_notizie"),
            )
        await interaction.response.edit_message(embed=embed, view=self)


class PersistentCampaignLauncherView(discord.ui.View):
    def __init__(self, service: Any, *, service_type: str, total_pages: int, page_map: list[dict[str, Any]]) -> None:
        super().__init__(timeout=None)
        self._service = service
        self._service_type = service_type
        self._total_pages = total_pages
        self._page_map = page_map
        self._build()

    def _build(self) -> None:
        dynamic = [entry for entry in self._page_map if entry.get("type") != "overview"]
        for idx, entry in enumerate(dynamic):
            row = idx // 5
            self.add_item(PageJumpButton(label=str(entry.get("label") or "Pagina")[:80], custom_id=f"campaign_content:{self._service_type}:jump:{entry.get('key', idx)}", target_index=int(entry.get("page", 0)), row=row))

    async def _open_ephemeral(self, interaction: discord.Interaction, target_index: int) -> None:
        try:
            ok = await self._service.open_personal_navigator(interaction, target_index=target_index, service_type=self._service_type)
        except Exception:
            if interaction.response.is_done():
                await send_standard_component_notice(interaction, area="campaign navigation", message="Navigazione non disponibile.", kind="warning", ephemeral=True)
            else:
                await send_standard_component_notice(interaction, area="campaign navigation", message="Navigazione non disponibile.", kind="warning", ephemeral=True)
            return

        if ok:
            return

        if interaction.response.is_done():
            await send_standard_component_notice(interaction, area="campaign navigation", message="Navigazione non disponibile.", kind="warning", ephemeral=True)
        else:
            await send_standard_component_notice(interaction, area="campaign navigation", message="Navigazione non disponibile.", kind="warning", ephemeral=True)

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
    await send_standard_component_notice(interaction, area="campaign navigation", message="Navigazione non disponibile.", kind="warning", ephemeral=True)


PageJumpButton.callback = _page_jump_callback  # type: ignore[method-assign]
