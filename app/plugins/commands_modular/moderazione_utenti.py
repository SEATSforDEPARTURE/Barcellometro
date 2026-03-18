from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands

from app.plugins.commands_modular.command_helpers import describe_placeholders
from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.services.discord_embed_utils import FIELD_MAX, truncate
from app.services.footer import attach_footer_meta, attach_footer_meta_to_all
from app.utils.command_embeds import CommandEmbedSection, build_command_embeds, send_command_embeds, send_standard_response
from app.services.member_flow_notifications import (
    build_template_context,
    format_duration_human,
    parse_duration_input,
    render_moderation_template,
)

PERM = "mod"
LEGACY_PERMISSION_ALIASES = ("moderazione.utenti",)
TEMPLATE_HELP = f"Supported placeholders: {describe_placeholders()}"
TEMPLATE_FIELDS = {
    "inactivity": "template_inactivity_reason",
    "kick": "template_kick_reason",
    "ban": "template_ban_reason",
    "tempban": "template_tempban_reason",
    "grace": "template_grace_reason",
}


def _ensure_embed_lines(title: str, lines: list[str]) -> list[discord.Embed]:
    if not lines:
        embed = discord.Embed(title=title, description="No results.", colour=discord.Colour.blue())
        attach_footer_meta(embed, service_name="moderazione_utenti", used_local_processing=True)
        return [embed]
    chunks: list[str] = []
    current = ""
    for line in lines:
        add = line if not current else f"\n{line}"
        if len(current) + len(add) > 3900:
            chunks.append(current)
            current = line
        else:
            current += add
    if current:
        chunks.append(current)
    embeds = [
        discord.Embed(
            title=f"{title} ({idx}/{len(chunks)})" if len(chunks) > 1 else title,
            description=chunk,
            colour=discord.Colour.blue(),
        )
        for idx, chunk in enumerate(chunks, start=1)
    ]
    attach_footer_meta_to_all(embeds, service_name="moderazione_utenti", used_local_processing=True)
    return embeds


async def _send_lines(interaction: discord.Interaction, *, title: str, lines: list[str], prefix: str) -> None:
    payload = "\n".join(lines) if lines else "No results."
    txt = discord.File(
        io.BytesIO(payload.encode("utf-8")),
        filename=f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.txt",
    )
    embeds = _ensure_embed_lines(title, lines)
    await interaction.response.send_message(embeds=embeds, ephemeral=True, file=txt)


def register_moderazione_utenti(mod_group: app_commands.Group, ctx: CommandContext) -> None:
    channel_group = app_commands.Group(name="channel", description="Moderation notification channel settings")
    users_group = app_commands.Group(name="users", description="Moderation actions for users")
    mod_group.add_command(channel_group)
    mod_group.add_command(users_group)

    async def _ensure(interaction: discord.Interaction) -> bool:
        return await check_permission(interaction, PERM, ctx, legacy_aliases=LEGACY_PERMISSION_ALIASES)

    async def _ensure_cfg(guild_id: str) -> dict:
        if await ctx.database.get_inactivity_config(guild_id) is None:
            await ctx.database.upsert_inactivity_config(guild_id)
        cfg = await ctx.database.get_inactivity_config(guild_id)
        return dict(cfg) if cfg else {}

    async def _default_reason(
        guild_id: str,
        template_key: str,
        *,
        user: discord.abc.User | discord.Member,
        guild: discord.Guild,
        moderator: discord.abc.User | discord.Member | None,
        duration_seconds: int | None = None,
        expires_at: datetime | None = None,
    ) -> str:
        templates = await ctx.database.get_moderation_templates(guild_id)
        template = str(templates.get(template_key) or "")
        context = build_template_context(
            user=user,
            guild=guild,
            moderator=moderator,
            duration_seconds=duration_seconds,
            expires_at=expires_at,
            rejoin_link=(await _ensure_cfg(guild_id)).get("invite_url"),
        )
        return render_moderation_template(template, **context)

    def _resolve_template_field(template_name: str) -> str | None:
        return TEMPLATE_FIELDS.get(template_name.strip().lower())

    async def _send_channel_status(interaction: discord.Interaction) -> None:
        templates = await ctx.database.get_moderation_templates(str(interaction.guild_id))
        notify_channel_id = templates.get("notify_channel_id")
        message = (
            f"enabled={'on' if bool(notify_channel_id) else 'off'}\n"
            f"notify_channel={f'<#{notify_channel_id}>' if notify_channel_id else 'not set'}\n"
            f"user_card={'on' if bool(int(templates.get('notify_card_enabled') or 0)) else 'off'}"
        )
        await send_standard_response(interaction, top_level="bm", subcommand_path="moderazione channel status", lines=[("enabled", "on" if bool(notify_channel_id) else "off"), ("notify_channel", f"<#{notify_channel_id}>" if notify_channel_id else "not set"), ("user_card", "on" if bool(int(templates.get('notify_card_enabled') or 0)) else "off")], footer_service=ctx.footer)

    @channel_group.command(name="on", description="Enable moderation notifications for a channel.")
    @app_commands.describe(channel="Optional text channel. Defaults to the current channel.")
    async def mod_channel_on(interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        target_channel = channel
        if target_channel is None and isinstance(interaction.channel, discord.TextChannel):
            target_channel = interaction.channel
        if target_channel is None:
            await send_standard_response(interaction, top_level="bm", subcommand_path="moderazione channel on", lines=[("error", "Select a text channel first.")], kind="error", footer_service=ctx.footer)
            return
        await ctx.database.set_notify_channel(str(interaction.guild_id), str(target_channel.id))
        await send_standard_response(interaction, top_level="bm", subcommand_path="moderazione channel on", lines=[("channel", target_channel.mention), ("result", "enabled")], kind="success", footer_service=ctx.footer)

    @channel_group.command(name="off", description="Disable moderation notifications for the channel setting.")
    async def mod_channel_off(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), notify_channel_id=None)
        await send_standard_response(interaction, top_level="bm", subcommand_path="moderazione channel off", lines=[("result", "disabled")], kind="success", footer_service=ctx.footer)

    @channel_group.command(name="status", description="Show the moderation channel configuration status.")
    async def mod_channel_status(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _send_channel_status(interaction)

    @channel_group.command(name="notify_set", description="Set the moderation notification channel.")
    @app_commands.describe(channel="Text channel used for moderation notifications.")
    async def mod_channel_notify_set(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.set_notify_channel(str(interaction.guild_id), str(channel.id))
        await send_standard_response(interaction, top_level="bm", subcommand_path="moderazione channel notify_set", lines=[("channel", channel.mention), ("result", "updated")], kind="success", footer_service=ctx.footer)

    @channel_group.command(name="notify_show", description="Show the moderation notification channel.")
    async def mod_channel_notify_show(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        templates = await ctx.database.get_moderation_templates(str(interaction.guild_id))
        notify_channel_id = templates.get("notify_channel_id")
        await send_standard_response(interaction, top_level="bm", subcommand_path="moderazione channel notify_show", lines=[("notify_channel", f"<#{notify_channel_id}>" if notify_channel_id else "not set")], footer_service=ctx.footer)

    @channel_group.command(name="notify_reset", description="Reset the moderation notification channel.")
    async def mod_channel_notify_reset(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), notify_channel_id=None)
        await send_standard_response(interaction, top_level="bm", subcommand_path="moderazione channel notify_reset", lines=[("result", "reset")], kind="success", footer_service=ctx.footer)

    @channel_group.command(name="template_set", description="Set a moderation notification template.")
    @app_commands.describe(template_name="Template target: inactivity, kick, ban, tempban, or grace.", text=TEMPLATE_HELP)
    async def mod_channel_template_set(interaction: discord.Interaction, template_name: str, text: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        field_name = _resolve_template_field(template_name)
        if field_name is None:
            await send_standard_response(interaction, top_level="bm", subcommand_path="moderazione channel template_reset", lines=[("error", "Invalid template_name. Use inactivity, kick, ban, tempban, or grace.")], kind="error", footer_service=ctx.footer)
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), **{field_name: text})
        await send_standard_response(interaction, top_level="bm", subcommand_path="moderazione channel template_set", lines=[("template_name", template_name), ("result", "updated")], kind="success", footer_service=ctx.footer)

    @channel_group.command(name="template_show", description="Show moderation notification templates.")
    @app_commands.describe(template_name="Optional template target: inactivity, kick, ban, tempban, or grace.")
    async def mod_channel_template_show(interaction: discord.Interaction, template_name: str | None = None) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        templates = await ctx.database.get_moderation_templates(str(interaction.guild_id))
        if template_name:
            field_name = _resolve_template_field(template_name)
            if field_name is None:
                await send_standard_response(interaction, top_level="bm", subcommand_path="moderazione channel template_reset", lines=[("error", "Invalid template_name. Use inactivity, kick, ban, tempban, or grace.")], kind="error", footer_service=ctx.footer)
                return
            await send_standard_response(interaction, top_level="bm", subcommand_path="moderazione channel template_show", lines=[("template_name", template_name), ("value", templates.get(field_name) or "not set")], footer_service=ctx.footer)
            return
        sections_data = [("Inactivity", str(templates["template_inactivity_reason"]) or "not set"), ("Kick", str(templates["template_kick_reason"]) or "not set"), ("Ban", str(templates["template_ban_reason"]) or "not set"), ("Tempban", str(templates["template_tempban_reason"]) or "not set"), ("Grace", str(templates["template_grace_reason"]) or "not set")]
        extra = "\n\n".join(f"## {name}\n{value}" for name, value in sections_data if len(value) > FIELD_MAX)
        files = None
        if extra:
            payload = extra.encode("utf-8")
            files = [discord.File(io.BytesIO(payload), filename=f"mod_channel_template_show_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.txt")]
        embeds = await build_command_embeds(top_level="bm", subcommand_path="moderazione channel template_show", sections=[CommandEmbedSection(title="Templates", lines=sections_data)], footer_service=ctx.footer)
        await send_command_embeds(interaction, embeds=embeds, ephemeral=True, files=files)

    @channel_group.command(name="template_reset", description="Reset a moderation notification template.")
    @app_commands.describe(template_name="Template target: inactivity, kick, ban, tempban, or grace.")
    async def mod_channel_template_reset(interaction: discord.Interaction, template_name: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        field_name = _resolve_template_field(template_name)
        if field_name is None:
            await send_standard_response(interaction, top_level="bm", subcommand_path="moderazione channel template_reset", lines=[("error", "Invalid template_name. Use inactivity, kick, ban, tempban, or grace.")], kind="error", footer_service=ctx.footer)
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), **{field_name: None})
        await send_standard_response(interaction, top_level="bm", subcommand_path="moderazione channel template_reset", lines=[("template_name", template_name), ("result", "reset")], kind="success", footer_service=ctx.footer)

    @channel_group.command(name="user_card_set", description="Set whether moderation notifications include the user card.")
    @app_commands.describe(enabled="Whether the moderation notification user card is enabled.")
    async def mod_channel_user_card_set(interaction: discord.Interaction, enabled: bool) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.set_notify_card_enabled(str(interaction.guild_id), enabled)
        await send_standard_response(interaction, top_level="bm", subcommand_path="moderazione channel user_card_set", lines=[("user_card", "enabled" if enabled else "disabled")], kind="success", footer_service=ctx.footer)

    @channel_group.command(name="user_card_show", description="Show whether the moderation notification user card is enabled.")
    async def mod_channel_user_card_show(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        templates = await ctx.database.get_moderation_templates(str(interaction.guild_id))
        enabled = bool(int(templates.get("notify_card_enabled") or 0))
        await send_standard_response(interaction, top_level="bm", subcommand_path="moderazione channel user_card_show", lines=[("user_card", "on" if enabled else "off")], footer_service=ctx.footer)

    @channel_group.command(name="user_card_reset", description="Reset the moderation notification user card setting.")
    async def mod_channel_user_card_reset(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.set_notify_card_enabled(str(interaction.guild_id), False)
        await send_standard_response(interaction, top_level="bm", subcommand_path="moderazione channel user_card_reset", lines=[("result", "reset")], kind="success", footer_service=ctx.footer)

    async def _notify_action(
        *,
        guild: discord.Guild,
        user: discord.abc.User | discord.Member,
        action_type: str,
        reason: str,
        moderator: discord.Member | discord.User,
        duration_seconds: int | None = None,
        expires_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> None:
        if ctx.member_flow_notifications is None:
            return
        await ctx.member_flow_notifications.log_action(
            guild_id=str(guild.id),
            user_id=str(user.id),
            moderator_id=str(moderator.id),
            action_type=action_type,
            reason=reason,
            duration_seconds=duration_seconds,
            expires_at=expires_at.isoformat() if expires_at else None,
            metadata=metadata or {},
        )
        await ctx.member_flow_notifications.send_notification(
            guild=guild,
            user=user,
            action_type=action_type,
            reason=reason,
            moderator=moderator,
            duration_seconds=duration_seconds,
            expires_at=expires_at,
            metadata=metadata or {},
        )

    @users_group.command(name="kick", description="Kick a user.")
    @app_commands.describe(user="Member to kick.", reason="Optional reason override.")
    async def mod_users_kick(interaction: discord.Interaction, user: discord.Member, reason: str | None = None) -> None:
        if not await _ensure(interaction) or interaction.guild is None:
            return
        resolved_reason = reason or await _default_reason(str(interaction.guild_id), "template_kick_reason", user=user, guild=interaction.guild, moderator=interaction.user)
        await user.kick(reason=resolved_reason)
        await _notify_action(guild=interaction.guild, user=user, action_type="kick", reason=resolved_reason, moderator=interaction.user)
        embed = discord.Embed(title="✅ Kick completed", description=f"{user.mention} was removed successfully.", colour=discord.Colour.green())
        attach_footer_meta(embed, service_name="moderazione_utenti", used_local_processing=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @users_group.command(name="kick_list", description="List recent kicks.")
    async def mod_users_kick_list(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        rows = await ctx.database.list_recent_kicked_users(str(interaction.guild_id))
        lines = [f"• <@{row['user_id']}> · {row['action_type']} · {str(row['created_at'])[:16]} · {row['reason'] or 'n/a'}" for row in rows]
        await _send_lines(interaction, title="Recent kicks", lines=lines, prefix="mod_users_kick_list")

    @users_group.command(name="ban", description="Ban a user permanently.")
    @app_commands.describe(user="Member to ban.", reason="Optional reason override.")
    async def mod_users_ban(interaction: discord.Interaction, user: discord.Member, reason: str | None = None) -> None:
        if not await _ensure(interaction) or interaction.guild is None:
            return
        resolved_reason = reason or await _default_reason(str(interaction.guild_id), "template_ban_reason", user=user, guild=interaction.guild, moderator=interaction.user)
        await interaction.guild.ban(user, reason=resolved_reason, delete_message_seconds=0)
        await _notify_action(guild=interaction.guild, user=user, action_type="ban", reason=resolved_reason, moderator=interaction.user)
        embed = discord.Embed(title="✅ Ban completed", description=f"{user.mention} was permanently banned.", colour=discord.Colour.green())
        attach_footer_meta(embed, service_name="moderazione_utenti", used_local_processing=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @users_group.command(name="ban_list", description="List active permanent bans.")
    async def mod_users_ban_list(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        rows = await ctx.database.list_active_bans(str(interaction.guild_id))
        lines = [f"• <@{row['user_id']}> · ban · {str(row['created_at'])[:16]} · {row['reason'] or 'n/a'}" for row in rows]
        await _send_lines(interaction, title="Active permanent bans", lines=lines, prefix="mod_users_ban_list")

    @users_group.command(name="tempban", description="Ban a user temporarily.")
    @app_commands.describe(user="Member to ban temporarily.", duration="Duration like 7d or 12h.", reason="Optional reason override.")
    async def mod_users_tempban(interaction: discord.Interaction, user: discord.Member, duration: str, reason: str | None = None) -> None:
        if not await _ensure(interaction) or interaction.guild is None:
            return
        duration_seconds = parse_duration_input(duration)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
        resolved_reason = reason or await _default_reason(
            str(interaction.guild_id),
            "template_tempban_reason",
            user=user,
            guild=interaction.guild,
            moderator=interaction.user,
            duration_seconds=duration_seconds,
            expires_at=expires_at,
        )
        await interaction.guild.ban(user, reason=resolved_reason, delete_message_seconds=0)
        await ctx.database.add_temp_ban(str(interaction.guild.id), str(user.id), expires_at.isoformat(), resolved_reason)
        await _notify_action(guild=interaction.guild, user=user, action_type="tempban", reason=resolved_reason, moderator=interaction.user, duration_seconds=duration_seconds, expires_at=expires_at)
        embed = discord.Embed(title="✅ Tempban completed", description=f"{user.mention} was banned for {format_duration_human(duration_seconds)}.", colour=discord.Colour.green())
        attach_footer_meta(embed, service_name="moderazione_utenti", used_local_processing=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @users_group.command(name="tempban_list", description="List active temporary bans.")
    async def mod_users_tempban_list(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        rows = await ctx.database.list_active_tempbans(str(interaction.guild_id))
        lines = [f"• <@{row['user_id']}> · {row['action_type'] or 'tempban'} · expires {str(row['expires_at'])[:16]} · {row['reason'] or 'n/a'}" for row in rows]
        await _send_lines(interaction, title="Active temporary bans", lines=lines, prefix="mod_users_tempban_list")

    @users_group.command(name="grace", description="Assign a manual grace period to a user.")
    @app_commands.describe(user="Member that receives the grace period.", duration="Optional duration like 7d or 12h.", reason="Optional reason override.")
    async def mod_users_grace(interaction: discord.Interaction, user: discord.Member, duration: str | None = None, reason: str | None = None) -> None:
        if not await _ensure(interaction) or interaction.guild is None:
            return
        cfg = await _ensure_cfg(str(interaction.guild.id))
        duration_seconds = parse_duration_input(duration) if duration else int(cfg.get("grace_days_after_reminder", 7)) * 86400
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
        await ctx.database.extend_user_grace(str(interaction.guild.id), str(user.id), datetime.now(timezone.utc).isoformat())
        resolved_reason = reason or await _default_reason(
            str(interaction.guild.id),
            "template_grace_reason",
            user=user,
            guild=interaction.guild,
            moderator=interaction.user,
            duration_seconds=duration_seconds,
            expires_at=expires_at,
        )
        await _notify_action(guild=interaction.guild, user=user, action_type="grace", reason=resolved_reason, moderator=interaction.user, duration_seconds=duration_seconds, expires_at=expires_at)
        embed = discord.Embed(title="✅ Grace updated", description=f"{user.mention} is protected until {expires_at.strftime('%d/%m/%Y %H:%M UTC')}", colour=discord.Colour.green())
        attach_footer_meta(embed, service_name="moderazione_utenti", used_local_processing=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @users_group.command(name="grace_list", description="List active grace periods.")
    async def mod_users_grace_list(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        rows = await ctx.database.list_active_grace_users(str(interaction.guild_id))
        lines = [f"• <@{row['user_id']}> · {row['action_type']} · expires {str(row['expires_at'])[:16]} · {row['reason'] or 'n/a'}" for row in rows]
        await _send_lines(interaction, title="Active grace periods", lines=lines, prefix="mod_users_grace_list")
