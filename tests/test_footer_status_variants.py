import sys
import types
import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock

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

from app.shared.discord.embed_status_helpers import _chunk_status_blocks, _service_section, _split_long_text
from app.shared.discord.embed_limits import (
    DISCORD_MAX_EMBED_DESCRIPTION,
    DISCORD_MAX_EMBED_TITLE,
    DISCORD_MAX_EMBED_TOTAL_CHARS,
    DISCORD_MAX_FIELD_VALUE,
    DISCORD_MAX_FIELDS,
    MAX_EMBED_CHARS,
    _estimate_embed_size,
    chunk_embeds_for_message_batches,
    normalize_embeds_for_discord,
)
from app.shared.discord.footer_status_renderer import build_footer_status_embeds, build_footer_status_pages
from app.shared.discord.command_embeds import send_command_embeds
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

        snapshot = await footer.build_status_snapshot()
        embeds = await build_footer_status_embeds(snapshot)

        assert embeds
        assert embeds[0].description and "OVERVIEW" in embeds[0].description
        assert all(len(embed.title or "") <= DISCORD_MAX_EMBED_TITLE for embed in embeds)
        assert all(len(embed.description or "") <= DISCORD_MAX_EMBED_DESCRIPTION for embed in embeds)
        assert all(len(embed.fields) <= DISCORD_MAX_FIELDS for embed in embeds)
        assert all(_estimate_embed_size(embed) <= MAX_EMBED_CHARS for embed in embeds)
        assert all(
            len(field.value or "") <= DISCORD_MAX_FIELD_VALUE
            for embed in embeds
            for field in embed.fields
        )

        batches = chunk_embeds_for_message_batches(embeds, max_total_chars=MAX_EMBED_CHARS)
        assert batches
        assert all(len(batch) <= 10 for batch in batches)
        assert all(sum(_estimate_embed_size(embed) for embed in batch) <= MAX_EMBED_CHARS for batch in batches)
        assert sum(len(batch) for batch in batches) == len(embeds)

    asyncio.run(_run())


def test_footer_status_regression_many_known_services_matches_runtime_shape() -> None:
    async def _run() -> None:
        footer = _build_footer_service()
        known_services = [
            "riassunto",
            "audio_notes",
            "campagne_notizie",
            "campagne_meteo",
            "campagne_oroscopo",
            "campagne_prompt",
            "campagne_timer",
            "barcello",
            "aura",
            "resoconto",
            "messaggi",
            "domanda",
        ]
        for service_name in known_services:
            await footer.register_known_service(service_name, source="startup")
        for idx in range(36):
            service_name = known_services[idx % len(known_services)]
            await footer.record_service_footer_variant(
                service_name=service_name if idx < len(known_services) else f"{service_name}_{idx}",
                contributors=[f"model_{idx}", f"fallback_{idx}"],
                used_local_processing=idx % 2 == 0,
                last_rendered_footer=f"Runtime footer {idx} " + ("known-service " * 30),
                origin="runtime",
            )

        snapshot = await footer.build_status_snapshot(
            inferred_profile_resolver=lambda service_name: _resolved_profile(
                service_name=service_name,
                contributors=[f"{service_name}-resolver", "aux"],
            )
        )
        embeds = await build_footer_status_embeds(snapshot)
        total_chars = sum(_estimate_embed_size(embed) for embed in embeds)

        assert len(embeds) > 1
        assert total_chars > DISCORD_MAX_EMBED_TOTAL_CHARS
        assert all(_estimate_embed_size(embed) <= MAX_EMBED_CHARS for embed in embeds)
        assert all("admin footer status" not in (embed.description or "").lower() for embed in embeds)

    asyncio.run(_run())


def test_send_command_embeds_batches_on_total_embed_characters_not_only_count() -> None:
    async def _run() -> None:
        interaction = types.SimpleNamespace()
        interaction.response = types.SimpleNamespace(
            is_done=Mock(return_value=False),
            send_message=AsyncMock(),
        )
        interaction.followup = types.SimpleNamespace(send=AsyncMock())

        embeds = [
            discord.Embed(title=f"Page {idx}", description=("A" * 2400))
            for idx in range(1, 5)
        ]

        await send_command_embeds(interaction, embeds=embeds, ephemeral=True)

        first_call = interaction.response.send_message.await_args.kwargs
        assert "embeds" in first_call
        assert len(first_call["embeds"]) < len(embeds)
        assert sum(_estimate_embed_size(embed) for embed in first_call["embeds"]) <= MAX_EMBED_CHARS
        assert interaction.followup.send.await_count >= 1
        for call in interaction.followup.send.await_args_list:
            sent_embeds = call.kwargs.get("embeds")
            sent_embed = call.kwargs.get("embed")
            batch = sent_embeds or ([sent_embed] if sent_embed is not None else [])
            assert batch
            assert sum(_estimate_embed_size(embed) for embed in batch) <= MAX_EMBED_CHARS

    asyncio.run(_run())


def test_normalize_embeds_for_discord_splits_description_and_fields_structurally() -> None:
    embed = discord.Embed(
        title="T" * 400,
        description="\n".join(f"linea {idx} " + ("x" * 180) for idx in range(80)),
    )
    for idx in range(30):
        embed.add_field(
            name=f"Campo {idx} " + ("n" * 300),
            value=" ".join(f"valore_{idx}_{slot}" for slot in range(220)),
            inline=False,
        )

    normalized = normalize_embeds_for_discord([embed], max_chars=MAX_EMBED_CHARS)

    assert len(normalized) > 1
    assert all(len(item.title or "") <= DISCORD_MAX_EMBED_TITLE for item in normalized)
    assert all(len(item.description or "") <= DISCORD_MAX_EMBED_DESCRIPTION for item in normalized)
    assert all(len(item.fields) <= DISCORD_MAX_FIELDS for item in normalized)
    assert all(_estimate_embed_size(item) <= MAX_EMBED_CHARS for item in normalized)
    assert all(
        len(field.value or "") <= DISCORD_MAX_FIELD_VALUE
        for item in normalized
        for field in item.fields
    )


async def _resolved_profile(service_name: str, contributors: list[str]) -> ServiceFooterProfile:
    return ServiceFooterProfile(
        service_name=service_name,
        contributors=contributors,
        used_local_processing=True,
        last_rendered_footer=None,
        updated_at=None,
        origins={"inference"},
    )
