import asyncio
import sys
import types

import discord

if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(Connection=object)

from app.services.footer import FooterService, attach_footer_meta, copy_footer_meta, get_footer_meta
from app.utils.footer_pipeline import finalize_embeds


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

        await service.apply(embed, default_service_name="fallback")

        assert embed.footer.text == "Barcellometro 1.0 · Dati elaborati con gpt-4o-mini e in loco"

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


def test_footer_meta_is_cleaned_up_after_apply() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="cleanup")
        attach_footer_meta(embed, service_name="barcello", contributors=["gpt-4o-mini"])
        service = _build_footer_service()

        assert get_footer_meta(embed) is not None
        await service.apply(embed)
        assert get_footer_meta(embed) is None

    asyncio.run(_run())
