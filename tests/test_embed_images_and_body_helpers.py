from __future__ import annotations

import asyncio

import discord

from app.services.embed_images import (
    EmbedImagesService,
    attach_embed_images_meta,
)
from app.shared.discord.embed_body import (
    BodyFormatOptions,
    apply_standard_body_helpers,
    format_standard_description,
    format_standard_field_name,
    format_standard_title,
)
from app.shared.discord.embed_rendering import finalize_embeds_rendering


class _FakeDatabase:
    def __init__(self) -> None:
        self.settings: dict[str, str] = {}

    async def get_setting(self, key: str) -> str | None:
        return self.settings.get(key)

    async def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value

    async def delete_setting(self, key: str) -> None:
        self.settings.pop(key, None)

    async def execute(self, _query: str, _params: tuple[str, ...] = ()) -> None:
        return None

    async def fetchall(self, query: str, params: tuple[str, ...] = ()):  # noqa: ANN202
        prefix = str(params[0]).replace('%', '') if params else ''
        if 'FROM settings' not in query:
            return []
        return [
            {'key': key, 'value': value}
            for key, value in sorted(self.settings.items())
            if not prefix or key.startswith(prefix)
        ]


def test_embed_images_global_toggle_and_templates_and_precedence() -> None:
    async def _run() -> None:
        service = EmbedImagesService(_FakeDatabase())
        await service.set_global_image("https://img.example/global.png")
        await service.set_global_thumbnail("https://img.example/global-thumb.png")
        await service.set_service_image("riassunto", "https://img.example/service.png")

        embed = discord.Embed(title="x")
        rendered = await finalize_embeds_rendering(
            [embed],
            footer_service=None,
            author_service=None,
            embed_images_service=service,
            default_service_name="riassunto",
        )
        assert rendered[0].image.url == "https://img.example/service.png"
        assert rendered[0].thumbnail.url == "https://img.example/global-thumb.png"

        runtime = discord.Embed(title="runtime")
        attach_embed_images_meta(
            runtime,
            service_name="riassunto",
            image_url="https://img.example/runtime.png",
        )
        rendered_runtime = await finalize_embeds_rendering(
            [runtime],
            footer_service=None,
            author_service=None,
            embed_images_service=service,
            default_service_name="riassunto",
        )
        assert rendered_runtime[0].image.url == "https://img.example/runtime.png"

        await service.set_enabled(False)
        rendered_off = await finalize_embeds_rendering(
            [runtime],
            footer_service=None,
            author_service=None,
            embed_images_service=service,
            default_service_name="riassunto",
        )
        assert rendered_off[0].image.url is None
        assert rendered_off[0].thumbnail.url is None

    asyncio.run(_run())


def test_embed_images_payload_rehydration_compatibility() -> None:
    async def _run() -> None:
        service = EmbedImagesService(_FakeDatabase())
        await service.set_global_image("https://img.example/global.png")
        source = discord.Embed(title="persisted")
        payload = source.to_dict()
        reloaded = discord.Embed.from_dict(payload)
        rendered = await finalize_embeds_rendering(
            [reloaded],
            footer_service=None,
            author_service=None,
            embed_images_service=service,
            default_service_name="status",
        )
        assert rendered[0].image.url == "https://img.example/global.png"

    asyncio.run(_run())


def test_body_helpers_formatters_and_limits() -> None:
    title = format_standard_title("qna", emoji="❓")
    assert title == "❓ __**QNA**__"

    description = format_standard_description("testo", italic=True, blank_line_before_fields=True)
    assert description == "*testo*\n\n"

    field_name = format_standard_field_name("Dettagli", emoji="📌")
    assert field_name == "📌 __**Dettagli**__"

    long_title = format_standard_title("x" * 400, emoji="✅")
    assert len(long_title) <= 256


def test_apply_standard_body_helpers_over_embed() -> None:
    embed = discord.Embed(title="status", description="linea")
    embed.add_field(name="campo", value="valore")
    apply_standard_body_helpers(
        embed,
        options=BodyFormatOptions(
            title_emoji="📦",
            title_uppercase=True,
            description_italic=True,
            blank_line_before_fields=True,
            format_field_names=True,
        ),
    )
    assert embed.title == "📦 __**STATUS**__"
    assert embed.description == "*linea*\n\n"
    assert embed.fields[0].name == "__**campo**__"
