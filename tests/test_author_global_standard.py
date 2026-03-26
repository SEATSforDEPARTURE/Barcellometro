from __future__ import annotations

import asyncio
import pathlib
import re

import discord

from app.services.author import attach_author_meta
from app.shared.discord.command_embeds import build_command_embed
from app.shared.discord.embed_rendering import finalize_embed_rendering, finalize_embeds_rendering
from app.shared.discord.report_embeds import apply_standard_report_style

VALID_PATTERN = re.compile(r"^servizio [A-Z]+( [A-Z]+)*( · \(Pag\. \d+/\d+\))?$")

INVALID_KEYWORDS = [
    "REPORT",
    "SUMMARY",
    "STATUS",
    "ACTIVITY",
    "USER",
    "DAILY",
]


def assert_author_is_standard(author: str | None) -> None:
    assert author is not None, "Author is missing"
    assert VALID_PATTERN.match(author), f"Invalid author format: {author}"

    for word in INVALID_KEYWORDS:
        assert f"servizio {word}" not in author, f"Invalid fallback author: {author}"


async def _finalize_single(embed: discord.Embed, *, default_service_name: str) -> discord.Embed:
    return await finalize_embed_rendering(
        embed,
        footer_service=None,
        author_service=None,
        default_service_name=default_service_name,
    )


async def _finalize_many(embeds: list[discord.Embed], *, default_service_name: str) -> list[discord.Embed]:
    return await finalize_embeds_rendering(
        embeds,
        footer_service=None,
        author_service=None,
        default_service_name=default_service_name,
    )


def test_author_pipeline_standard() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="test")
        attach_author_meta(embed, service_name="channelsummary", canonical_top_level_command="channelsummary")

        await _finalize_single(embed, default_service_name="channelsummary")

        assert_author_is_standard(embed.author.name)

    asyncio.run(_run())


def test_author_pagination() -> None:
    async def _run() -> None:
        embeds = [discord.Embed(title="p1"), discord.Embed(title="p2")]

        for embed in embeds:
            attach_author_meta(
                embed,
                service_name="channelsummary",
                canonical_top_level_command="channelsummary",
            )

        result = await _finalize_many(embeds, default_service_name="channelsummary")

        for embed in result:
            assert_author_is_standard(embed.author.name)
            assert "(Pag." in str(embed.author.name)

    asyncio.run(_run())


def test_command_embed_author() -> None:
    async def _run() -> None:
        embed = await build_command_embed(
            top_level="riassunto",
            subcommand_path="riassunto oggi",
            visual_top_level="channelsummary",
            footer_service=None,
        )
        await _finalize_single(embed, default_service_name="channelsummary")

        assert_author_is_standard(embed.author.name)

    asyncio.run(_run())


def test_no_hardcoded_set_author() -> None:
    root = pathlib.Path("app")
    safe_author_pipeline = pathlib.Path("app/shared/discord/author_pipeline.py")

    for path in root.rglob("*.py"):
        if path == safe_author_pipeline:
            continue
        text = path.read_text(encoding="utf-8")

        for match in re.finditer(r"set_author\((?P<args>[\s\S]*?)\)", text):
            args = match.group("args")
            if "name=" not in args:
                continue
            if "render_author_name" in args or "render_author_name_with_page" in args:
                continue
            if "attach_author_meta" in text:
                continue
            raise AssertionError(f"Hardcoded author in {path}")


def test_report_helpers_attach_author() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="report")

        apply_standard_report_style(
            [embed],
            service_name="riassunto",
            canonical_top_level_command="dmsummary",
        )

        await _finalize_single(embed, default_service_name="dmsummary")

        assert_author_is_standard(embed.author.name)

    asyncio.run(_run())


def test_alias_resolution() -> None:
    async def _run() -> None:
        embed = discord.Embed()

        attach_author_meta(
            embed,
            service_name="dmsummary",
            canonical_top_level_command="dmsummary",
        )

        await _finalize_single(embed, default_service_name="dmsummary")

        assert "DM SUMMARY" in str(embed.author.name)

    asyncio.run(_run())
