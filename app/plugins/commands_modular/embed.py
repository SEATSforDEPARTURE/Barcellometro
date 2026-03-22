from __future__ import annotations

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.shared.discord.command_embeds import CommandEmbedSection, send_legacy_standard_response, send_standard_response
from app.shared.discord.embed_status_helpers import _chunk_status_blocks, _service_section
from app.services.footer import InvalidFooterThumbnailError, ServiceFooterProfile, ServiceFooterVariant, _is_persistable_service_name


async def _send_legacy(interaction: discord.Interaction, ctx: CommandContext, **kwargs) -> None:
    await send_legacy_standard_response(interaction, footer_service=ctx.footer, **kwargs)


async def _send_embed_response(
    interaction: discord.Interaction,
    ctx: CommandContext,
    *,
    subcommand_path: str,
    lines: list[tuple[str, object]] | None = None,
    sections: list[CommandEmbedSection] | None = None,
    kind: str = "info",
) -> None:
    await send_standard_response(
        interaction,
        top_level="embed",
        subcommand_path=subcommand_path,
        lines=lines,
        sections=sections,
        kind=kind,
        footer_service=ctx.footer,
        ephemeral=True,
    )


def _clean_opt(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _format_value(value: str | None) -> str:
    return value if value else "(not set)"


def _format_override_value(value: str | None, *, missing: str) -> str:
    return value if value else missing


def _human_service_name(service_name: str) -> str:
    labels = {
        "campagne_notizie": "campagne_notizie",
        "campagne_meteo": "campagne_meteo",
        "campagne_oroscopo": "campagne_oroscopo",
        "campagne_prompt": "campagne_prompt",
        "campagne_timer": "campagne_timer",
    }
    return labels.get(service_name, service_name.replace("_", " ").title())


def _format_contributors(contributors: list[str]) -> str:
    return " + ".join(contributors) if contributors else "(none)"


def _format_variant_block(service_name: str, variant: ServiceFooterVariant, phrase: str) -> str:
    mode = "local" if variant.used_local_processing else "remote"
    footer_text = variant.last_rendered_footer or "(footer not rendered yet)"
    origins = ",".join(sorted(variant.origins or [])) or "(n/a)"
    updated = variant.updated_at or "(n/a)"
    return (
        f"variant: {mode} | {_format_contributors(variant.contributors)}\n"
        f"→ {footer_text}\n"
        f"phrase: {phrase}\n"
        f"origin: {origins}\n"
        f"updated: {updated}\n"
        f"key: {variant.variant_key}"
    )


def _format_service_header(service_name: str) -> str:
    return f"**{service_name}**\nlabel: {_human_service_name(service_name)}\ntechnical alias: `{service_name}`"


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
            await _send_legacy(interaction, ctx, top_level="embed", path_parts=["footer", "on"], entries=[("Reason", "Footer service is unavailable")], tone="error", service_name="status")
            return
        await ctx.footer.set_enabled(True)
        await _send_legacy(interaction, ctx, top_level="embed", path_parts=["footer", "on"], entries=[("Status", "enabled")], tone="success", service_name="status")

    @footer_group.command(name="off", description="Disable footer rendering.")
    async def footer_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.footer.off", ctx):
            return
        if ctx.footer is None:
            await _send_legacy(interaction, ctx, top_level="embed", path_parts=["footer", "off"], entries=[("Reason", "Footer service is unavailable")], tone="error", service_name="status")
            return
        await ctx.footer.set_enabled(False)
        await _send_legacy(interaction, ctx, top_level="embed", path_parts=["footer", "off"], entries=[("Status", "disabled")], tone="success", service_name="status")

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
            await _send_legacy(interaction, ctx, top_level="embed", path_parts=["footer", "template_global_set"], entries=[("Reason", "Footer service is unavailable")], tone="error", service_name="status")
            return
        if version is None and phrase is None and thumbnail is None:
            await _send_legacy(
                interaction,
                ctx,
                top_level="embed",
                path_parts=["footer", "template_global_set"],
                entries=[("Reason", "No changes provided")],
                tone="warning",
                sections=[("Next Step", [("Command", "/embed footer template_global_show")])],
                service_name="status",
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
                await _send_legacy(interaction, ctx, top_level="embed", path_parts=["footer", "template_global_set"], entries=[("Reason", str(exc))], tone="error", service_name="status")
                return
        await _send_legacy(
            interaction,
            ctx,
            top_level="embed",
            path_parts=["footer", "template_global_set"],
            entries=[
                ("Status", "updated"),
                ("Version", _format_value(await ctx.footer.get_version())),
                ("Phrase", _format_value(await ctx.footer.get_global_phrase())),
                ("Thumbnail", _format_value(await ctx.footer.get_global_thumbnail())),
            ],
            tone="success",
            service_name="status",
        )

    @footer_group.command(name="template_global_show", description="Show the global footer template.")
    async def footer_template_global_show_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.footer.template_global_show", ctx):
            return
        if ctx.footer is None:
            await _send_legacy(interaction, ctx, top_level="embed", path_parts=["footer", "template_global_show"], entries=[("Reason", "Footer service is unavailable")], tone="error", service_name="status")
            return
        current_version = await ctx.footer.get_version()
        current_global = await ctx.footer.get_global_phrase()
        current_thumbnail = await ctx.footer.get_global_thumbnail()
        await _send_legacy(
            interaction,
            ctx,
            top_level="embed",
            path_parts=["footer", "template_global_show"],
            entries=[
                ("Version", _format_override_value(current_version, missing="No custom override (default brand version in use)")),
                ("Phrase", _format_override_value(current_global, missing="No custom override (default footer phrase in use)")),
                ("Thumbnail", _format_override_value(current_thumbnail, missing="No custom override (default footer thumbnail in use)")),
            ],
            service_name="status",
        )

    @footer_group.command(name="template_global_reset", description="Reset the global footer template.")
    async def footer_template_global_reset_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.footer.template_global_reset", ctx):
            return
        if ctx.footer is None:
            await _send_legacy(interaction, ctx, top_level="embed", path_parts=["footer", "template_global_reset"], entries=[("Reason", "Footer service is unavailable")], tone="error", service_name="status")
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
            await _send_legacy(interaction, ctx, top_level="embed", path_parts=["footer", "template_service_set"], entries=[("Reason", "Footer service is unavailable")], tone="error", service_name="status")
            return
        service_name = _clean_opt(service)
        if service_name is None:
            await _send_legacy(interaction, ctx, top_level="embed", path_parts=["footer", "template_service_set"], entries=[("Reason", "Provide a valid service name")], tone="error", service_name="status")
            return
        if phrase is None and thumbnail is None:
            await _send_legacy(interaction, ctx, top_level="embed", path_parts=["footer", "template_service_set"], entries=[("Reason", "No changes provided")], tone="warning", service_name="status")
            return
        if phrase is not None:
            await ctx.footer.set_service_phrase(service_name, _clean_opt(phrase))
        if thumbnail is not None:
            try:
                await ctx.footer.set_service_thumbnail(service_name, _clean_opt(thumbnail))
            except InvalidFooterThumbnailError as exc:
                await _send_legacy(interaction, ctx, top_level="embed", path_parts=["footer", "template_service_set"], entries=[("Reason", str(exc))], tone="error", service_name="status")
                return
        service_thumbnail = (await ctx.footer.get_service_thumbnails()).get(service_name)
        service_phrase = (await ctx.footer.get_service_phrases()).get(service_name)
        await _send_legacy(
            interaction,
            ctx,
            top_level="embed",
            path_parts=["footer", "template_service_set"],
            entries=[("Service", service_name), ("Status", "updated"), ("Phrase", _format_value(service_phrase)), ("Thumbnail", _format_value(service_thumbnail))],
            tone="success",
            service_name="status",
        )

    @footer_group.command(name="template_service_show", description="Show a service-specific footer template.")
    @app_commands.describe(service="Service name.")
    async def footer_template_service_show_command(interaction: discord.Interaction, service: str) -> None:
        if not await check_permission(interaction, "admin.footer.template_service_show", ctx):
            return
        if ctx.footer is None:
            await _send_legacy(interaction, ctx, top_level="embed", path_parts=["footer", "template_service_show"], entries=[("Reason", "Footer service is unavailable")], tone="error", service_name="status")
            return
        service_name = _clean_opt(service)
        if service_name is None:
            await _send_legacy(interaction, ctx, top_level="embed", path_parts=["footer", "template_service_show"], entries=[("Reason", "Provide a valid service name")], tone="error", service_name="status")
            return
        phrase = (await ctx.footer.get_service_phrases()).get(service_name)
        thumbnail_value = (await ctx.footer.get_service_thumbnails()).get(service_name)
        await _send_legacy(
            interaction,
            ctx,
            top_level="embed",
            path_parts=["footer", "template_service_show"],
            entries=[
                ("Service", service_name),
                ("Phrase", _format_override_value(phrase, missing="No custom override (service uses default footer behavior)")),
                ("Thumbnail", _format_override_value(thumbnail_value, missing="No custom override (service uses default footer thumbnail behavior)")),
            ],
            service_name="status",
        )

    @footer_group.command(name="template_service_reset", description="Reset a service-specific footer template.")
    @app_commands.describe(service="Service name.")
    async def footer_template_service_reset_command(interaction: discord.Interaction, service: str) -> None:
        if not await check_permission(interaction, "admin.footer.template_service_reset", ctx):
            return
        if ctx.footer is None:
            await _send_legacy(interaction, ctx, top_level="embed", path_parts=["footer", "template_service_reset"], entries=[("Reason", "Footer service is unavailable")], tone="error", service_name="status")
            return
        service_name = _clean_opt(service)
        if service_name is None:
            await _send_legacy(interaction, ctx, top_level="embed", path_parts=["footer", "template_service_reset"], entries=[("Reason", "Provide a valid service name")], tone="error", service_name="status")
            return
        await ctx.footer.set_service_phrase(service_name, None)
        await ctx.footer.set_service_thumbnail(service_name, None)
        await _send_embed_response(
            interaction,
            ctx,
            subcommand_path="footer template_service_reset",
            lines=[("service", service_name), ("result", "reset")],
            kind="success",
        )

    @footer_group.command(name="status", description="Show footer status and rendered variants.")
    async def footer_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "admin.footer.status", ctx):
            return
        if ctx.footer is None:
            await _send_legacy(interaction, ctx, top_level="embed", path_parts=["footer", "status"], entries=[("Reason", "Footer service is unavailable")], tone="error", service_name="status")
            return

        enabled = await ctx.footer.is_enabled()
        service_phrases = await ctx.footer.get_service_phrases()
        global_phrase = await ctx.footer.get_global_phrase()
        known_services = await ctx.footer.get_known_services()
        service_sources = await ctx.footer.get_known_service_sources()
        all_variants = await ctx.footer.get_all_service_footer_variants()
        profile_map = await ctx.footer.get_service_footer_profiles()

        if not known_services:
            await _send_legacy(interaction, ctx, top_level="embed", path_parts=["footer", "status"], entries=[("Reason", "No known footer services")], tone="warning", service_name="status")
            return

        services = sorted(set(known_services), key=lambda name: (_service_section(name), name))
        sections: dict[str, list[str]] = {
            "Standard services": [],
            "Editorial campaigns": [],
            "Prompt campaigns": [],
            "Timer campaigns": [],
        }
        minimal_services: list[str] = []

        for service_name in services:
            if not _is_persistable_service_name(service_name):
                continue
            variants = all_variants.get(service_name, {})
            if not variants:
                profile = profile_map.get(service_name)
                if profile is None:
                    profile = await _infer_service_profile(service_name, ctx)
                footer_text, _ = await ctx.footer.render_footer(
                    service_name=service_name,
                    contributors=profile.contributors,
                    used_local_processing=profile.used_local_processing,
                )
                phrase = service_phrases.get(service_name) or global_phrase or "(none)"
                origins = sorted(set(service_sources.get(service_name, [])) | set(profile.origins or set()))
                minimal_services.append(
                    f"**{service_name}**\n"
                    f"label: {_human_service_name(service_name)}\n"
                    f"technical alias: `{service_name}`\n"
                    f"→ {footer_text}\n"
                    f"phrase: {phrase}\n"
                    f"origin: {','.join(origins) if origins else '(n/a)'}"
                )
                continue

            variant_blocks: list[str] = []
            for variant in sorted(variants.values(), key=lambda item: item.variant_key):
                phrase = service_phrases.get(service_name) or global_phrase or "(none)"
                variant_blocks.append(_format_variant_block(service_name, variant, phrase))

            service_block = f"{_format_service_header(service_name)}\n\n" + "\n\n".join(variant_blocks)
            section_idx = _service_section(service_name)
            if section_idx == 1:
                sections["Editorial campaigns"].append(service_block)
            elif section_idx == 2:
                sections["Prompt campaigns"].append(service_block)
            elif section_idx == 3:
                sections["Timer campaigns"].append(service_block)
            else:
                sections["Standard services"].append(service_block)

        lines: list[str] = [f"Footer rendering: {'on' if enabled else 'off'}"]
        for title in ["Standard services", "Editorial campaigns", "Prompt campaigns", "Timer campaigns"]:
            blocks = sections[title]
            if blocks:
                lines.append(f"__{title}__\n" + "\n\n".join(blocks))
        if minimal_services:
            lines.append("__Services without persisted footer variants__\n" + "\n\n".join(minimal_services))

        chunks = _chunk_status_blocks(lines, max_len=1900)
        if not chunks:
            await _send_legacy(interaction, ctx, top_level="embed", path_parts=["footer", "status"], entries=[("Reason", "No footer data available")], tone="warning", service_name="status")
            return

        sections_payload = [CommandEmbedSection(title="Details", lines=[("status", chunk)]) for chunk in chunks]
        await _send_embed_response(interaction, ctx, subcommand_path="footer status", lines=[("footer_rendering", "on" if enabled else "off")], sections=sections_payload)
