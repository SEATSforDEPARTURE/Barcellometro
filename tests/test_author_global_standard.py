from __future__ import annotations

import asyncio
import ast
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
    safe_author_files = {
        pathlib.Path("app/shared/discord/author_pipeline.py"),
        pathlib.Path("app/services/author.py"),
    }
    allowed_renderers = {"render_author_name", "render_author_name_with_page"}
    allowed_wrapper_calls = {"_truncate_text"}
    violations: list[str] = []

    def _callable_name(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def _is_author_name_attr(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "name"
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "author"
        )

    def _is_allowed_name_source(node: ast.AST) -> bool:
        if _is_author_name_attr(node):
            return True

        if isinstance(node, ast.IfExp):
            return _is_allowed_name_source(node.body) and _is_allowed_name_source(node.orelse)

        if isinstance(node, ast.Call):
            called_name = _callable_name(node.func)
            if called_name in allowed_renderers:
                return True
            if called_name in allowed_wrapper_calls and node.args:
                return _is_allowed_name_source(node.args[0])

        return False

    for path in root.rglob("*.py"):
        if path in safe_author_files:
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr != "set_author":
                continue

            name_expr = None
            if node.args:
                name_expr = node.args[0]
            for kw in node.keywords:
                if kw.arg == "name":
                    name_expr = kw.value
                    break

            if name_expr is None:
                continue
            if _is_allowed_name_source(name_expr):
                continue

            rendered_expr = ast.get_source_segment(source, name_expr) or ast.dump(name_expr, include_attributes=False)
            violations.append(
                f"{path}:{node.lineno} set_author(name=...) non canonico: {rendered_expr!r}. "
                "Usa render_author_name* o clona embed.author.name."
            )

    assert not violations, "Bypass AUTHOR standard rilevati:\n- " + "\n- ".join(violations)


def test_report_helpers_attach_author() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="report")

        apply_standard_report_style(
            [embed],
            service_name="riassunto",
            canonical_top_level_command="dmchannelsummary",
        )

        await _finalize_single(embed, default_service_name="dmchannelsummary")

        assert_author_is_standard(embed.author.name)

    asyncio.run(_run())


def test_alias_resolution() -> None:
    async def _run() -> None:
        embed = discord.Embed()

        attach_author_meta(
            embed,
            service_name="dmchannelsummary",
            canonical_top_level_command="dmchannelsummary",
        )

        await _finalize_single(embed, default_service_name="dmchannelsummary")

        assert "DM CHANNEL SUMMARY" in str(embed.author.name)

    asyncio.run(_run())


def test_author_sensitive_sources_do_not_reference_legacy_summary_labels_or_roots() -> None:
    banned_tokens = (
        "DM SUMMARY",
        "dmsummary",
        "AURA SUMMARY",
        "aurasummary",
        "ACTIVITY SUMMARY",
        "activitysummary",
        "BARCELLO SUMMARY",
        "barcellosummary",
    )
    sensitive_files = (
        pathlib.Path("app/services/author.py"),
        pathlib.Path("app/shared/discord/author_pipeline.py"),
        pathlib.Path("app/shared/discord/embed_rendering.py"),
        pathlib.Path("app/shared/discord/delivery.py"),
        pathlib.Path("tests/test_author_service.py"),
        pathlib.Path("tests/test_embed_rendering.py"),
    )

    for path in sensitive_files:
        source = path.read_text(encoding="utf-8")
        for token in banned_tokens:
            assert token not in source, f"Legacy token {token!r} found in {path}"
