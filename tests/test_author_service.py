import asyncio

import discord

from app.services.author import (
    AuthorService,
    InvalidAuthorThumbnailError,
    attach_author_meta,
    attach_author_meta_to_all,
    copy_author_meta,
    get_author_meta,
    normalize_author_thumbnail,
)
from app.services.footer import FooterService, attach_footer_meta
from app.shared.discord.author_pipeline import finalize_embed_author, finalize_embeds_author
from app.shared.discord.delivery import _prepare_embeds_for_send
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
    attach_author_meta(source, service_name="riassunto", minimal=True, preserve_existing=True)

    copy_author_meta(source, target)

    meta = get_author_meta(target)
    assert meta is not None
    assert meta.service_name == "riassunto"
    assert meta.minimal is True
    assert meta.preserve_existing is True



def test_attach_author_meta_to_all_applies_consistent_meta() -> None:
    embeds = [discord.Embed(title=f"page {idx}") for idx in range(1, 4)]

    out = attach_author_meta_to_all(
        embeds,
        service_name="riassunto",
        author_icon_url="https://example.com/author.png",
        minimal=True,
    )

    assert out == embeds
    for embed in embeds:
        meta = get_author_meta(embed)
        assert meta is not None
        assert meta.service_name == "riassunto"
        assert meta.author_icon_url == "https://example.com/author.png"
        assert meta.minimal is True



def test_author_service_apply_uses_service_fallback_without_thumbnail() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="x")
        attach_author_meta(embed, service_name="riassunto")
        service, _ = _build_author_service()

        await service.apply(embed, default_service_name="fallback")

        assert embed.author.name == "servizio DM CHANNEL SUMMARY"
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



def test_author_service_can_be_disabled_without_applying_author() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="x")
        attach_author_meta(embed, service_name="riassunto")
        service, _ = _build_author_service()
        await service.set_enabled(False)

        await finalize_embed_author(embed, service, default_service_name="riassunto")

        assert embed.author.name is None

    asyncio.run(_run())



def test_author_service_preserves_hardcoded_author_when_only_footer_meta_exists() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="x")
        embed.set_author(name="🚪 INGRESSI & USCITE")
        attach_footer_meta(embed, service_name="member_flow_notifications", used_local_processing=True)
        service, _ = _build_author_service()
        await service.set_global_phrase("Centro embed")

        await finalize_embed_author(embed, service, default_service_name="member_flow_notifications")

        assert embed.author.name == "🚪 INGRESSI & USCITE"

    asyncio.run(_run())



def test_author_service_skip_meta_leaves_embed_without_author() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="x")
        attach_author_meta(embed, service_name="riassunto", skip=True)
        service, _ = _build_author_service()
        await service.set_global_phrase("Centro embed")

        await finalize_embed_author(embed, service, default_service_name="riassunto")

        assert embed.author.name is None

    asyncio.run(_run())



def test_author_service_minimal_meta_uses_service_fallback_name() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="x")
        attach_author_meta(embed, service_name="riassunto", minimal=True)
        service, _ = _build_author_service()
        await service.set_version("2026.03")
        await service.set_global_phrase("Centro embed")

        await finalize_embed_author(embed, service, default_service_name="riassunto")

        assert embed.author.name == "servizio DM CHANNEL SUMMARY"

    asyncio.run(_run())


def test_author_service_uses_canonical_top_level_metadata_when_present() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="x")
        attach_author_meta(embed, service_name="resoconto", canonical_top_level_command="serversummary")
        service, _ = _build_author_service()

        await finalize_embed_author(embed, service, default_service_name="resoconto")

        assert embed.author.name == "servizio SERVER SUMMARY"

    asyncio.run(_run())


def test_author_service_uses_canonical_alias_resolution_for_audionotes() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="x")
        attach_author_meta(embed, service_name="audio_notes", canonical_top_level_command="audionotes")
        service, _ = _build_author_service()

        await finalize_embed_author(embed, service, default_service_name="audio_notes")

        assert embed.author.name == "servizio AUDIO NOTES"

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
        await finalize_embeds_author(normalized, service, default_service_name="riassunto")

        author_names = [item.author.name for item in normalized]
        assert len(author_names) >= 2
        assert author_names[0] == f"servizio DM CHANNEL SUMMARY · (Pag. 1/{len(author_names)})"
        assert author_names[-1] == f"servizio DM CHANNEL SUMMARY · (Pag. {len(author_names)}/{len(author_names)})"

    asyncio.run(_run())



def test_prepare_embeds_for_send_applies_author_and_footer_together_on_all_pages() -> None:
    async def _run() -> None:
        embeds = [discord.Embed(title="Page 1"), discord.Embed(title="Page 2")]
        for embed in embeds:
            attach_author_meta(embed, service_name="riassunto")
            attach_footer_meta(embed, service_name="riassunto", contributors=["gpt-4o-mini"], used_local_processing=False)
        author_service, _ = _build_author_service()
        footer_service = FooterService(_FakeDatabase())

        prepared = await _prepare_embeds_for_send(
            embeds,
            footer_service=footer_service,
            author_service=author_service,
            default_service_name="riassunto",
        )

        assert [embed.author.name for embed in prepared] == ["servizio DM CHANNEL SUMMARY · (Pag. 1/2)", "servizio DM CHANNEL SUMMARY · (Pag. 2/2)"]
        assert all((embed.footer.text or "").startswith("Barcellometro") for embed in prepared)

    asyncio.run(_run())



def test_author_pipeline_service_and_global_thumbnail_precedence_and_fallback() -> None:
    async def _run() -> None:
        global_embed = discord.Embed(title="global")
        attach_author_meta(global_embed, service_name="status")
        service_embed = discord.Embed(title="service")
        attach_author_meta(service_embed, service_name="riassunto")
        fallback_embed = discord.Embed(title="fallback")
        attach_author_meta(fallback_embed, service_name="qna")
        service, _ = _build_author_service()
        await service.set_global_thumbnail("https://example.com/global.png")
        await service.set_service_thumbnail("riassunto", "https://example.com/service.png")

        await finalize_embeds_author([global_embed, service_embed, fallback_embed], service, default_service_name="status")

        assert global_embed.author.icon_url == "https://example.com/global.png"
        assert service_embed.author.icon_url == "https://example.com/service.png"
        assert fallback_embed.author.icon_url == "https://example.com/global.png"

    asyncio.run(_run())



def test_normalize_author_thumbnail_supports_custom_emoji_and_rejects_invalid_value() -> None:
    assert normalize_author_thumbnail("<a:pulse:1475962151502876696>") == "https://cdn.discordapp.com/emojis/1475962151502876696.gif"
    try:
        normalize_author_thumbnail("bad-value")
    except InvalidAuthorThumbnailError:
        pass
    else:
        raise AssertionError("Expected InvalidAuthorThumbnailError")


def test_author_service_supports_global_and_service_url() -> None:
    async def _run() -> None:
        global_embed = discord.Embed(title="global")
        attach_author_meta(global_embed, service_name="status")
        service_embed = discord.Embed(title="service")
        attach_author_meta(service_embed, service_name="riassunto")
        service, _ = _build_author_service()
        await service.set_global_url("https://example.com/global")
        await service.set_service_url("riassunto", "https://example.com/riassunto")

        await finalize_embeds_author([global_embed, service_embed], service, default_service_name="status")

        assert global_embed.author.url == "https://example.com/global"
        assert service_embed.author.url == "https://example.com/riassunto"

    asyncio.run(_run())
