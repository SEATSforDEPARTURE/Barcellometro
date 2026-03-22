import sys
import types
import asyncio
from pathlib import Path
from typing import Any

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

from app.shared.discord.embed_status_helpers import _chunk_status_blocks, _service_section, _split_long_text
from app.shared.discord.footer_status_renderer import build_footer_status_embeds, build_footer_status_pages
from app.services.footer import FooterService, ServiceFooterProfile


class _FooterDb:
    def __init__(self) -> None:
        self.settings: dict[str, str] = {}

    async def get_setting(self, key: str) -> str | None:
        return self.settings.get(key)

    async def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value

    async def fetchall(self, query: str, params: tuple[Any, ...]) -> list[dict[str, str]]:
        prefix = str(params[0]).replace("%", "")
        rows = [{"key": key, "value": value} for key, value in sorted(self.settings.items()) if key.startswith(prefix)]
        return rows


def _build_footer_service() -> FooterService:
    return FooterService(_FooterDb())


def test_footer_status_groups_campaign_sections_separately() -> None:
    assert _service_section("campagne_notizie") == 1
    assert _service_section("campagne_meteo") == 1
    assert _service_section("campagne_oroscopo") == 1
    assert _service_section("campagne_prompt") == 2
    assert _service_section("campagne_timer") == 3
    assert _service_section("audio_notes") == 0


def test_footer_status_source_uses_variants_and_excludes_legacy_campagne() -> None:
    command_source = Path("app/plugins/commands_modular/embed.py").read_text()
    renderer_source = Path("app/shared/discord/footer_status_renderer.py").read_text()
    assert "build_status_snapshot" in command_source
    assert "Editorial campaigns" in renderer_source
    assert "Prompt campaigns" in renderer_source
    assert "Timer campaigns" in renderer_source
    assert 'service_name="campagne"' not in command_source


def test_message_scheduler_uses_prompt_vs_timer_footer_service() -> None:
    source = Path("app/services/message_scheduler.py").read_text()
    assert "def _campaign_footer_service_name" in source
    assert 'return "campagne_prompt" if str(campaign_type or "").upper() == "AI_PROMPT" else "campagne_timer"' in source


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


def test_chunk_status_blocks_scales_with_many_services() -> None:
    blocks = [f"**service_{idx}**\nvariante: local | model\n→ footer" for idx in range(200)]
    chunks = _chunk_status_blocks(blocks, max_len=1900)
    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 1900 for chunk in chunks)


def test_footer_status_overview_page_is_always_present() -> None:
    async def _run() -> None:
        footer = _build_footer_service()
        await footer.set_enabled(True)
        await footer.set_global_phrase("Frase globale")
        await footer.register_known_service("audio_notes", source="startup")

        snapshot = await footer.build_status_snapshot(
            inferred_profile_resolver=lambda _service: _resolved_profile(
                service_name="audio_notes",
                contributors=["whisper", "argos"],
            )
        )

        pages = build_footer_status_pages(snapshot)
        embeds = await build_footer_status_embeds(snapshot)

        assert pages[0].title == "Overview"
        assert "OVERVIEW" in (embeds[0].description or "")
        assert "Known Services" in (embeds[0].description or "")
        assert "SERVICES WITHOUT PERSISTED VARIANTS" in "\n".join(embed.description or "" for embed in embeds)

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

        assert "Overview" in page_titles
        assert "Standard services" in page_titles
        assert "Editorial campaigns" in page_titles
        assert "Prompt campaigns" in page_titles
        assert "Timer campaigns" in page_titles

    asyncio.run(_run())


def test_footer_status_builds_multiple_pages_when_services_are_many() -> None:
    async def _run() -> None:
        footer = _build_footer_service()
        for idx in range(24):
            await footer.record_service_footer_variant(
                service_name=f"service_{idx}",
                contributors=[f"model_{idx}", f"fallback_{idx}"],
                used_local_processing=idx % 2 == 0,
                last_rendered_footer=f"Footer render {idx} " + ("x" * 80),
                origin="runtime",
            )

        snapshot = await footer.build_status_snapshot()
        embeds = await build_footer_status_embeds(snapshot)

        assert len(embeds) > 2
        assert "Page: **1/" in (embeds[0].description or "")
        assert all("admin footer status" not in (embed.description or "").lower() for embed in embeds)

    asyncio.run(_run())


async def _resolved_profile(service_name: str, contributors: list[str]) -> ServiceFooterProfile:
    return ServiceFooterProfile(
        service_name=service_name,
        contributors=contributors,
        used_local_processing=True,
        last_rendered_footer=None,
        updated_at=None,
        origins={"inference"},
    )
