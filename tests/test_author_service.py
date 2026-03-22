import asyncio

import discord

from app.services.author import (
    AuthorService,
    InvalidAuthorThumbnailError,
    attach_author_meta,
    copy_author_meta,
    get_author_meta,
    normalize_author_thumbnail,
)
from app.shared.discord.author_pipeline import finalize_embeds
from app.shared.discord.embed_limits import normalize_embeds_for_discord


class _FakeDatabase:
    def __init__(self) -> None:
        self.settings: dict[str, str] = {}

    async def get_setting(self, key: str) -> str | None:
        return self.settings.get(key)

    async def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value

    async def delete_setting(self, key: str) -> None:
        self.settings.pop(key, None)

    async def execute(self, _query: str, _params: tuple[str, ...]) -> None:
        return None

    async def fetchall(self, query: str, params: tuple[str, ...]):
        prefix = str(params[0]).replace('%', '') if params else ''
        if 'FROM settings' not in query:
            return []
        return [
            {'key': key, 'value': value}
            for key, value in sorted(self.settings.items())
            if not prefix or key.startswith(prefix)
        ]



def _build_author_service() -> tuple[AuthorService, _FakeDatabase]:
    database = _FakeDatabase()
    return AuthorService(database), database



def test_author_meta_roundtrip_and_copy() -> None:
    source = discord.Embed(title="source")
    target = discord.Embed(title="target")
    attach_author_meta(source, service_name="riassunto")

    copy_author_meta(source, target)

    meta = get_author_meta(target)
    assert meta is not None
    assert meta.service_name == "riassunto"



def test_author_service_apply_uses_service_fallback_without_thumbnail() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="x")
        attach_author_meta(embed, service_name="riassunto")
        service, _ = _build_author_service()

        await service.apply(embed, default_service_name="fallback")

        assert embed.author.name == "🗒️ Riassunto"
        assert embed.author.icon_url is None

    asyncio.run(_run())



def test_author_service_apply_uses_global_phrase_version_and_thumbnail() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="x")
        attach_author_meta(embed, service_name="status")
        service, _ = _build_author_service()
        await service.set_version("v2")
        await service.set_global_phrase("Centro embed")
        await service.set_global_thumbnail("<:melon:1475962151502876695>")

        await service.apply(embed, default_service_name="status")

        assert embed.author.name == "Centro embed · v2"
        assert embed.author.icon_url == "https://cdn.discordapp.com/emojis/1475962151502876695.png"

    asyncio.run(_run())



def test_author_service_service_override_beats_global_template() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="x")
        attach_author_meta(embed, service_name="riassunto")
        service, _ = _build_author_service()
        await service.set_version("2026.03")
        await service.set_global_phrase("Linea globale")
        await service.set_service_phrase("riassunto", "Linea dedicata")
        await service.set_global_thumbnail("https://example.com/global.png")
        await service.set_service_thumbnail("riassunto", "https://example.com/service.png")

        await service.apply(embed, default_service_name="riassunto")

        assert embed.author.name == "Linea dedicata · 2026.03"
        assert embed.author.icon_url == "https://example.com/service.png"

    asyncio.run(_run())



def test_author_pipeline_finalize_split_embeds_keeps_author_meta() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="Split me")
        embed.add_field(name="F1", value="x" * 4000, inline=False)
        embed.add_field(name="F2", value="y" * 4000, inline=False)
        attach_author_meta(embed, service_name="riassunto")

        normalized = normalize_embeds_for_discord([embed], max_chars=4500)
        assert len(normalized) >= 2

        service, _ = _build_author_service()
        await finalize_embeds(normalized, service, default_service_name="riassunto")

        author_names = [item.author.name for item in normalized]
        assert len(set(author_names)) == 1
        assert author_names[0] == "🗒️ Riassunto"

    asyncio.run(_run())



def test_normalize_author_thumbnail_supports_custom_emoji_and_rejects_invalid_value() -> None:
    assert normalize_author_thumbnail("<a:pulse:1475962151502876696>") == "https://cdn.discordapp.com/emojis/1475962151502876696.gif"
    try:
        normalize_author_thumbnail("bad-value")
    except InvalidAuthorThumbnailError:
        pass
    else:
        raise AssertionError("Expected InvalidAuthorThumbnailError")
