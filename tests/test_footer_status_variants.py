import asyncio
from pathlib import Path
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(Connection=object)
if "httpx" not in sys.modules:
    httpx_stub = types.ModuleType("httpx")

    class _AsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

        async def get(self, *args, **kwargs):
            raise RuntimeError("httpx stub: network call not configured in this test")

    httpx_stub.AsyncClient = _AsyncClient
    sys.modules["httpx"] = httpx_stub

from discord import app_commands

from app.plugins.commands_modular.embed import register_embed
from app.services.footer import FooterService, ServiceFooterProfile
from app.shared.discord.embed_limits import (
    DISCORD_MAX_EMBED_DESCRIPTION,
    DISCORD_MAX_EMBED_TITLE,
    DISCORD_MAX_FIELD_VALUE,
    DISCORD_MAX_FIELDS,
    MAX_EMBED_CHARS,
    _estimate_embed_size,
)
from app.shared.discord.embed_body import format_standard_field_name, format_standard_title
from app.shared.discord.embed_status_helpers import _chunk_status_blocks, _service_section, _split_long_text
from app.shared.discord.footer_status_pagination import FooterStatusPaginationView
from app.shared.discord.footer_status_renderer import build_footer_status_embeds, build_footer_status_pages, build_service_status_field


class _FooterDb:
    def __init__(self) -> None:
        self.settings: dict[str, str] = {}

    async def get_setting(self, key: str) -> str | None:
        return self.settings.get(key)

    async def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value

    async def fetchall(self, query: str, params: tuple[object, ...]) -> list[dict[str, str]]:
        prefix = str(params[0]).replace("%", "")
        rows = [{"key": key, "value": value} for key, value in sorted(self.settings.items()) if key.startswith(prefix)]
        return rows



def _build_footer_service() -> FooterService:
    return FooterService(_FooterDb())


async def _resolved_profile(service_name: str, contributors: list[str]) -> ServiceFooterProfile:
    return ServiceFooterProfile(
        service_name=service_name,
        contributors=contributors,
        used_local_processing=True,
        last_rendered_footer=None,
        updated_at=None,
        origins={"inference"},
    )


def test_footer_status_groups_campaign_sections_separately() -> None:
    assert _service_section("campagne_notizie") == 1
    assert _service_section("campagne_meteo") == 1
    assert _service_section("campagne_oroscopo") == 1
    assert _service_section("campagne_prompt") == 2
    assert _service_section("campagne_timer") == 3
    assert _service_section("audio_notes") == 0



def test_split_long_text_handles_very_long_line() -> None:
    text = "a" * 4500
    parts = _split_long_text(text, max_len=1900)
    assert len(parts) == 3
    assert all(len(part) <= 1900 for part in parts)



def test_chunk_status_blocks_handles_big_block_and_long_line() -> None:
    blocks = [
        "blocco breve",
        "riga1\n" + ("x" * 2200) + "\n" + ("y" * 2100),
        "blocco finale",
    ]
    chunks = _chunk_status_blocks(blocks, max_len=1900)
    assert chunks
    assert all(0 < len(chunk) <= 1900 for chunk in chunks)



def test_footer_status_overview_page_is_always_present_and_readable() -> None:
    async def _run() -> None:
        footer = _build_footer_service()
        await footer.set_enabled(True)
        await footer.set_global_phrase("Frase globale")
        await footer.set_global_thumbnail("https://example.com/thumb.png")
        await footer.register_known_service("audio_notes", source="startup")
        await footer.register_known_service("riassunto", source="db")
        await footer.set_service_phrase("riassunto", "Frase dedicata")

        snapshot = await footer.build_status_snapshot(
            inferred_profile_resolver=lambda service_name: _resolved_profile(
                service_name=service_name,
                contributors=["whisper", "argos"],
            )
        )

        pages = build_footer_status_pages(snapshot)
        overview = pages[0]

        assert overview.title == "FOOTER STATUS"
        assert "Stato e diagnostica del footer embed." in overview.description
        assert [field.name for field in overview.fields] == [
            format_standard_field_name("STATO", emoji="ℹ️"),
            format_standard_field_name("SERVIZI", emoji="📊"),
            format_standard_field_name("FAMIGLIE", emoji="📂"),
            format_standard_field_name("CONFIGURAZIONE", emoji="⚙️"),
        ]
        assert all("• " in field.value for field in overview.fields)
        assert "Navigazione" not in "\n".join(field.name for field in overview.fields)

    asyncio.run(_run())



def test_footer_status_service_blocks_are_compact_and_variant_aware() -> None:
    async def _run() -> None:
        footer = _build_footer_service()
        await footer.register_known_service("riassunto", source="startup")
        await footer.set_service_phrase("riassunto", "Footer dedicato")
        await footer.record_service_footer_variant(
            service_name="riassunto",
            contributors=["llama3.2"],
            used_local_processing=True,
            last_rendered_footer="Footer base compatto",
            origin="runtime",
        )
        await footer.record_service_footer_variant(
            service_name="riassunto",
            contributors=["gpt-4o-mini"],
            used_local_processing=False,
            last_rendered_footer="Footer remoto alternativo",
            origin="runtime",
        )

        snapshot = await footer.build_status_snapshot()
        entry = snapshot.services[0]
        field = build_service_status_field(entry, snapshot)

        assert field.name == format_standard_field_name("RIASSUNTO", emoji="🧾")
        assert "• Footer effettivo:" in field.value
        assert "• Sorgente: **service**" in field.value
        assert "Varianti: **2**" in field.value
        assert "local (1): riassunto|local|llama3.2" in field.value
        assert "remote (1): riassunto|remote|gpt-4o-mini" in field.value
        assert "• Diff: remote" in field.value
        assert "technical alias" not in field.value.lower()
        assert "label:" not in field.value.lower()
        assert "key:" not in field.value.lower()
        assert "origin:" not in field.value.lower()
        assert "updated:" not in field.value.lower()

    asyncio.run(_run())



def test_footer_status_groups_campaign_pages() -> None:
    async def _run() -> None:
        footer = _build_footer_service()
        for service_name in ("riassunto", "campagne_notizie", "campagne_prompt", "campagne_timer"):
            await footer.record_service_footer_variant(
                service_name=service_name,
                contributors=[f"{service_name}-model"],
                used_local_processing=service_name != "campagne_prompt",
                last_rendered_footer=f"Footer {service_name}",
                origin="runtime",
            )

        snapshot = await footer.build_status_snapshot()
        pages = build_footer_status_pages(snapshot)
        page_titles = [page.title for page in pages]

        assert "FOOTER STATUS" in page_titles
        assert "FOOTER STATUS · STANDARD SERVICES" in page_titles
        assert "FOOTER STATUS · EDITORIAL CAMPAIGNS" in page_titles
        assert "FOOTER STATUS · PROMPT CAMPAIGNS" in page_titles
        assert "FOOTER STATUS · TIMER CAMPAIGNS" in page_titles

    asyncio.run(_run())



def test_footer_status_builds_multiple_pages_when_services_are_many() -> None:
    async def _run() -> None:
        footer = _build_footer_service()
        for idx in range(40):
            await footer.record_service_footer_variant(
                service_name=f"service_{idx}",
                contributors=[f"model_{idx}", f"fallback_{idx}"],
                used_local_processing=idx % 2 == 0,
                last_rendered_footer=f"Footer render {idx} " + ("x" * 120),
                origin="runtime",
            )

        embeds = await build_footer_status_embeds(await footer.build_status_snapshot(), footer_service=footer)

        assert len(embeds) > 2
        assert embeds[0].title == format_standard_title("FOOTER STATUS", emoji="📦")
        assert embeds[0].description and "Stato e diagnostica del footer embed." in embeds[0].description
        assert any("FOOTER STATUS · STANDARD SERVICES" in (embed.title or "") for embed in embeds[1:])
        assert all("(1/" not in (embed.title or "") for embed in embeds)
        assert all("*" in (embed.description or "") for embed in embeds)
        assert all(embed.fields and embed.fields[0].name == format_standard_field_name("INFO", emoji="ℹ️") for embed in embeds)
        assert all("• Pagina: **" in (embed.fields[0].value or "") for embed in embeds)
        assert all("Pagina " not in (embed.footer.text or "") for embed in embeds)
        assert all((embed.author.name or "").startswith("servizio EMBED · (Pag. ") for embed in embeds)
        assert all("UNKNOWN" not in (embed.author.name or "") for embed in embeds)

    asyncio.run(_run())



def test_footer_status_renderer_keeps_each_embed_within_real_discord_limits() -> None:
    async def _run() -> None:
        footer = _build_footer_service()
        service_names = [
            "riassunto",
            "audio_notes",
            "campagne_notizie",
            "campagne_meteo",
            "campagne_oroscopo",
            "campagne_prompt",
            "campagne_timer",
            *[f"service_{idx}" for idx in range(48)],
        ]
        await footer.set_global_phrase("Frase globale molto leggibile")
        for idx, service_name in enumerate(service_names):
            await footer.record_service_footer_variant(
                service_name=service_name,
                contributors=[f"model_{idx}", f"fallback_{idx}", f"backup_{idx}"],
                used_local_processing=idx % 3 != 0,
                last_rendered_footer=(
                    f"Footer {service_name} • "
                    + " / ".join(f"source_{slot}_{idx}" for slot in range(8))
                    + " "
                    + ("x" * 240)
                ),
                origin="runtime",
            )

        embeds = await build_footer_status_embeds(await footer.build_status_snapshot(), footer_service=footer)

        assert embeds
        assert all(len(embed.title or "") <= DISCORD_MAX_EMBED_TITLE for embed in embeds)
        assert all(len(embed.description or "") <= DISCORD_MAX_EMBED_DESCRIPTION for embed in embeds)
        assert all(len(embed.fields) <= DISCORD_MAX_FIELDS for embed in embeds)
        assert all(_estimate_embed_size(embed) <= MAX_EMBED_CHARS for embed in embeds)
        assert all(len(field.value or "") <= DISCORD_MAX_FIELD_VALUE for embed in embeds for field in embed.fields)

    asyncio.run(_run())




def test_footer_status_renderer_source_has_no_manual_set_footer_call() -> None:
    source = Path("app/shared/discord/footer_status_renderer.py").read_text(encoding="utf-8")

    assert "set_footer(" not in source

def test_footer_status_pagination_view_navigates_and_disables_buttons_correctly() -> None:
    async def _run() -> None:
        embeds = [discord.Embed(title=f"Page {idx}") for idx in range(1, 4)]
        view = FooterStatusPaginationView(embeds)
        buttons = {button.label: button for button in view.children}

        assert buttons["INIZIO"].disabled is True
        assert buttons["INDIETRO"].disabled is True
        assert buttons["AVANTI"].disabled is False

        interaction = SimpleNamespace(response=SimpleNamespace(edit_message=AsyncMock()))

        await buttons["AVANTI"].callback(interaction)
        assert view.current_index == 1
        assert buttons["INIZIO"].disabled is False
        assert buttons["INDIETRO"].disabled is False
        interaction.response.edit_message.assert_awaited_with(embed=embeds[1], view=view)

        await buttons["AVANTI"].callback(interaction)
        assert view.current_index == 2
        assert buttons["AVANTI"].disabled is True

        await buttons["INDIETRO"].callback(interaction)
        assert view.current_index == 1
        assert buttons["AVANTI"].disabled is False

        await buttons["INIZIO"].callback(interaction)
        assert view.current_index == 0
        assert buttons["INIZIO"].disabled is True
        assert buttons["INDIETRO"].disabled is True

    asyncio.run(_run())



def test_footer_status_command_sends_single_embed_without_pagination_view() -> None:
    async def _run() -> None:
        footer = _build_footer_service()
        await footer.set_enabled(False)
        await footer.set_service_phrase("riassunto", "Footer riassunto")
        await footer.set_service_thumbnail("riassunto", "https://example.com/footer.png")

        ctx = SimpleNamespace(footer=footer, database=SimpleNamespace(), ai=None)
        embed_group = app_commands.Group(name="embed", description="embed")
        register_embed(embed_group, ctx)

        footer_group = next(command for command in embed_group.commands if command.name == "footer")
        status_command = next(command for command in footer_group.commands if command.name == "status")

        interaction = SimpleNamespace(
            response=SimpleNamespace(is_done=lambda: False, send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        from app.plugins.commands_modular import embed as embed_module

        original_check_permission = embed_module.check_permission
        embed_module.check_permission = AsyncMock(return_value=True)
        try:
            await status_command.callback(interaction)
        finally:
            embed_module.check_permission = original_check_permission

        kwargs = interaction.response.send_message.await_args.kwargs
        assert kwargs["ephemeral"] is True
        assert "embed" in kwargs
        assert "view" not in kwargs or kwargs.get("view") is None
        assert interaction.followup.send.await_count == 0
        embed = kwargs["embed"]
        assert embed.title and "FOOTER STATUS" in embed.title
        assert len(embed.fields) >= 3

        info_field = embed.fields[0]
        assert "INFO" in info_field.name
        info_text = info_field.value.lower()
        assert "enabled: **off**" in info_text
        assert "supported services: **10**" in info_text
        assert "services with custom template: **1**" in info_text
        assert "services using default: **9**" in info_text
        assert "runtime rule" in info_text

        custom_field = next(field for field in embed.fields if "CUSTOM TEMPLATES" in field.name)
        assert "riassunto" in custom_field.value.lower()
        assert "phrase, thumbnail" in custom_field.value.lower()

        default_field = next(field for field in embed.fields if "DEFAULT SERVICES" in field.name)
        assert "riassunto" not in default_field.value.lower()
        assert "audio" in default_field.value.lower()
        assert "triggers" in default_field.value.lower()

    asyncio.run(_run())
