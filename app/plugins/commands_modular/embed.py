from __future__ import annotations

import discord
from discord import app_commands
from typing import Literal

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.shared.discord.command_embeds import CommandEmbedSection, send_standard_response
from app.services.embed_images import InvalidEmbedImageUrlError
from app.services.author import InvalidAuthorThumbnailError, render_author_name
from app.services.description_template_service import InvalidDescriptionTemplateError
from app.services.embed_public_service_keys import list_embed_service_aliases, list_public_embed_service_keys
from app.services.embed_template_service_catalog import (
    build_embed_template_service_autocomplete_choices,
    resolve_embed_template_public_service,
)
from app.services.embed_status_placeholders import format_placeholder_status_lines
from app.services.footer import InvalidFooterThumbnailError


def _author_service(ctx: CommandContext):
    return getattr(ctx, "author", None)


async def _send_embed_response(
    interaction: discord.Interaction,
    ctx: CommandContext,
    *,
    subcommand_path: str,
    subtitle_args: list[object] | None = None,
    lines: list[tuple[str, object]] | None = None,
    sections: list[CommandEmbedSection] | None = None,
    kind: str = "info",
) -> None:
    await send_standard_response(
        interaction,
        top_level="embed",
        subcommand_path=subcommand_path,
        subtitle_args=subtitle_args,
        lines=lines,
        sections=sections,
        kind=kind,
        footer_service=ctx.footer,
        author_service=_author_service(ctx),
        embed_images_service=getattr(ctx, "embed_images", None),
        footer_service_name="status",
        description_template_service=getattr(ctx, "description_template", None),
        ephemeral=True,
    )


def _template_section(*entries: tuple[str, object]) -> list[CommandEmbedSection]:
    rendered = [(label, value) for label, value in entries if value is not None]
    if not rendered:
        return []
    return [CommandEmbedSection(title="Template", lines=rendered)]


def _next_step_section(command: str) -> list[CommandEmbedSection]:
    return [CommandEmbedSection(title="Next Step", lines=[("Command", command)])]


def _clean_opt(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _format_value(value: str | None) -> str:
    return value if value else "(not set)"


def _format_override_value(value: str | None, *, missing: str) -> str:
    return value if value else missing


def _normalize_template_service_key(value: str) -> str | None:
    return resolve_embed_template_public_service(_clean_opt(value))


def _resolve_public_service_value(values: dict[str, str], public_service_key: str) -> str | None:
    for alias in list_embed_service_aliases(public_service_key):
        found = values.get(alias)
        if found is not None:
            return found
    return None


def _service_has_any_override(public_service_key: str, *override_maps: dict[str, str]) -> bool:
    for alias in list_embed_service_aliases(public_service_key):
        for values in override_maps:
            value = values.get(alias)
            if value is not None and str(value).strip():
                return True
    return False


def _build_status_service_buckets(
    supported_services: list[str],
    *,
    has_override,
) -> tuple[list[str], list[str]]:
    custom_services = sorted([service for service in supported_services if has_override(service)])
    default_services = [service for service in supported_services if service not in custom_services]
    return custom_services, default_services


def _placeholder_section(system: Literal["author", "footer", "description"]) -> CommandEmbedSection:
    lines = format_placeholder_status_lines(system)
    return CommandEmbedSection(
        title="PLACEHOLDERS",
        lines=lines if lines else [("none", "Nessun placeholder supportato")],
    )


def _description_preview_context(*, service_name: str, user_name: str = "Mario") -> dict[str, object]:
    return {
        "user_name": user_name,
        "service_name": service_name,
        "ordinal_today": "secondo",
        "audio_intro": "Leggiamo cosa ci dice",
        "is_first_today": False,
        "count_today": 2,
    }


def _truncate_preview(value: str, *, limit: int = 80) -> str:
    cleaned = (value or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1].rstrip()}…"


def register_embed(embed_group: app_commands.Group, ctx: CommandContext) -> None:
    async def _autocomplete_embed_template_service(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        del interaction
        return await build_embed_template_service_autocomplete_choices(ctx, current)

    footer_group = app_commands.Group(name="footer", description="Footer controls")
    embed_group.add_command(footer_group)

    @footer_group.command(name="on", description="Enable footer rendering.")
    async def footer_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.footer.on", ctx):
            return
        if ctx.footer is None:
            await _send_embed_response(
                interaction,
                ctx,
                subcommand_path="footer on",
                lines=[("reason", "Footer service is unavailable")],
                kind="error",
            )
            return
        await ctx.footer.set_enabled(True)
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="footer on",
            lines=[("result", "enabled")],
            kind="success",
        )

    @footer_group.command(name="off", description="Disable footer rendering.")
    async def footer_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.footer.off", ctx):
            return
        if ctx.footer is None:
            await _send_embed_response(
                interaction,
                ctx,
                subcommand_path="footer off",
                lines=[("reason", "Footer service is unavailable")],
                kind="error",
            )
            return
        await ctx.footer.set_enabled(False)
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="footer off",
            lines=[("result", "disabled")],
            kind="success",
        )

    @footer_group.command(name="template_global_set", description="Set the global footer template.")
    @app_commands.describe(version="Optional footer brand version.", phrase="Optional global footer phrase.", thumbnail="Optional footer thumbnail: Discord custom emoji or http/https image URL.")
    async def footer_template_global_set_command(
        interaction: discord.Interaction,
        version: str | None = None,
        phrase: str | None = None,
        thumbnail: str | None = None,
    ) -> None:
        if not await check_permission(interaction, "admin.footer.template_global_set", ctx):
            return
        if ctx.footer is None:
            await _send_embed_response(
                interaction,
                ctx,
                subcommand_path="footer template_global_set",
                lines=[("reason", "Footer service is unavailable")],
                kind="error",
            )
            return
        if version is None and phrase is None and thumbnail is None:
            await _send_embed_response(
                interaction,
                ctx,
                subcommand_path="footer template_global_set",
                lines=[("reason", "No changes provided")],
                sections=_next_step_section("/embed footer template_global_show"),
                kind="warning",
            )
            return
        if version is not None:
            await ctx.footer.set_version(_clean_opt(version))
        if phrase is not None:
            await ctx.footer.set_global_phrase(_clean_opt(phrase))
        if thumbnail is not None:
            try:
                await ctx.footer.set_global_thumbnail(_clean_opt(thumbnail))
            except InvalidFooterThumbnailError as exc:
                await _send_embed_response(
                    interaction,
                    ctx,
                    subcommand_path="footer template_global_set",
                    lines=[("reason", str(exc))],
                    kind="error",
                )
                return
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="footer template_global_set",
            lines=[("result", "updated")],
            sections=_template_section(
                ("Version", _format_value(await ctx.footer.get_version())),
                ("Phrase", _format_value(await ctx.footer.get_global_phrase())),
                ("Thumbnail", _format_value(await ctx.footer.get_global_thumbnail())),
            ),
            kind="success",
        )

    @footer_group.command(name="template_global_show", description="Show the global footer template.")
    async def footer_template_global_show_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.footer.template_global_show", ctx):
            return
        if ctx.footer is None:
            await _send_embed_response(
                interaction,
                ctx,
                subcommand_path="footer template_global_show",
                lines=[("reason", "Footer service is unavailable")],
                kind="error",
            )
            return
        current_version = await ctx.footer.get_version()
        current_global = await ctx.footer.get_global_phrase()
        current_thumbnail = await ctx.footer.get_global_thumbnail()
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="footer template_global_show",
            sections=_template_section(
                ("Version", _format_override_value(current_version, missing="(not set)")),
                ("Phrase", _format_override_value(current_global, missing="(not set)")),
                ("Thumbnail", _format_override_value(current_thumbnail, missing="(not set)")),
            ),
        )

    @footer_group.command(name="template_global_reset", description="Reset the global footer template.")
    async def footer_template_global_reset_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.footer.template_global_reset", ctx):
            return
        if ctx.footer is None:
            await _send_embed_response(
                interaction,
                ctx,
                subcommand_path="footer template_global_reset",
                lines=[("reason", "Footer service is unavailable")],
                kind="error",
            )
            return
        await ctx.footer.set_version(None)
        await ctx.footer.set_global_phrase(None)
        await ctx.footer.set_global_thumbnail(None)
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="footer template_global_reset",
            lines=[("result", "reset")],
            kind="success",
        )

    @footer_group.command(name="template_service_set", description="Set a service-specific footer template.")
    @app_commands.describe(service="Service name.", phrase="Optional service-specific footer phrase.", thumbnail="Optional footer thumbnail: Discord custom emoji or http/https image URL.")
    @app_commands.autocomplete(service=_autocomplete_embed_template_service)
    async def footer_template_service_set_command(
        interaction: discord.Interaction,
        service: str,
        phrase: str | None = None,
        thumbnail: str | None = None,
    ) -> None:
        if not await check_permission(interaction, "admin.footer.template_service_set", ctx):
            return
        if ctx.footer is None:
            await _send_embed_response(
                interaction,
                ctx,
                subcommand_path="footer template_service_set",
                lines=[("reason", "Footer service is unavailable")],
                kind="error",
            )
            return
        service_name = _normalize_template_service_key(service)
        if service_name is None:
            await _send_embed_response(
                interaction,
                ctx,
                subcommand_path="footer template_service_set",
                lines=[("reason", "Provide a valid service name")],
                kind="error",
            )
            return
        if phrase is None and thumbnail is None:
            await _send_embed_response(
                interaction,
                ctx,
                subcommand_path="footer template_service_set",
                subtitle_args=[service_name],
                lines=[("reason", "No changes provided")],
                kind="warning",
            )
            return
        if phrase is not None:
            await ctx.footer.set_service_phrase(service_name, _clean_opt(phrase))
        if thumbnail is not None:
            try:
                await ctx.footer.set_service_thumbnail(service_name, _clean_opt(thumbnail))
            except InvalidFooterThumbnailError as exc:
                await _send_embed_response(
                    interaction,
                    ctx,
                    subcommand_path="footer template_service_set",
                    subtitle_args=[service_name],
                    lines=[("reason", str(exc))],
                    kind="error",
                )
                return
        service_thumbnail = _resolve_public_service_value(await ctx.footer.get_service_thumbnails(), service_name)
        service_phrase = _resolve_public_service_value(await ctx.footer.get_service_phrases(), service_name)
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="footer template_service_set",
            subtitle_args=[service_name],
            lines=[("result", "updated")],
            sections=_template_section(
                ("Phrase", _format_value(service_phrase)),
                ("Thumbnail", _format_value(service_thumbnail)),
            ),
            kind="success",
        )

    @footer_group.command(name="template_service_show", description="Show a service-specific footer template.")
    @app_commands.describe(service="Service name.")
    @app_commands.autocomplete(service=_autocomplete_embed_template_service)
    async def footer_template_service_show_command(interaction: discord.Interaction, service: str) -> None:
        if not await check_permission(interaction, "admin.footer.template_service_show", ctx):
            return
        if ctx.footer is None:
            await _send_embed_response(
                interaction,
                ctx,
                subcommand_path="footer template_service_show",
                lines=[("reason", "Footer service is unavailable")],
                kind="error",
            )
            return
        service_name = _normalize_template_service_key(service)
        if service_name is None:
            await _send_embed_response(
                interaction,
                ctx,
                subcommand_path="footer template_service_show",
                lines=[("reason", "Provide a valid service name")],
                kind="error",
            )
            return
        phrase = _resolve_public_service_value(await ctx.footer.get_service_phrases(), service_name)
        thumbnail_value = _resolve_public_service_value(await ctx.footer.get_service_thumbnails(), service_name)
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="footer template_service_show",
            subtitle_args=[service_name],
            sections=[
                *_template_section(
                    ("Phrase", _format_override_value(phrase, missing="(not set)")),
                    ("Thumbnail", _format_override_value(thumbnail_value, missing="(not set)")),
                ),
                _placeholder_section("footer"),
            ],
        )

    @footer_group.command(name="template_service_reset", description="Reset a service-specific footer template.")
    @app_commands.describe(service="Service name.")
    @app_commands.autocomplete(service=_autocomplete_embed_template_service)
    async def footer_template_service_reset_command(interaction: discord.Interaction, service: str) -> None:
        if not await check_permission(interaction, "admin.footer.template_service_reset", ctx):
            return
        if ctx.footer is None:
            await _send_embed_response(
                interaction,
                ctx,
                subcommand_path="footer template_service_reset",
                lines=[("reason", "Footer service is unavailable")],
                kind="error",
            )
            return
        service_name = _normalize_template_service_key(service)
        if service_name is None:
            await _send_embed_response(
                interaction,
                ctx,
                subcommand_path="footer template_service_reset",
                lines=[("reason", "Provide a valid service name")],
                kind="error",
            )
            return
        for alias in list_embed_service_aliases(service_name):
            await ctx.footer.set_service_phrase(alias, None)
            await ctx.footer.set_service_thumbnail(alias, None)
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="footer template_service_reset",
            subtitle_args=[service_name],
            lines=[("result", "reset")],
            kind="success",
        )

    @footer_group.command(name="status", description="Show footer status and rendered variants.")
    async def footer_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.footer.status", ctx):
            return
        if ctx.footer is None:
            await _send_embed_response(
                interaction,
                ctx,
                subcommand_path="footer status",
                lines=[("reason", "Footer service is unavailable")],
                kind="error",
            )
            return

        supported_services = list_public_embed_service_keys()
        enabled = await ctx.footer.is_enabled()
        service_phrases = await ctx.footer.get_service_phrases()
        service_thumbnails = await ctx.footer.get_service_thumbnails()
        custom_services, default_services = _build_status_service_buckets(
            supported_services,
            has_override=lambda service: _service_has_any_override(service, service_phrases, service_thumbnails),
        )
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="footer status",
            lines=[
                ("enabled", "on" if enabled else "off"),
                ("supported services", len(supported_services)),
                ("services with custom template", len(custom_services)),
                ("services using default", len(default_services)),
                (
                    "runtime rule",
                    (
                        "OFF = runtime always uses standard default footer even if custom is saved"
                        if not enabled
                        else "ON = runtime uses service custom footer when configured; otherwise standard default"
                    ),
                ),
            ],
            sections=[
                CommandEmbedSection(
                    title="Custom Templates",
                    lines=(
                        [
                            (
                                service,
                                ", ".join(
                                    token
                                    for token, value in (
                                        ("phrase", _resolve_public_service_value(service_phrases, service)),
                                        ("thumbnail", _resolve_public_service_value(service_thumbnails, service)),
                                    )
                                    if value
                                ),
                            )
                            for service in custom_services
                        ]
                        if custom_services
                        else [("services", "(none)")]
                    ),
                ),
                CommandEmbedSection(
                    title="Default Services",
                    lines=[("services", ", ".join(default_services) if default_services else "(none)")],
                ),
                _placeholder_section("footer"),
            ],
        )

    author_group = app_commands.Group(name="author", description="Author controls")
    embed_group.add_command(author_group)

    @author_group.command(name="on", description="Enable author rendering.")
    async def author_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.author.on", ctx):
            return
        if _author_service(ctx) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author on", lines=[("reason", "Author service is unavailable")], kind="error")
            return
        await _author_service(ctx).set_enabled(True)
        await _send_embed_response(interaction, ctx, subcommand_path="author on", lines=[("result", "enabled")], kind="success")

    @author_group.command(name="off", description="Disable author rendering.")
    async def author_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.author.off", ctx):
            return
        if _author_service(ctx) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author off", lines=[("reason", "Author service is unavailable")], kind="error")
            return
        await _author_service(ctx).set_enabled(False)
        await _send_embed_response(interaction, ctx, subcommand_path="author off", lines=[("result", "disabled")], kind="success")

    @author_group.command(name="template_global_set", description="Set the global author template.")
    @app_commands.describe(version="Optional author template version suffix.", phrase="Optional global author phrase.", thumbnail="Optional author thumbnail: Discord custom emoji or http/https image URL.", url="Optional global author URL.")
    async def author_template_global_set_command(
        interaction: discord.Interaction,
        version: str | None = None,
        phrase: str | None = None,
        thumbnail: str | None = None,
        url: str | None = None,
    ) -> None:
        if not await check_permission(interaction, "admin.author.template_global_set", ctx):
            return
        if _author_service(ctx) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_global_set", lines=[("reason", "Author service is unavailable")], kind="error")
            return
        if version is None and phrase is None and thumbnail is None and url is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_global_set", lines=[("reason", "No changes provided")], sections=_next_step_section("/embed author template_global_show"), kind="warning")
            return
        if version is not None:
            await _author_service(ctx).set_version(_clean_opt(version))
        if phrase is not None:
            await _author_service(ctx).set_global_phrase(_clean_opt(phrase))
        if thumbnail is not None:
            try:
                await _author_service(ctx).set_global_thumbnail(_clean_opt(thumbnail))
            except InvalidAuthorThumbnailError as exc:
                await _send_embed_response(interaction, ctx, subcommand_path="author template_global_set", lines=[("reason", str(exc))], kind="error")
                return
        if url is not None:
            await _author_service(ctx).set_global_url(_clean_opt(url))
        preview = render_author_name(
            service_name="status",
            phrase=await _author_service(ctx).get_global_phrase(),
            version=await _author_service(ctx).get_version(),
        )
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="author template_global_set",
            lines=[("result", "updated")],
            sections=_template_section(
                ("Version", _format_value(await _author_service(ctx).get_version())),
                ("Phrase", _format_value(await _author_service(ctx).get_global_phrase())),
                ("Thumbnail", _format_value(await _author_service(ctx).get_global_thumbnail())),
                ("URL", _format_value(await _author_service(ctx).get_global_url())),
                ("Preview", preview),
            ),
            kind="success",
        )

    @author_group.command(name="template_global_show", description="Show the global author template.")
    async def author_template_global_show_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.author.template_global_show", ctx):
            return
        if _author_service(ctx) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_global_show", lines=[("reason", "Author service is unavailable")], kind="error")
            return
        current_version = await _author_service(ctx).get_version()
        current_global = await _author_service(ctx).get_global_phrase()
        current_thumbnail = await _author_service(ctx).get_global_thumbnail()
        current_url = await _author_service(ctx).get_global_url()
        preview = render_author_name(service_name="status", phrase=current_global, version=current_version)
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="author template_global_show",
            sections=_template_section(
                ("Version", _format_override_value(current_version, missing="(not set)")),
                ("Phrase", _format_override_value(current_global, missing="(not set)")),
                ("Thumbnail", _format_override_value(current_thumbnail, missing="(not set)")),
                ("URL", _format_override_value(current_url, missing="(not set)")),
                ("Preview", preview),
            ),
        )

    @author_group.command(name="template_global_reset", description="Reset the global author template.")
    async def author_template_global_reset_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.author.template_global_reset", ctx):
            return
        if _author_service(ctx) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_global_reset", lines=[("reason", "Author service is unavailable")], kind="error")
            return
        await _author_service(ctx).set_version(None)
        await _author_service(ctx).set_global_phrase(None)
        await _author_service(ctx).set_global_thumbnail(None)
        await _author_service(ctx).set_global_url(None)
        await _send_embed_response(interaction, ctx, subcommand_path="author template_global_reset", lines=[("result", "reset")], kind="success")

    @author_group.command(name="template_service_set", description="Set a service-specific author template.")
    @app_commands.describe(service="Service name.", phrase="Optional service-specific author phrase.", thumbnail="Optional author thumbnail: Discord custom emoji or http/https image URL.", url="Optional service-specific author URL.")
    @app_commands.autocomplete(service=_autocomplete_embed_template_service)
    async def author_template_service_set_command(
        interaction: discord.Interaction,
        service: str,
        phrase: str | None = None,
        thumbnail: str | None = None,
        url: str | None = None,
    ) -> None:
        if not await check_permission(interaction, "admin.author.template_service_set", ctx):
            return
        if _author_service(ctx) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_service_set", lines=[("reason", "Author service is unavailable")], kind="error")
            return
        service_name = _normalize_template_service_key(service)
        if service_name is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_service_set", lines=[("reason", "Provide a valid service name")], kind="error")
            return
        if phrase is None and thumbnail is None and url is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_service_set", subtitle_args=[service_name], lines=[("reason", "No changes provided")], kind="warning")
            return
        if phrase is not None:
            await _author_service(ctx).set_service_phrase(service_name, _clean_opt(phrase))
        if thumbnail is not None:
            try:
                await _author_service(ctx).set_service_thumbnail(service_name, _clean_opt(thumbnail))
            except InvalidAuthorThumbnailError as exc:
                await _send_embed_response(interaction, ctx, subcommand_path="author template_service_set", subtitle_args=[service_name], lines=[("reason", str(exc))], kind="error")
                return
        if url is not None:
            await _author_service(ctx).set_service_url(service_name, _clean_opt(url))
        service_thumbnail = _resolve_public_service_value(await _author_service(ctx).get_service_thumbnails(), service_name)
        service_phrase = _resolve_public_service_value(await _author_service(ctx).get_service_phrases(), service_name)
        service_url = _resolve_public_service_value(await _author_service(ctx).get_service_urls(), service_name)
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="author template_service_set",
            subtitle_args=[service_name],
            lines=[("result", "updated")],
            sections=_template_section(
                ("Phrase", _format_value(service_phrase)),
                ("Thumbnail", _format_value(service_thumbnail)),
                ("URL", _format_value(service_url)),
                ("Preview", render_author_name(service_name=service_name, phrase=service_phrase or await _author_service(ctx).get_global_phrase(), version=await _author_service(ctx).get_version())),
            ),
            kind="success",
        )

    @author_group.command(name="template_service_show", description="Show a service-specific author template.")
    @app_commands.describe(service="Service name.")
    @app_commands.autocomplete(service=_autocomplete_embed_template_service)
    async def author_template_service_show_command(interaction: discord.Interaction, service: str) -> None:
        if not await check_permission(interaction, "admin.author.template_service_show", ctx):
            return
        if _author_service(ctx) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_service_show", lines=[("reason", "Author service is unavailable")], kind="error")
            return
        service_name = _normalize_template_service_key(service)
        if service_name is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_service_show", lines=[("reason", "Provide a valid service name")], kind="error")
            return
        phrase = _resolve_public_service_value(await _author_service(ctx).get_service_phrases(), service_name)
        thumbnail_value = _resolve_public_service_value(await _author_service(ctx).get_service_thumbnails(), service_name)
        url_value = _resolve_public_service_value(await _author_service(ctx).get_service_urls(), service_name)
        global_phrase = await _author_service(ctx).get_global_phrase()
        version = await _author_service(ctx).get_version()
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="author template_service_show",
            subtitle_args=[service_name],
            sections=[
                *_template_section(
                    ("Phrase", _format_override_value(phrase, missing="(not set)")),
                    ("Thumbnail", _format_override_value(thumbnail_value, missing="(not set)")),
                    ("URL", _format_override_value(url_value, missing="(not set)")),
                    ("Preview", render_author_name(service_name=service_name, phrase=phrase or global_phrase, version=version)),
                ),
                _placeholder_section("author"),
            ],
        )

    @author_group.command(name="template_service_reset", description="Reset a service-specific author template.")
    @app_commands.describe(service="Service name.")
    @app_commands.autocomplete(service=_autocomplete_embed_template_service)
    async def author_template_service_reset_command(interaction: discord.Interaction, service: str) -> None:
        if not await check_permission(interaction, "admin.author.template_service_reset", ctx):
            return
        if _author_service(ctx) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_service_reset", lines=[("reason", "Author service is unavailable")], kind="error")
            return
        service_name = _normalize_template_service_key(service)
        if service_name is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_service_reset", lines=[("reason", "Provide a valid service name")], kind="error")
            return
        for alias in list_embed_service_aliases(service_name):
            await _author_service(ctx).set_service_phrase(alias, None)
            await _author_service(ctx).set_service_thumbnail(alias, None)
            await _author_service(ctx).set_service_url(alias, None)
        await _send_embed_response(interaction, ctx, subcommand_path="author template_service_reset", subtitle_args=[service_name], lines=[("result", "reset")], kind="success")

    @author_group.command(name="status", description="Show author status and effective service templates.")
    async def author_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.author.status", ctx):
            return
        if _author_service(ctx) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author status", lines=[("reason", "Author service is unavailable")], kind="error")
            return
        supported_services = list_public_embed_service_keys()
        enabled = await _author_service(ctx).is_enabled()
        service_phrases = await _author_service(ctx).get_service_phrases()
        service_thumbnails = await _author_service(ctx).get_service_thumbnails()
        service_urls = await _author_service(ctx).get_service_urls()
        custom_services, default_services = _build_status_service_buckets(
            supported_services,
            has_override=lambda service: _service_has_any_override(service, service_phrases, service_thumbnails, service_urls),
        )
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="author status",
            lines=[
                ("enabled", "on" if enabled else "off"),
                ("supported services", len(supported_services)),
                ("services with custom template", len(custom_services)),
                ("services using default", len(default_services)),
                (
                    "runtime rule",
                    (
                        "OFF = runtime always uses standard default author even if custom is saved"
                        if not enabled
                        else "ON = runtime uses service custom author when configured; otherwise standard default"
                    ),
                ),
            ],
            sections=[
                CommandEmbedSection(
                    title="Custom Templates",
                    lines=(
                        [
                            (
                                service,
                                ", ".join(
                                    token
                                    for token, value in (
                                        ("phrase", _resolve_public_service_value(service_phrases, service)),
                                        ("thumbnail", _resolve_public_service_value(service_thumbnails, service)),
                                        ("url", _resolve_public_service_value(service_urls, service)),
                                    )
                                    if value
                                ),
                            )
                            for service in custom_services
                        ]
                        if custom_services
                        else [("services", "(none)")]
                    ),
                ),
                CommandEmbedSection(
                    title="Default Services",
                    lines=[("services", ", ".join(default_services) if default_services else "(none)")],
                ),
                _placeholder_section("author"),
            ],
        )

    description_group = app_commands.Group(name="description", description="Description controls")
    embed_group.add_command(description_group)

    @description_group.command(name="on", description="Enable centralized description template overrides.")
    async def description_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.description.on", ctx):
            return
        if getattr(ctx, "description_template", None) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="description on", lines=[("reason", "Description template service is unavailable")], kind="error")
            return
        await ctx.description_template.set_enabled(True)
        await _send_embed_response(interaction, ctx, subcommand_path="description on", lines=[("result", "enabled")], kind="success")

    @description_group.command(name="off", description="Disable centralized description template overrides.")
    async def description_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.description.off", ctx):
            return
        if getattr(ctx, "description_template", None) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="description off", lines=[("reason", "Description template service is unavailable")], kind="error")
            return
        await ctx.description_template.set_enabled(False)
        await _send_embed_response(interaction, ctx, subcommand_path="description off", lines=[("result", "disabled")], kind="success")

    @description_group.command(name="status", description="Show centralized description template override status.")
    async def description_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.description.status", ctx):
            return
        if getattr(ctx, "description_template", None) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="description status", lines=[("reason", "Description template service is unavailable")], kind="error")
            return
        snapshot = await ctx.description_template.build_status_snapshot()
        supported_services = list_public_embed_service_keys()
        custom_services = sorted(snapshot.custom_templates)
        default_services = [service for service in supported_services if service not in snapshot.custom_templates]
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="description status",
            lines=[
                ("enabled", "on" if snapshot.enabled else "off"),
                ("supported services", snapshot.total_services),
                ("services with custom template", len(custom_services)),
                ("services using default", len(default_services)),
                ("runtime rule", "OFF = always native fallback; ON = service custom template when present"),
            ],
            sections=[
                CommandEmbedSection(
                    title="Custom Templates",
                    lines=(
                        [(service, _truncate_preview(snapshot.custom_templates[service])) for service in custom_services]
                        if custom_services
                        else [("services", "(none)")]
                    ),
                ),
                CommandEmbedSection(
                    title="Default Services",
                    lines=[("services", ", ".join(default_services) if default_services else "(none)")],
                ),
                _placeholder_section("description"),
            ],
        )

    @description_group.command(name="template_service_set", description="Set a service-specific description template.")
    @app_commands.describe(service="Service name.", template="Description template with placeholders.")
    @app_commands.autocomplete(service=_autocomplete_embed_template_service)
    async def description_template_service_set_command(interaction: discord.Interaction, service: str, template: str) -> None:
        if not await check_permission(interaction, "admin.description.template_service_set", ctx):
            return
        if getattr(ctx, "description_template", None) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="description template_service_set", lines=[("reason", "Description template service is unavailable")], kind="error")
            return
        service_name = _normalize_template_service_key(service)
        if service_name is None:
            await _send_embed_response(interaction, ctx, subcommand_path="description template_service_set", lines=[("reason", "Provide a valid service name")], kind="error")
            return
        try:
            stored = await ctx.description_template.set_template(service_name, template)
            preview = await ctx.description_template.render_preview(
                service=service_name,
                context=_description_preview_context(service_name=service_name),
                fallback="Usa default del servizio",
            )
        except InvalidDescriptionTemplateError as exc:
            await _send_embed_response(
                interaction,
                ctx,
                subcommand_path="description template_service_set",
                subtitle_args=[service_name],
                lines=[("reason", str(exc))],
                kind="error",
            )
            return
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="description template_service_set",
            subtitle_args=[service_name],
            lines=[("result", "updated")],
            sections=_template_section(("Template", stored), ("Preview", preview)),
            kind="success",
        )

    @description_group.command(name="template_service_show", description="Show a service-specific description template.")
    @app_commands.describe(service="Service name.")
    @app_commands.autocomplete(service=_autocomplete_embed_template_service)
    async def description_template_service_show_command(interaction: discord.Interaction, service: str) -> None:
        if not await check_permission(interaction, "admin.description.template_service_show", ctx):
            return
        if getattr(ctx, "description_template", None) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="description template_service_show", lines=[("reason", "Description template service is unavailable")], kind="error")
            return
        service_name = _normalize_template_service_key(service)
        if service_name is None:
            await _send_embed_response(interaction, ctx, subcommand_path="description template_service_show", lines=[("reason", "Provide a valid service name")], kind="error")
            return
        current = await ctx.description_template.get_template(service_name)
        preview = await ctx.description_template.render_preview(
            service=service_name,
            context=_description_preview_context(service_name=service_name),
            fallback="Usa default del servizio",
        )
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="description template_service_show",
            subtitle_args=[service_name],
            sections=[
                *_template_section(
                    ("Template", current or "usa default del servizio"),
                    ("Preview", preview),
                ),
                _placeholder_section("description"),
            ],
        )

    @description_group.command(name="template_service_reset", description="Reset a service-specific description template.")
    @app_commands.describe(service="Service name.")
    @app_commands.autocomplete(service=_autocomplete_embed_template_service)
    async def description_template_service_reset_command(interaction: discord.Interaction, service: str) -> None:
        if not await check_permission(interaction, "admin.description.template_service_reset", ctx):
            return
        if getattr(ctx, "description_template", None) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="description template_service_reset", lines=[("reason", "Description template service is unavailable")], kind="error")
            return
        service_name = _normalize_template_service_key(service)
        if service_name is None:
            await _send_embed_response(interaction, ctx, subcommand_path="description template_service_reset", lines=[("reason", "Provide a valid service name")], kind="error")
            return
        await ctx.description_template.reset_template(service_name)
        await _send_embed_response(interaction, ctx, subcommand_path="description template_service_reset", subtitle_args=[service_name], lines=[("result", "reset")], kind="success")

    images_group = app_commands.Group(name="images", description="Embed image controls")
    embed_group.add_command(images_group)

    @images_group.command(name="on", description="Enable centralized embed images rendering.")
    async def images_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.images.on", ctx):
            return
        if getattr(ctx, "embed_images", None) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="images on", lines=[("reason", "Embed images service is unavailable")], kind="error")
            return
        await ctx.embed_images.set_enabled(True)
        await _send_embed_response(interaction, ctx, subcommand_path="images on", lines=[("result", "enabled")], kind="success")

    @images_group.command(name="off", description="Disable centralized embed images rendering.")
    async def images_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.images.off", ctx):
            return
        if getattr(ctx, "embed_images", None) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="images off", lines=[("reason", "Embed images service is unavailable")], kind="error")
            return
        await ctx.embed_images.set_enabled(False)
        await _send_embed_response(interaction, ctx, subcommand_path="images off", lines=[("result", "disabled")], kind="success")

    @images_group.command(name="status", description="Show embed images status.")
    async def images_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.images.status", ctx):
            return
        if getattr(ctx, "embed_images", None) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="images status", lines=[("reason", "Embed images service is unavailable")], kind="error")
            return
        snapshot = await ctx.embed_images.build_status_snapshot()
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="images status",
            lines=[
                ("enabled", "on" if snapshot.enabled else "off"),
                ("global image", _format_value(snapshot.global_image)),
                ("global thumbnail", _format_value(snapshot.global_thumbnail)),
                ("service image overrides", len(snapshot.service_images)),
                ("service thumbnail overrides", len(snapshot.service_thumbnails)),
                ("precedence", "runtime override > service template > global template > no image"),
            ],
        )

    @images_group.command(name="template_global_set", description="Set global image and thumbnail templates.")
    @app_commands.describe(image="Optional global embed image URL.", thumbnail="Optional global embed thumbnail URL.")
    async def images_template_global_set_command(interaction: discord.Interaction, image: str | None = None, thumbnail: str | None = None) -> None:
        if not await check_permission(interaction, "admin.images.template_global_set", ctx):
            return
        if getattr(ctx, "embed_images", None) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="images template_global_set", lines=[("reason", "Embed images service is unavailable")], kind="error")
            return
        if image is None and thumbnail is None:
            await _send_embed_response(interaction, ctx, subcommand_path="images template_global_set", lines=[("reason", "No changes provided")], kind="warning")
            return
        try:
            if image is not None:
                await ctx.embed_images.set_global_image(_clean_opt(image))
            if thumbnail is not None:
                await ctx.embed_images.set_global_thumbnail(_clean_opt(thumbnail))
        except InvalidEmbedImageUrlError as exc:
            await _send_embed_response(interaction, ctx, subcommand_path="images template_global_set", lines=[("reason", str(exc))], kind="error")
            return
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="images template_global_set",
            lines=[("result", "updated")],
            sections=_template_section(
                ("Image", _format_value(await ctx.embed_images.get_global_image())),
                ("Thumbnail", _format_value(await ctx.embed_images.get_global_thumbnail())),
            ),
            kind="success",
        )

    @images_group.command(name="template_global_show", description="Show global image and thumbnail templates.")
    async def images_template_global_show_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.images.template_global_show", ctx):
            return
        if getattr(ctx, "embed_images", None) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="images template_global_show", lines=[("reason", "Embed images service is unavailable")], kind="error")
            return
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="images template_global_show",
            sections=_template_section(
                ("Image", _format_override_value(await ctx.embed_images.get_global_image(), missing="(not set)")),
                ("Thumbnail", _format_override_value(await ctx.embed_images.get_global_thumbnail(), missing="(not set)")),
            ),
        )

    @images_group.command(name="template_global_reset", description="Reset global image and thumbnail templates.")
    async def images_template_global_reset_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.images.template_global_reset", ctx):
            return
        if getattr(ctx, "embed_images", None) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="images template_global_reset", lines=[("reason", "Embed images service is unavailable")], kind="error")
            return
        await ctx.embed_images.set_global_image(None)
        await ctx.embed_images.set_global_thumbnail(None)
        await _send_embed_response(interaction, ctx, subcommand_path="images template_global_reset", lines=[("result", "reset")], kind="success")

    @images_group.command(name="template_service_set", description="Set service-level image and thumbnail templates.")
    @app_commands.describe(service="Service name.", image="Optional service embed image URL.", thumbnail="Optional service embed thumbnail URL.")
    @app_commands.autocomplete(service=_autocomplete_embed_template_service)
    async def images_template_service_set_command(interaction: discord.Interaction, service: str, image: str | None = None, thumbnail: str | None = None) -> None:
        if not await check_permission(interaction, "admin.images.template_service_set", ctx):
            return
        if getattr(ctx, "embed_images", None) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="images template_service_set", lines=[("reason", "Embed images service is unavailable")], kind="error")
            return
        service_name = _normalize_template_service_key(service)
        if service_name is None:
            await _send_embed_response(interaction, ctx, subcommand_path="images template_service_set", lines=[("reason", "Provide a valid service name")], kind="error")
            return
        if image is None and thumbnail is None:
            await _send_embed_response(interaction, ctx, subcommand_path="images template_service_set", subtitle_args=[service_name], lines=[("reason", "No changes provided")], kind="warning")
            return
        try:
            if image is not None:
                await ctx.embed_images.set_service_image(service_name, _clean_opt(image))
            if thumbnail is not None:
                await ctx.embed_images.set_service_thumbnail(service_name, _clean_opt(thumbnail))
        except InvalidEmbedImageUrlError as exc:
            await _send_embed_response(interaction, ctx, subcommand_path="images template_service_set", subtitle_args=[service_name], lines=[("reason", str(exc))], kind="error")
            return
        service_image = _resolve_public_service_value(await ctx.embed_images.get_service_images(), service_name)
        service_thumbnail = _resolve_public_service_value(await ctx.embed_images.get_service_thumbnails(), service_name)
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="images template_service_set",
            subtitle_args=[service_name],
            lines=[("result", "updated")],
            sections=_template_section(("Image", _format_value(service_image)), ("Thumbnail", _format_value(service_thumbnail))),
            kind="success",
        )

    @images_group.command(name="template_service_show", description="Show service-level image and thumbnail templates.")
    @app_commands.describe(service="Service name.")
    @app_commands.autocomplete(service=_autocomplete_embed_template_service)
    async def images_template_service_show_command(interaction: discord.Interaction, service: str) -> None:
        if not await check_permission(interaction, "admin.images.template_service_show", ctx):
            return
        if getattr(ctx, "embed_images", None) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="images template_service_show", lines=[("reason", "Embed images service is unavailable")], kind="error")
            return
        service_name = _normalize_template_service_key(service)
        if service_name is None:
            await _send_embed_response(interaction, ctx, subcommand_path="images template_service_show", lines=[("reason", "Provide a valid service name")], kind="error")
            return
        service_image = _resolve_public_service_value(await ctx.embed_images.get_service_images(), service_name)
        service_thumbnail = _resolve_public_service_value(await ctx.embed_images.get_service_thumbnails(), service_name)
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="images template_service_show",
            subtitle_args=[service_name],
            sections=_template_section(
                ("Image", _format_override_value(service_image, missing="(not set)")),
                ("Thumbnail", _format_override_value(service_thumbnail, missing="(not set)")),
            ),
        )

    @images_group.command(name="template_service_reset", description="Reset service-level image and thumbnail templates.")
    @app_commands.describe(service="Service name.")
    @app_commands.autocomplete(service=_autocomplete_embed_template_service)
    async def images_template_service_reset_command(interaction: discord.Interaction, service: str) -> None:
        if not await check_permission(interaction, "admin.images.template_service_reset", ctx):
            return
        if getattr(ctx, "embed_images", None) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="images template_service_reset", lines=[("reason", "Embed images service is unavailable")], kind="error")
            return
        service_name = _normalize_template_service_key(service)
        if service_name is None:
            await _send_embed_response(interaction, ctx, subcommand_path="images template_service_reset", lines=[("reason", "Provide a valid service name")], kind="error")
            return
        for alias in list_embed_service_aliases(service_name):
            await ctx.embed_images.set_service_image(alias, None)
            await ctx.embed_images.set_service_thumbnail(alias, None)
        await _send_embed_response(interaction, ctx, subcommand_path="images template_service_reset", subtitle_args=[service_name], lines=[("result", "reset")], kind="success")
