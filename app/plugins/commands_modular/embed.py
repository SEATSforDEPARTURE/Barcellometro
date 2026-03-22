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
from app.services.author import InvalidAuthorThumbnailError, render_author_name
from app.services.footer import InvalidFooterThumbnailError, ServiceFooterProfile


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
        author_service=ctx.author,
        footer_service_name="status",
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
                ("Version", _format_override_value(current_version, missing="No custom override (default brand version in use)")),
                ("Phrase", _format_override_value(current_global, missing="No custom override (default footer phrase in use)")),
                ("Thumbnail", _format_override_value(current_thumbnail, missing="No custom override (default footer thumbnail in use)")),
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
                ("Phrase", _format_override_value(phrase, missing="No custom override (service uses default footer behavior)")),
                ("Thumbnail", _format_override_value(thumbnail_value, missing="No custom override (service uses default footer thumbnail behavior)")),
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
        embeds = await build_footer_status_embeds(snapshot, footer_service=ctx.footer)
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
        await send_command_embeds(interaction, embeds=[embeds[0]], ephemeral=True, view=view, footer_service=ctx.footer, author_service=ctx.author, default_service_name="status")

    author_group = app_commands.Group(name="author", description="Author controls")
    embed_group.add_command(author_group)

    @author_group.command(name="on", description="Enable author rendering.")
    async def author_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.author.on", ctx):
            return
        if ctx.author is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author on", lines=[("reason", "Author service is unavailable")], kind="error")
            return
        await ctx.author.set_enabled(True)
        await _send_embed_response(interaction, ctx, subcommand_path="author on", lines=[("result", "enabled")], kind="success")

    @author_group.command(name="off", description="Disable author rendering.")
    async def author_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.author.off", ctx):
            return
        if ctx.author is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author off", lines=[("reason", "Author service is unavailable")], kind="error")
            return
        await ctx.author.set_enabled(False)
        await _send_embed_response(interaction, ctx, subcommand_path="author off", lines=[("result", "disabled")], kind="success")

    @author_group.command(name="template_global_set", description="Set the global author template.")
    @app_commands.describe(version="Optional author template version suffix.", phrase="Optional global author phrase.", thumbnail="Optional author thumbnail: Discord custom emoji or http/https image URL.")
    async def author_template_global_set_command(
        interaction: discord.Interaction,
        version: str | None = None,
        phrase: str | None = None,
        thumbnail: str | None = None,
    ) -> None:
        if not await check_permission(interaction, "admin.author.template_global_set", ctx):
            return
        if ctx.author is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_global_set", lines=[("reason", "Author service is unavailable")], kind="error")
            return
        if version is None and phrase is None and thumbnail is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_global_set", lines=[("reason", "No changes provided")], sections=_next_step_section("/embed author template_global_show"), kind="warning")
            return
        if version is not None:
            await ctx.author.set_version(_clean_opt(version))
        if phrase is not None:
            await ctx.author.set_global_phrase(_clean_opt(phrase))
        if thumbnail is not None:
            try:
                await ctx.author.set_global_thumbnail(_clean_opt(thumbnail))
            except InvalidAuthorThumbnailError as exc:
                await _send_embed_response(interaction, ctx, subcommand_path="author template_global_set", lines=[("reason", str(exc))], kind="error")
                return
        preview = render_author_name(
            service_name="status",
            phrase=await ctx.author.get_global_phrase(),
            version=await ctx.author.get_version(),
        )
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="author template_global_set",
            lines=[("result", "updated")],
            sections=_template_section(
                ("Version", _format_value(await ctx.author.get_version())),
                ("Phrase", _format_value(await ctx.author.get_global_phrase())),
                ("Thumbnail", _format_value(await ctx.author.get_global_thumbnail())),
                ("Preview", preview),
            ),
            kind="success",
        )

    @author_group.command(name="template_global_show", description="Show the global author template.")
    async def author_template_global_show_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.author.template_global_show", ctx):
            return
        if ctx.author is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_global_show", lines=[("reason", "Author service is unavailable")], kind="error")
            return
        current_version = await ctx.author.get_version()
        current_global = await ctx.author.get_global_phrase()
        current_thumbnail = await ctx.author.get_global_thumbnail()
        preview = render_author_name(service_name="status", phrase=current_global, version=current_version)
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="author template_global_show",
            sections=_template_section(
                ("Version", _format_override_value(current_version, missing="No custom override (version is ignored without an author phrase)")),
                ("Phrase", _format_override_value(current_global, missing="No custom override (services use semantic fallback author)")),
                ("Thumbnail", _format_override_value(current_thumbnail, missing="No custom override (default author has no thumbnail)")),
                ("Preview", preview),
            ),
        )

    @author_group.command(name="template_global_reset", description="Reset the global author template.")
    async def author_template_global_reset_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.author.template_global_reset", ctx):
            return
        if ctx.author is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_global_reset", lines=[("reason", "Author service is unavailable")], kind="error")
            return
        await ctx.author.set_version(None)
        await ctx.author.set_global_phrase(None)
        await ctx.author.set_global_thumbnail(None)
        await _send_embed_response(interaction, ctx, subcommand_path="author template_global_reset", lines=[("result", "reset")], kind="success")

    @author_group.command(name="template_service_set", description="Set a service-specific author template.")
    @app_commands.describe(service="Service name.", phrase="Optional service-specific author phrase.", thumbnail="Optional author thumbnail: Discord custom emoji or http/https image URL.")
    async def author_template_service_set_command(
        interaction: discord.Interaction,
        service: str,
        phrase: str | None = None,
        thumbnail: str | None = None,
    ) -> None:
        if not await check_permission(interaction, "admin.author.template_service_set", ctx):
            return
        if ctx.author is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_service_set", lines=[("reason", "Author service is unavailable")], kind="error")
            return
        service_name = _clean_opt(service)
        if service_name is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_service_set", lines=[("reason", "Provide a valid service name")], kind="error")
            return
        if phrase is None and thumbnail is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_service_set", subtitle_args=[service_name], lines=[("reason", "No changes provided")], kind="warning")
            return
        if phrase is not None:
            await ctx.author.set_service_phrase(service_name, _clean_opt(phrase))
        if thumbnail is not None:
            try:
                await ctx.author.set_service_thumbnail(service_name, _clean_opt(thumbnail))
            except InvalidAuthorThumbnailError as exc:
                await _send_embed_response(interaction, ctx, subcommand_path="author template_service_set", subtitle_args=[service_name], lines=[("reason", str(exc))], kind="error")
                return
        service_thumbnail = (await ctx.author.get_service_thumbnails()).get(service_name)
        service_phrase = (await ctx.author.get_service_phrases()).get(service_name)
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="author template_service_set",
            subtitle_args=[service_name],
            lines=[("result", "updated")],
            sections=_template_section(
                ("Phrase", _format_value(service_phrase)),
                ("Thumbnail", _format_value(service_thumbnail)),
                ("Preview", render_author_name(service_name=service_name, phrase=service_phrase or await ctx.author.get_global_phrase(), version=await ctx.author.get_version())),
            ),
            kind="success",
        )

    @author_group.command(name="template_service_show", description="Show a service-specific author template.")
    @app_commands.describe(service="Service name.")
    async def author_template_service_show_command(interaction: discord.Interaction, service: str) -> None:
        if not await check_permission(interaction, "admin.author.template_service_show", ctx):
            return
        if ctx.author is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_service_show", lines=[("reason", "Author service is unavailable")], kind="error")
            return
        service_name = _clean_opt(service)
        if service_name is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_service_show", lines=[("reason", "Provide a valid service name")], kind="error")
            return
        phrase = (await ctx.author.get_service_phrases()).get(service_name)
        thumbnail_value = (await ctx.author.get_service_thumbnails()).get(service_name)
        global_phrase = await ctx.author.get_global_phrase()
        version = await ctx.author.get_version()
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="author template_service_show",
            subtitle_args=[service_name],
            sections=_template_section(
                ("Phrase", _format_override_value(phrase, missing="No custom override (service uses global/fallback author phrase)")),
                ("Thumbnail", _format_override_value(thumbnail_value, missing="No custom override (service uses global/no thumbnail fallback)")),
                ("Preview", render_author_name(service_name=service_name, phrase=phrase or global_phrase, version=version)),
            ),
        )

    @author_group.command(name="template_service_reset", description="Reset a service-specific author template.")
    @app_commands.describe(service="Service name.")
    async def author_template_service_reset_command(interaction: discord.Interaction, service: str) -> None:
        if not await check_permission(interaction, "admin.author.template_service_reset", ctx):
            return
        if ctx.author is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_service_reset", lines=[("reason", "Author service is unavailable")], kind="error")
            return
        service_name = _clean_opt(service)
        if service_name is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author template_service_reset", lines=[("reason", "Provide a valid service name")], kind="error")
            return
        await ctx.author.set_service_phrase(service_name, None)
        await ctx.author.set_service_thumbnail(service_name, None)
        await _send_embed_response(interaction, ctx, subcommand_path="author template_service_reset", subtitle_args=[service_name], lines=[("result", "reset")], kind="success")

    @author_group.command(name="status", description="Show author status and effective service templates.")
    async def author_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.author.status", ctx):
            return
        if ctx.author is None:
            await _send_embed_response(interaction, ctx, subcommand_path="author status", lines=[("reason", "Author service is unavailable")], kind="error")
            return
        known_services = await ctx.author.get_known_services()
        if not known_services:
            await _send_embed_response(interaction, ctx, subcommand_path="author status", lines=[("reason", "No known author services")], kind="warning")
            return
        snapshot = await ctx.author.build_status_snapshot()
        embeds = await build_author_status_embeds(snapshot, footer_service=ctx.footer, author_service=ctx.author)
        if not embeds:
            await _send_embed_response(interaction, ctx, subcommand_path="author status", lines=[("reason", "No author data available")], kind="warning")
            return
        view = AuthorStatusPaginationView(embeds)
        await send_command_embeds(interaction, embeds=[embeds[0]], ephemeral=True, view=view, footer_service=ctx.footer, author_service=ctx.author, default_service_name="status")
