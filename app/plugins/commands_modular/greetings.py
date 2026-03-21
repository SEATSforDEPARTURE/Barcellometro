from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.services.discord_embed_utils import FIELD_MAX
from app.services.greetings_copy_service import GreetingsCopyService
from app.shared.discord.command_embeds import CommandEmbedSection, build_command_embeds, send_command_embeds, send_standard_response

PERM = "mod"
TEMPLATE_FIELDS = {
    "inactivity": "template_inactivity_reason",
    "kick": "template_kick_reason",
    "ban": "template_ban_reason",
    "tempban": "template_tempban_reason",
    "grace": "template_grace_reason",
}
TEMPLATE_CHOICES = ", ".join(TEMPLATE_FIELDS)
_TEMPLATE_LABELS = {
    "inactivity": "Inactivity",
    "kick": "Kick",
    "ban": "Ban",
    "tempban": "Tempban",
    "grace": "Grace",
}


def resolve_greetings_template_field(template_type: str) -> str | None:
    return TEMPLATE_FIELDS.get(template_type.strip().lower())


async def _ensure_cfg(ctx: CommandContext, guild_id: str) -> dict[str, Any]:
    if await ctx.database.get_inactivity_config(guild_id) is None:
        await ctx.database.upsert_inactivity_config(guild_id)
    cfg = await ctx.database.get_inactivity_config(guild_id)
    return dict(cfg) if cfg else {}


async def render_greetings_template(
    ctx: CommandContext,
    guild_id: str,
    template_key: str,
    *,
    user: discord.abc.User | discord.Member | Any,
    guild: discord.Guild | Any,
    moderator: discord.abc.User | discord.Member | None,
    reason: str | None = None,
    duration_seconds: int | None = None,
    expires_at: datetime | None = None,
    days_inactive: int | None = None,
    inactivity_text: str | None = None,
) -> str:
    templates = await ctx.database.get_moderation_templates(guild_id)
    template = str(templates.get(template_key) or "")
    copy_service = GreetingsCopyService(ctx.database, barcello_service=getattr(ctx, "barcello_service", None))
    rendered, _ = await copy_service.render_moderation_preview(
        template=template,
        event_type_key="inactive_kick" if template_key == "template_inactivity_reason" else template_key.removeprefix("template_").removesuffix("_reason"),
        user=user,
        guild=guild,
        moderator=moderator,
        reason=reason,
        duration_seconds=duration_seconds,
        expires_at=expires_at,
        rejoin_link=(await _ensure_cfg(ctx, guild_id)).get("invite_url"),
        days_inactive=days_inactive,
        inactivity_text=inactivity_text,
    )
    return rendered


async def _render_preview(
    ctx: CommandContext,
    interaction: discord.Interaction,
    template_type: str,
) -> tuple[str, str]:
    guild_id = str(interaction.guild_id)
    field_name = resolve_greetings_template_field(template_type)
    if field_name is None:
        raise ValueError(f"Invalid type. Use {TEMPLATE_CHOICES}.")

    now = datetime.now(timezone.utc)
    duration_seconds = 7 * 86400 if template_type in {"tempban", "grace"} else None
    expires_at = now + timedelta(seconds=duration_seconds) if duration_seconds else None
    preview_user = SimpleNamespace(
        id=42,
        name="new_user",
        display_name="New User",
        mention="<@42>",
    )
    preview_guild = interaction.guild or SimpleNamespace(id=interaction.guild_id or 0, name="Barcellometro")
    rendered = await render_greetings_template(
        ctx,
        guild_id,
        field_name,
        user=preview_user,
        guild=preview_guild,
        moderator=interaction.user,
        duration_seconds=duration_seconds,
        expires_at=expires_at,
        days_inactive=30 if template_type == "inactivity" else None,
        inactivity_text="30 days" if template_type == "inactivity" else None,
    )
    templates = await ctx.database.get_moderation_templates(guild_id)
    return templates.get(field_name) or "not set", rendered


def register_greetings(greetings_group: app_commands.Group, ctx: CommandContext) -> None:
    async def _ensure(interaction: discord.Interaction) -> bool:
        return await check_permission(interaction, PERM, ctx)

    async def _send(
        interaction: discord.Interaction,
        *,
        subcommand_path: str,
        subtitle_args: list[object] | None = None,
        lines: list[tuple[str, object]] | None = None,
        sections: list[CommandEmbedSection] | None = None,
        kind: str = "info",
        footer_service: object | None = None,
    ) -> None:
        await send_standard_response(
            interaction,
            top_level="admin",
            subcommand_path=subcommand_path,
            visual_top_level="greetings",
            subtitle_args=subtitle_args,
            lines=lines,
            sections=sections,
            kind=kind,
            footer_service=ctx.footer if footer_service is None else footer_service,
        )

    async def _send_status(interaction: discord.Interaction) -> None:
        templates = await ctx.database.get_moderation_templates(str(interaction.guild_id))
        notify_channel_id = templates.get("notify_channel_id")
        await _send(
            interaction,
            subcommand_path="greetings status",
            lines=[
                ("enabled", "on" if bool(notify_channel_id) else "off"),
                ("notify_channel", f"<#{notify_channel_id}>" if notify_channel_id else "not set"),
                ("user_card", "on" if bool(int(templates.get("notify_card_enabled") or 0)) else "off"),
            ],
        )

    @greetings_group.command(name="on", description="Enable greetings notifications for a channel.")
    @app_commands.describe(channel="Optional text channel. Defaults to the current channel.")
    async def greetings_on(interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        target_channel = channel
        if target_channel is None and isinstance(interaction.channel, discord.TextChannel):
            target_channel = interaction.channel
        if target_channel is None:
            await _send(interaction, subcommand_path="greetings on", lines=[("error", "Select a text channel first.")], kind="error", footer_service=ctx.footer)
            return
        await ctx.database.set_notify_channel(str(interaction.guild_id), str(target_channel.id))
        await _send(
            interaction,
            subcommand_path="greetings on",
            subtitle_args=[target_channel],
            lines=[("channel", target_channel.mention), ("result", "enabled")],
            kind="success",
            footer_service=ctx.footer,
        )

    @greetings_group.command(name="off", description="Disable greetings notifications.")
    async def greetings_off(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), notify_channel_id=None)
        await _send(interaction, subcommand_path="greetings off", lines=[("result", "disabled")], kind="success", footer_service=ctx.footer)

    @greetings_group.command(name="status", description="Show the greetings configuration status.")
    async def greetings_status(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _send_status(interaction)

    @greetings_group.command(name="notify_set", description="Set the greetings notification channel.")
    @app_commands.describe(channel="Text channel used for greetings notifications.")
    async def greetings_notify_set(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.set_notify_channel(str(interaction.guild_id), str(channel.id))
        await _send(
            interaction,
            subcommand_path="greetings notify_set",
            subtitle_args=[channel],
            lines=[("channel", channel.mention), ("result", "updated")],
            kind="success",
            footer_service=ctx.footer,
        )

    @greetings_group.command(name="notify_show", description="Show the greetings notification channel.")
    async def greetings_notify_show(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        templates = await ctx.database.get_moderation_templates(str(interaction.guild_id))
        notify_channel_id = templates.get("notify_channel_id")
        await _send(interaction, subcommand_path="greetings notify_show", lines=[("notify_channel", f"<#{notify_channel_id}>" if notify_channel_id else "not set")], footer_service=ctx.footer)

    @greetings_group.command(name="notify_reset", description="Reset the greetings notification channel.")
    async def greetings_notify_reset(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), notify_channel_id=None)
        await _send(interaction, subcommand_path="greetings notify_reset", lines=[("result", "reset")], kind="success", footer_service=ctx.footer)

    @greetings_group.command(name="template_set", description="Set a greetings template.")
    @app_commands.describe(type="Template type: inactivity, kick, ban, tempban, or grace.", text="Custom greeting template text.")
    async def greetings_template_set(interaction: discord.Interaction, type: str, text: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        field_name = resolve_greetings_template_field(type)
        if field_name is None:
            await _send(interaction, subcommand_path="greetings template_set", lines=[("error", f"Invalid type. Use {TEMPLATE_CHOICES}.")], kind="error", footer_service=ctx.footer)
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), **{field_name: text})
        await _send(interaction, subcommand_path="greetings template_set", subtitle_args=[type], lines=[("type", type), ("result", "updated")], kind="success", footer_service=ctx.footer)

    @greetings_group.command(name="template_show", description="Show greetings templates.")
    @app_commands.describe(type="Optional template type: inactivity, kick, ban, tempban, or grace.")
    async def greetings_template_show(interaction: discord.Interaction, type: str | None = None) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        if type:
            if resolve_greetings_template_field(type) is None:
                await _send(interaction, subcommand_path="greetings template_show", lines=[("error", f"Invalid type. Use {TEMPLATE_CHOICES}.")], kind="error", footer_service=ctx.footer)
                return
            try:
                configured_template, rendered_preview = await _render_preview(ctx, interaction, type)
            except ValueError as exc:
                await _send(interaction, subcommand_path="greetings template_show", lines=[("error", str(exc))], kind="error", footer_service=ctx.footer)
                return
            attachments: list[str] = []
            sections = [
                CommandEmbedSection(title="Template", lines=[configured_template[:FIELD_MAX]]),
                CommandEmbedSection(title="Preview", lines=[rendered_preview[:FIELD_MAX]]),
            ]
            if len(configured_template) > FIELD_MAX:
                attachments.append(f"## Template\n{configured_template}")
            if len(rendered_preview) > FIELD_MAX:
                attachments.append(f"## Preview\n{rendered_preview}")
            files = None
            if attachments:
                payload = "\n\n".join(attachments).encode("utf-8")
                files = [discord.File(io.BytesIO(payload), filename=f"greetings_template_show_{type}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.txt")]
            embeds = await build_command_embeds(
                top_level="admin",
                visual_top_level="greetings",
                subcommand_path="greetings template_show",
                subtitle_args=[type],
                sections=sections,
                footer_service=ctx.footer,
            )
            await send_command_embeds(interaction, embeds=embeds, ephemeral=True, files=files)
            return
        templates = await ctx.database.get_moderation_templates(str(interaction.guild_id))
        sections_data = [(_TEMPLATE_LABELS[name], str(templates[field_name]) or "not set") for name, field_name in TEMPLATE_FIELDS.items()]
        extra = "\n\n".join(f"## {name}\n{value}" for name, value in sections_data if len(value) > FIELD_MAX)
        files = None
        if extra:
            payload = extra.encode("utf-8")
            files = [discord.File(io.BytesIO(payload), filename=f"greetings_template_show_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.txt")]
        embeds = await build_command_embeds(
            top_level="admin",
            visual_top_level="greetings",
            subcommand_path="greetings template_show",
            sections=[CommandEmbedSection(title="Templates", lines=sections_data)],
            footer_service=ctx.footer,
        )
        await send_command_embeds(interaction, embeds=embeds, ephemeral=True, files=files)

    @greetings_group.command(name="template_reset", description="Reset a greetings template.")
    @app_commands.describe(type="Template type to reset: inactivity, kick, ban, tempban, or grace.")
    async def greetings_template_reset(interaction: discord.Interaction, type: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        field_name = resolve_greetings_template_field(type)
        if field_name is None:
            await _send(interaction, subcommand_path="greetings template_reset", lines=[("error", f"Invalid type. Use {TEMPLATE_CHOICES}.")], kind="error", footer_service=ctx.footer)
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), **{field_name: None})
        await _send(interaction, subcommand_path="greetings template_reset", subtitle_args=[type], lines=[("type", type), ("result", "reset")], kind="success", footer_service=ctx.footer)

    @greetings_group.command(name="user_card_set", description="Set whether greetings notifications include the user card.")
    @app_commands.describe(enabled="Whether the greetings notification user card is enabled.")
    async def greetings_user_card_set(interaction: discord.Interaction, enabled: bool) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.set_notify_card_enabled(str(interaction.guild_id), enabled)
        await _send(interaction, subcommand_path="greetings user_card_set", lines=[("user_card", "enabled" if enabled else "disabled")], kind="success", footer_service=ctx.footer)

    @greetings_group.command(name="user_card_show", description="Show whether the greetings notification user card is enabled.")
    async def greetings_user_card_show(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        templates = await ctx.database.get_moderation_templates(str(interaction.guild_id))
        enabled = bool(int(templates.get("notify_card_enabled") or 0))
        await _send(interaction, subcommand_path="greetings user_card_show", lines=[("user_card", "on" if enabled else "off")], footer_service=ctx.footer)

    @greetings_group.command(name="user_card_reset", description="Reset the greetings notification user card setting.")
    async def greetings_user_card_reset(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.set_notify_card_enabled(str(interaction.guild_id), False)
        await _send(interaction, subcommand_path="greetings user_card_reset", lines=[("result", "reset")], kind="success", footer_service=ctx.footer)
