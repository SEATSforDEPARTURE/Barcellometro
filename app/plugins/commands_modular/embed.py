from __future__ import annotations

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.shared.discord.author_status_pagination import AuthorStatusPaginationView
from app.shared.discord.author_status_renderer import build_author_status_embeds
from app.shared.discord.command_embeds import CommandEmbedSection, send_command_embeds, send_standard_response
from app.shared.discord.footer_status_pagination import FooterStatusPaginationView
from app.shared.discord.footer_status_renderer import build_footer_status_embeds
from app.services.embed_images import InvalidEmbedImageUrlError
from app.services.author import InvalidAuthorThumbnailError, render_author_name
from app.services.description_template_service import InvalidDescriptionTemplateError
from app.services.footer import InvalidFooterThumbnailError, ServiceFooterProfile


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


def _description_preview_context(*, service_name: str, user_name: str = "Mario") -> dict[str, object]:
    return {
        "user_name": user_name,
        "service_name": service_name,
        "ordinal_today": "secondo",
        "audio_intro": "Leggiamo cosa ci dice",
        "is_first_today": False,
        "count_today": 2,
    }


async def _infer_audio_notes_profile(ctx: CommandContext) -> ServiceFooterProfile:
    stt_backend = ((await ctx.database.get_setting("stt.backend")) or "local").strip().lower()
    translate_backend = ((await ctx.database.get_setting("translate.backend")) or "local").strip().lower()
    stt_local_model = ((await ctx.database.get_setting("stt.local.model")) or "small").strip()
    stt_ai_model = ctx.ai.get_runtime_model("transcription") if ctx.ai is not None else "openai:gpt-4o-transcribe"
    translate_ai_model = ctx.ai.get_runtime_model("translation") if ctx.ai is not None else "openai:gpt-4o-mini"

    stt_model = stt_local_model if stt_backend != "ai" else (stt_ai_model or "gpt-4o-transcribe")
    translation_model = "argos" if translate_backend != "ai" else (translate_ai_model or "gpt-4o-mini")

    contributors: list[str] = []
    if stt_model:
        contributors.append(stt_model)
    if translation_model:
        contributors.append(translation_model)

    deduped: list[str] = []
    seen: set[str] = set()
    for item in contributors:
        clean = item.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        deduped.append(clean)

    return ServiceFooterProfile(
        service_name="audio_notes",
        contributors=deduped,
        used_local_processing=(stt_backend != "ai" or translate_backend != "ai"),
        last_rendered_footer=None,
        updated_at=None,
        origins={"inference"},
    )


async def _infer_service_profile(service_name: str, ctx: CommandContext) -> ServiceFooterProfile:
    if service_name == "audio_notes":
        return await _infer_audio_notes_profile(ctx)
    return ServiceFooterProfile(
        service_name=service_name,
        contributors=[],
        used_local_processing=True,
        last_rendered_footer=None,
        updated_at=None,
        origins={"fallback"},
    )


def register_embed(embed_group: app_commands.Group, ctx: CommandContext) -> None:
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
        service_name = _clean_opt(service)
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
        service_thumbnail = (await ctx.footer.get_service_thumbnails()).get(service_name)
        service_phrase = (await ctx.footer.get_service_phrases()).get(service_name)
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
        service_name = _clean_opt(service)
        if service_name is None:
            await _send_embed_response(
                interaction,
                ctx,
                subcommand_path="footer template_service_show",
                lines=[("reason", "Provide a valid service name")],
                kind="error",
            )
            return
        phrase = (await ctx.footer.get_service_phrases()).get(service_name)
        thumbnail_value = (await ctx.footer.get_service_thumbnails()).get(service_name)
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="footer template_service_show",
            subtitle_args=[service_name],
            sections=_template_section(
                ("Phrase", _format_override_value(phrase, missing="(not set)")),
                ("Thumbnail", _format_override_value(thumbnail_value, missing="(not set)")),
            ),
        )

    @footer_group.command(name="template_service_reset", description="Reset a service-specific footer template.")
    @app_commands.describe(service="Service name.")
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
        service_name = _clean_opt(service)
        if service_name is None:
            await _send_embed_response(
                interaction,
                ctx,
                subcommand_path="footer template_service_reset",
                lines=[("reason", "Provide a valid service name")],
                kind="error",
            )
            return
        await ctx.footer.set_service_phrase(service_name, None)
        await ctx.footer.set_service_thumbnail(service_name, None)
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

        known_services = await ctx.footer.get_known_services()

        if not known_services:
            await _send_embed_response(
                interaction,
                ctx,
                subcommand_path="footer status",
                lines=[("reason", "No known footer services")],
                kind="warning",
            )
            return

        snapshot = await ctx.footer.build_status_snapshot(inferred_profile_resolver=lambda service_name: _infer_service_profile(service_name, ctx))
        embeds = await build_footer_status_embeds(
            snapshot,
            footer_service=ctx.footer,
            author_service=getattr(ctx, "author", None),
        )
        if not embeds:
            await _send_embed_response(
                interaction,
                ctx,
                subcommand_path="footer status",
                lines=[("reason", "No footer data available")],
                kind="warning",
            )
            return
        view = FooterStatusPaginationView(embeds)
        await send_command_embeds(interaction, embeds=[embeds[0]], ephemeral=True, view=view, footer_service=ctx.footer, author_service=_author_service(ctx), embed_images_service=getattr(ctx, "embed_images", None), default_service_name="status")

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
        service_name = _clean_opt(service)
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
        service_thumbnail = (await _author_service(ctx).get_service_thumbnails()).get(service_name)
        service_phrase = (await _author_service(ctx).get_service_phrases()).get(service_name)
        service_url = (await _author_service(ctx).get_service_urls()).get(service_name)
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
    async def author_template_service_show_command(interaction: discord.Interaction, service: str) -> None:
        if not await check_permission(interaction, "admin.author.template_service_show", ctx):
            return
        if _author_service(ctx) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_service_show", lines=[("reason", "Author service is unavailable")], kind="error")
            return
        service_name = _clean_opt(service)
        if service_name is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_service_show", lines=[("reason", "Provide a valid service name")], kind="error")
            return
        phrase = (await _author_service(ctx).get_service_phrases()).get(service_name)
        thumbnail_value = (await _author_service(ctx).get_service_thumbnails()).get(service_name)
        url_value = (await _author_service(ctx).get_service_urls()).get(service_name)
        global_phrase = await _author_service(ctx).get_global_phrase()
        version = await _author_service(ctx).get_version()
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="author template_service_show",
            subtitle_args=[service_name],
            sections=_template_section(
                ("Phrase", _format_override_value(phrase, missing="(not set)")),
                ("Thumbnail", _format_override_value(thumbnail_value, missing="(not set)")),
                ("URL", _format_override_value(url_value, missing="(not set)")),
                ("Preview", render_author_name(service_name=service_name, phrase=phrase or global_phrase, version=version)),
            ),
        )

    @author_group.command(name="template_service_reset", description="Reset a service-specific author template.")
    @app_commands.describe(service="Service name.")
    async def author_template_service_reset_command(interaction: discord.Interaction, service: str) -> None:
        if not await check_permission(interaction, "admin.author.template_service_reset", ctx):
            return
        if _author_service(ctx) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_service_reset", lines=[("reason", "Author service is unavailable")], kind="error")
            return
        service_name = _clean_opt(service)
        if service_name is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_service_reset", lines=[("reason", "Provide a valid service name")], kind="error")
            return
        await _author_service(ctx).set_service_phrase(service_name, None)
        await _author_service(ctx).set_service_thumbnail(service_name, None)
        await _author_service(ctx).set_service_url(service_name, None)
        await _send_embed_response(interaction, ctx, subcommand_path="author template_service_reset", subtitle_args=[service_name], lines=[("result", "reset")], kind="success")

    @author_group.command(name="status", description="Show author status and effective service templates.")
    async def author_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.author.status", ctx):
            return
        if _author_service(ctx) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author status", lines=[("reason", "Author service is unavailable")], kind="error")
            return
        known_services = await _author_service(ctx).get_known_services()
        if not known_services:
            await _send_embed_response(interaction, ctx, subcommand_path="author status", lines=[("reason", "No known author services")], kind="warning")
            return
        snapshot = await _author_service(ctx).build_status_snapshot()
        embeds = await build_author_status_embeds(snapshot, footer_service=ctx.footer, author_service=getattr(ctx, "author", None))
        if not embeds:
            await _send_embed_response(interaction, ctx, subcommand_path="author status", lines=[("reason", "No author data available")], kind="warning")
            return
        view = AuthorStatusPaginationView(embeds)
        await send_command_embeds(interaction, embeds=[embeds[0]], ephemeral=True, view=view, footer_service=ctx.footer, author_service=_author_service(ctx), embed_images_service=getattr(ctx, "embed_images", None), default_service_name="status")

    description_group = app_commands.Group(name="description", description="Description controls")
    embed_group.add_command(description_group)

    @description_group.command(name="template_service_set", description="Set a service-specific description template.")
    @app_commands.describe(service="Service name.", template="Description template with placeholders.")
    async def description_template_service_set_command(interaction: discord.Interaction, service: str, template: str) -> None:
        if not await check_permission(interaction, "admin.description.template_service_set", ctx):
            return
        if getattr(ctx, "description_template", None) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="description template_service_set", lines=[("reason", "Description template service is unavailable")], kind="error")
            return
        service_name = _clean_opt(service)
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
    async def description_template_service_show_command(interaction: discord.Interaction, service: str) -> None:
        if not await check_permission(interaction, "admin.description.template_service_show", ctx):
            return
        if getattr(ctx, "description_template", None) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="description template_service_show", lines=[("reason", "Description template service is unavailable")], kind="error")
            return
        service_name = _clean_opt(service)
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
            sections=_template_section(
                ("Template", current or "usa default del servizio"),
                ("Preview", preview),
            ),
        )

    @description_group.command(name="template_service_reset", description="Reset a service-specific description template.")
    @app_commands.describe(service="Service name.")
    async def description_template_service_reset_command(interaction: discord.Interaction, service: str) -> None:
        if not await check_permission(interaction, "admin.description.template_service_reset", ctx):
            return
        if getattr(ctx, "description_template", None) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="description template_service_reset", lines=[("reason", "Description template service is unavailable")], kind="error")
            return
        service_name = _clean_opt(service)
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
    async def images_template_service_set_command(interaction: discord.Interaction, service: str, image: str | None = None, thumbnail: str | None = None) -> None:
        if not await check_permission(interaction, "admin.images.template_service_set", ctx):
            return
        if getattr(ctx, "embed_images", None) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="images template_service_set", lines=[("reason", "Embed images service is unavailable")], kind="error")
            return
        service_name = _clean_opt(service)
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
        service_image = (await ctx.embed_images.get_service_images()).get(service_name)
        service_thumbnail = (await ctx.embed_images.get_service_thumbnails()).get(service_name)
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
    async def images_template_service_show_command(interaction: discord.Interaction, service: str) -> None:
        if not await check_permission(interaction, "admin.images.template_service_show", ctx):
            return
        if getattr(ctx, "embed_images", None) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="images template_service_show", lines=[("reason", "Embed images service is unavailable")], kind="error")
            return
        service_name = _clean_opt(service)
        if service_name is None:
            await _send_embed_response(interaction, ctx, subcommand_path="images template_service_show", lines=[("reason", "Provide a valid service name")], kind="error")
            return
        service_image = (await ctx.embed_images.get_service_images()).get(service_name)
        service_thumbnail = (await ctx.embed_images.get_service_thumbnails()).get(service_name)
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
    async def images_template_service_reset_command(interaction: discord.Interaction, service: str) -> None:
        if not await check_permission(interaction, "admin.images.template_service_reset", ctx):
            return
        if getattr(ctx, "embed_images", None) is None:
            await _send_embed_response(interaction, ctx, subcommand_path="images template_service_reset", lines=[("reason", "Embed images service is unavailable")], kind="error")
            return
        service_name = _clean_opt(service)
        if service_name is None:
            await _send_embed_response(interaction, ctx, subcommand_path="images template_service_reset", lines=[("reason", "Provide a valid service name")], kind="error")
            return
        await ctx.embed_images.set_service_image(service_name, None)
        await ctx.embed_images.set_service_thumbnail(service_name, None)
        await _send_embed_response(interaction, ctx, subcommand_path="images template_service_reset", subtitle_args=[service_name], lines=[("result", "reset")], kind="success")
