import asyncio
import sys
import types

import discord

if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(Connection=object)

from app.services.footer import (
    FooterService,
    attach_footer_meta,
    attach_footer_meta_to_all,
    copy_footer_meta,
    get_footer_meta,
)
from app.shared.discord.embed_limits import normalize_embeds_for_discord
from app.shared.discord.footer_pipeline import finalize_embeds


class _FakeDatabase:
    def __init__(self) -> None:
        self.settings: dict[str, str] = {}

    async def get_setting(self, key: str) -> str | None:
        return self.settings.get(key)

    async def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value

    async def execute(self, _query: str, _params: tuple[str, ...]) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def fetchall(self, _query: str, _params: tuple[str, ...]):
        return []


def _build_footer_service() -> FooterService:
    return FooterService(_FakeDatabase())


def test_attach_footer_meta_non_crashing_with_discord_embed() -> None:
    embed = discord.Embed(title="test")
    attach_footer_meta(embed, service_name="barcello", used_local_processing=True)


def test_get_footer_meta_roundtrip() -> None:
    embed = discord.Embed(title="meta")
    attach_footer_meta(
        embed,
        service_name="barcello",
        contributors=["gpt-4o-mini", "gpt-4o-mini", " claude "],
        used_local_processing=True,
    )

    meta = get_footer_meta(embed)
    assert meta is not None
    assert meta.service_name == "barcello"
    assert meta.contributors == ["gpt-4o-mini", "claude"]
    assert meta.used_local_processing is True


def test_copy_footer_meta_copies_values_to_target() -> None:
    source = discord.Embed(title="source")
    target = discord.Embed(title="target")
    attach_footer_meta(source, service_name="riassunto", contributors=["gpt-4o-mini"], used_local_processing=False)

    copy_footer_meta(source, target)

    meta = get_footer_meta(target)
    assert meta is not None
    assert meta.service_name == "riassunto"
    assert meta.contributors == ["gpt-4o-mini"]
    assert meta.used_local_processing is False


def test_footer_service_apply_sets_footer_text() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="x")
        attach_footer_meta(embed, service_name="barcello", contributors=["gpt-4o-mini"], used_local_processing=True)
        service = _build_footer_service()
        await service.set_version("1.0")
        await service.set_global_phrase("In via di sviluppo.")

        await service.apply(embed, default_service_name="fallback")

        assert embed.footer.text == "Barcellometro 1.0 · In via di sviluppo. · Dati elaborati con gpt-4o-mini e fallback locale"

    asyncio.run(_run())


def test_finalize_embeds_multi_embed_does_not_crash() -> None:
    async def _run() -> None:
        embeds = [discord.Embed(title="one"), discord.Embed(title="two")]
        attach_footer_meta(embeds[0], service_name="riassunto", contributors=["gpt-4o-mini"])

        service = _build_footer_service()
        await finalize_embeds(embeds, service, default_service_name="unknown")

        assert embeds[0].footer and "Barcellometro" in (embeds[0].footer.text or "")
        assert embeds[1].footer and "Barcellometro" in (embeds[1].footer.text or "")

    asyncio.run(_run())


def test_normalize_embeds_for_discord_preserves_footer_meta_on_split_pages() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="Split me")
        embed.add_field(name="F1", value="x" * 4000, inline=False)
        embed.add_field(name="F2", value="y" * 4000, inline=False)
        attach_footer_meta(embed, service_name="riassunto", contributors=["gpt-4o"], used_local_processing=False)

        normalized = normalize_embeds_for_discord([embed], max_chars=4500)
        assert len(normalized) >= 2

        service = _build_footer_service()
        await service.set_version("dev6")
        await service.set_global_phrase("In via di sviluppo.")
        await finalize_embeds(normalized, service, default_service_name="riassunto")

        footer_texts = [item.footer.text for item in normalized]
        assert len(set(footer_texts)) == 1
        assert footer_texts[0] == "Barcellometro dev6 · In via di sviluppo. · Dati elaborati con gpt-4o"

    asyncio.run(_run())


def test_attach_footer_meta_to_all_applies_consistent_meta() -> None:
    embeds = [discord.Embed(title=f"page {idx}") for idx in range(1, 4)]

    out = attach_footer_meta_to_all(
        embeds,
        service_name="riassunto",
        contributors=["gpt-4o"],
        used_local_processing=False,
    )

    assert out == embeds
    for embed in embeds:
        meta = get_footer_meta(embed)
        assert meta is not None
        assert meta.service_name == "riassunto"
        assert meta.contributors == ["gpt-4o"]
        assert meta.used_local_processing is False


def test_finalize_embeds_multipage_riassunto_keeps_same_ai_footer_on_all_pages() -> None:
    async def _run() -> None:
        embeds = [discord.Embed(title=f"Dettagli {idx}") for idx in range(1, 4)]
        attach_footer_meta_to_all(
            embeds,
            service_name="riassunto",
            contributors=["gpt-4o"],
            used_local_processing=False,
        )
        service = _build_footer_service()
        await service.set_version("dev6")
        await service.set_global_phrase("In via di sviluppo.")

        await finalize_embeds(embeds, service, default_service_name="riassunto")

        footers = [embed.footer.text for embed in embeds]
        assert len(set(footers)) == 1
        assert footers[0] == "Barcellometro dev6 · In via di sviluppo. · Dati elaborati con gpt-4o"
        assert all("in loco" not in (text or "") for text in footers)

    asyncio.run(_run())


def test_footer_meta_is_cleaned_up_after_apply() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="cleanup")
        attach_footer_meta(embed, service_name="barcello", contributors=["gpt-4o-mini"])
        service = _build_footer_service()

        assert get_footer_meta(embed) is not None
        await service.apply(embed)
        assert get_footer_meta(embed) is None

    asyncio.run(_run())


def test_footer_service_tracks_multiple_variants_for_same_service() -> None:
    async def _run() -> None:
        service = _build_footer_service()
        await service.record_service_footer_profile(
            service_name="audio_notes",
            contributors=["small", "argos"],
            used_local_processing=True,
            last_rendered_footer="f1",
        )
        await service.record_service_footer_profile(
            service_name="audio_notes",
            contributors=["gpt-4o-transcribe", "gpt-4o-mini"],
            used_local_processing=False,
            last_rendered_footer="f2",
        )

        variants = await service.get_service_footer_variants("audio_notes")
        keys = sorted(variants.keys())
        assert keys == [
            "audio_notes|local|argos+small",
            "audio_notes|remote|gpt-4o-mini+gpt-4o-transcribe",
        ]

    asyncio.run(_run())


def test_unknown_service_is_not_persisted_or_returned_as_known() -> None:
    async def _run() -> None:
        service = _build_footer_service()
        await service.record_service_footer_profile(
            service_name="unknown",
            contributors=[],
            used_local_processing=True,
            last_rendered_footer="fallback",
        )
        embed = discord.Embed(title="x")
        await service.apply(embed, default_service_name="unknown")

        assert await service.get_known_services() == []
        assert await service.get_service_footer_profile("unknown") is None
        assert await service.get_service_footer_variants("unknown") == {}

    asyncio.run(_run())


def test_footer_service_render_footer_mixed_ai_and_local_fallback() -> None:
    async def _run() -> None:
        service = _build_footer_service()
        await service.set_version("dev6")
        await service.set_global_phrase("In via di sviluppo.")
        footer, _ = await service.render_footer(
            service_name="riassunto",
            contributors=["qwen2.5"],
            used_local_processing=True,
        )
        assert footer == "Barcellometro dev6 · In via di sviluppo. · Dati elaborati con qwen2.5 e fallback locale"

    asyncio.run(_run())


def test_footer_service_render_footer_orders_version_phrase_then_processing() -> None:
    async def _run() -> None:
        service = _build_footer_service()
        await service.set_version("dev7.1")
        await service.set_global_phrase("Sempre acceso.")

        footer, phrase = await service.render_footer(
            service_name="status",
            contributors=["llama3.2"],
            used_local_processing=False,
        )

        assert phrase == "Sempre acceso."
        assert footer == "Barcellometro dev7.1 · Sempre acceso. · Dati elaborati con llama3.2"

    asyncio.run(_run())


def test_footer_service_render_footer_skips_missing_phrase_without_double_separator() -> None:
    async def _run() -> None:
        service = _build_footer_service()
        await service.set_version("dev7.1")

        footer, phrase = await service.render_footer(
            service_name="status",
            contributors=[],
            used_local_processing=True,
        )

        assert phrase is None
        assert footer == "Barcellometro dev7.1"
        assert "Dati elaborati con" not in footer
        assert "Dati elaborati" + " in loco" not in footer
        assert " ·  · " not in footer

    asyncio.run(_run())


def test_footer_service_render_footer_with_phrase_and_no_contributors_skips_processing_segment() -> None:
    async def _run() -> None:
        service = _build_footer_service()
        await service.set_version("dev8")
        await service.set_global_phrase("In via di sviluppo.")

        footer, phrase = await service.render_footer(
            service_name="status",
            contributors=[],
            used_local_processing=True,
        )

        assert phrase == "In via di sviluppo."
        assert footer == "Barcellometro dev8 · In via di sviluppo."
        assert "Dati elaborati con" not in footer
        assert "Dati elaborati" + " in loco" not in footer
        assert " ·  · " not in footer

    asyncio.run(_run())


def test_footer_service_render_footer_shows_processing_only_when_contributors_exist() -> None:
    async def _run() -> None:
        service = _build_footer_service()
        await service.set_version("dev8")

        with_contributors, _ = await service.render_footer(
            service_name="status",
            contributors=["llama3.2"],
            used_local_processing=False,
        )
        without_contributors, _ = await service.render_footer(
            service_name="status",
            contributors=[],
            used_local_processing=False,
        )

        assert with_contributors == "Barcellometro dev8 · Dati elaborati con llama3.2"
        assert without_contributors == "Barcellometro dev8"
        assert "Dati elaborati con llama3.2" in with_contributors
        assert "Dati elaborati con" not in without_contributors
        assert "Dati elaborati" + " in loco" not in without_contributors

    asyncio.run(_run())
