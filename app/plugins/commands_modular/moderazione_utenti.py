from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands

from app.plugins.commands_modular.command_helpers import describe_placeholders
from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.services.discord_embed_utils import FIELD_MAX, truncate
from app.services.footer import attach_footer_meta, attach_footer_meta_to_all
from app.services.member_flow_notifications import build_template_context, parse_duration_input, render_moderation_template, format_duration_human

PERM = "moderazione.utenti"
TEMPLATE_HELP = f"Placeholder supportati: {describe_placeholders()}"


def _ensure_embed_lines(title: str, lines: list[str]) -> list[discord.Embed]:
    if not lines:
        embed = discord.Embed(title=title, description="Nessun risultato.", colour=discord.Colour.blue())
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
    embeds = [discord.Embed(title=f"{title} ({idx}/{len(chunks)})" if len(chunks) > 1 else title, description=chunk, colour=discord.Colour.blue()) for idx, chunk in enumerate(chunks, start=1)]
    attach_footer_meta_to_all(embeds, service_name="moderazione_utenti", used_local_processing=True)
    return embeds


async def _send_lines(interaction: discord.Interaction, *, title: str, lines: list[str], prefix: str) -> None:
    payload = "\n".join(lines) if lines else "Nessun risultato."
    txt = discord.File(io.BytesIO(payload.encode("utf-8")), filename=f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.txt")
    embeds = _ensure_embed_lines(title, lines)
    await interaction.response.send_message(embeds=embeds, ephemeral=True, file=txt)


def register_moderazione_utenti(moderazione_group: app_commands.Group, ctx: CommandContext) -> None:
    utenti_group = app_commands.Group(name="utenti", description="Template, notify e azioni utenti")
    moderazione_group.add_command(utenti_group)

    async def _ensure(interaction: discord.Interaction) -> bool:
        return await check_permission(interaction, PERM, ctx)

    async def _ensure_cfg(guild_id: str) -> dict:
        if await ctx.database.get_inactivity_config(guild_id) is None:
            await ctx.database.upsert_inactivity_config(guild_id)
        cfg = await ctx.database.get_inactivity_config(guild_id)
        return dict(cfg) if cfg else {}

    async def _default_reason(guild_id: str, template_key: str, *, user: discord.abc.User | discord.Member, guild: discord.Guild, moderator: discord.abc.User | discord.Member | None, duration_seconds: int | None = None, expires_at: datetime | None = None) -> str:
        templates = await ctx.database.get_moderation_templates(guild_id)
        template = str(templates.get(template_key) or "")
        context = build_template_context(user=user, guild=guild, moderator=moderator, duration_seconds=duration_seconds, expires_at=expires_at, rejoin_link=(await _ensure_cfg(guild_id)).get("invite_url"))
        return render_moderation_template(template, **context)

    @utenti_group.command(name="channel_notify_set", description="Imposta il canale notify ingressi/uscite")
    async def channel_notify_set(interaction: discord.Interaction, canale: discord.TextChannel) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.set_notify_channel(str(interaction.guild_id), str(canale.id))
        await interaction.response.send_message(f"✅ Canale notify impostato su {canale.mention}.", ephemeral=True)

    @utenti_group.command(name="tesserino", description="Abilita o disabilita il tesserino notify")
    async def tesserino(interaction: discord.Interaction, enabled: bool) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.set_notify_card_enabled(str(interaction.guild_id), enabled)
        await interaction.response.send_message(f"✅ Tesserino notify {'abilitato' if enabled else 'disabilitato'}.", ephemeral=True)

    @utenti_group.command(name="template_show", description="Mostra tutti i template notify utenti")
    async def template_show(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        templates = await ctx.database.get_moderation_templates(str(interaction.guild_id))
        embed = discord.Embed(title="🧩 Template moderazione utenti", colour=discord.Colour.blue())
        attach_footer_meta(embed, service_name="moderazione_utenti", used_local_processing=True)
        sections: list[tuple[str, str]] = [
            ("🚪 Inactivity reason", str(templates["template_inactivity_reason"])),
            ("👢 Kick reason", str(templates["template_kick_reason"])),
            ("⛔ Ban reason", str(templates["template_ban_reason"])),
            ("⏳ Tempban reason", str(templates["template_tempban_reason"])),
            ("🛟 Grace reason", str(templates["template_grace_reason"])),
            ("📩 Legacy reminder DM", str(templates.get("dm_reminder_template") or "n/d")),
            ("📨 Legacy kick DM", str(templates.get("dm_kick_template") or "n/d")),
        ]
        extra: list[str] = []
        for name, value in sections:
            if len(value) <= FIELD_MAX:
                embed.add_field(name=name, value=value or "n/d", inline=False)
            else:
                embed.add_field(name=name, value=truncate(value, FIELD_MAX), inline=False)
                extra.append(f"## {name}\n{value}")
        if extra:
            payload = "\n\n".join(extra).encode("utf-8")
            file = discord.File(io.BytesIO(payload), filename=f"template_show_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.txt")
            await interaction.response.send_message(embed=embed, ephemeral=True, file=file)
            return
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _set_template(interaction: discord.Interaction, field_name: str, testo: str, success_message: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), **{field_name: testo})
        await interaction.response.send_message(success_message, ephemeral=True)

    @utenti_group.command(name="template_inactivity_reason", description="Template notify inattività")
    async def template_inactivity_reason(interaction: discord.Interaction, testo: str) -> None:
        await _set_template(interaction, "template_inactivity_reason", testo, "✅ Template inactivity reason aggiornato.")

    @utenti_group.command(name="template_kick_reason", description="Template notify kick")
    async def template_kick_reason(interaction: discord.Interaction, testo: str) -> None:
        await _set_template(interaction, "template_kick_reason", testo, "✅ Template kick reason aggiornato.")

    @utenti_group.command(name="template_ban_reason", description="Template notify ban")
    async def template_ban_reason(interaction: discord.Interaction, testo: str) -> None:
        await _set_template(interaction, "template_ban_reason", testo, "✅ Template ban reason aggiornato.")

    @utenti_group.command(name="template_tempban_reason", description="Template notify tempban")
    async def template_tempban_reason(interaction: discord.Interaction, testo: str) -> None:
        await _set_template(interaction, "template_tempban_reason", testo, "✅ Template tempban reason aggiornato.")

    @utenti_group.command(name="template_grace_reason", description="Template notify grace")
    async def template_grace_reason(interaction: discord.Interaction, testo: str) -> None:
        await _set_template(interaction, "template_grace_reason", testo, "✅ Template grace reason aggiornato.")

    async def _notify_action(*, guild: discord.Guild, user: discord.abc.User | discord.Member, action_type: str, reason: str, moderator: discord.Member | discord.User, duration_seconds: int | None = None, expires_at: datetime | None = None, metadata: dict | None = None) -> None:
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

    @utenti_group.command(name="kick", description="Kick manuale utente")
    async def kick(interaction: discord.Interaction, utente: discord.Member, motivazione: str | None = None) -> None:
        if not await _ensure(interaction) or interaction.guild is None:
            return
        reason = motivazione or await _default_reason(str(interaction.guild_id), "template_kick_reason", user=utente, guild=interaction.guild, moderator=interaction.user)
        await utente.kick(reason=reason)
        await _notify_action(guild=interaction.guild, user=utente, action_type="kick", reason=reason, moderator=interaction.user)
        embed = discord.Embed(title="✅ Kick eseguito", description=f"{utente.mention} rimosso con successo.", colour=discord.Colour.green())
        attach_footer_meta(embed, service_name="moderazione_utenti", used_local_processing=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @utenti_group.command(name="ban", description="Ban permanente utente")
    async def ban(interaction: discord.Interaction, utente: discord.Member, motivazione: str | None = None) -> None:
        if not await _ensure(interaction) or interaction.guild is None:
            return
        reason = motivazione or await _default_reason(str(interaction.guild_id), "template_ban_reason", user=utente, guild=interaction.guild, moderator=interaction.user)
        await interaction.guild.ban(utente, reason=reason, delete_message_seconds=0)
        await _notify_action(guild=interaction.guild, user=utente, action_type="ban", reason=reason, moderator=interaction.user)
        embed = discord.Embed(title="✅ Ban eseguito", description=f"{utente.mention} bannato permanentemente.", colour=discord.Colour.green())
        attach_footer_meta(embed, service_name="moderazione_utenti", used_local_processing=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @utenti_group.command(name="tempban", description="Ban temporaneo utente")
    async def tempban(interaction: discord.Interaction, utente: discord.Member, durata: str, motivazione: str | None = None) -> None:
        if not await _ensure(interaction) or interaction.guild is None:
            return
        duration_seconds = parse_duration_input(durata)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
        reason = motivazione or await _default_reason(str(interaction.guild_id), "template_tempban_reason", user=utente, guild=interaction.guild, moderator=interaction.user, duration_seconds=duration_seconds, expires_at=expires_at)
        await interaction.guild.ban(utente, reason=reason, delete_message_seconds=0)
        await ctx.database.add_temp_ban(str(interaction.guild.id), str(utente.id), expires_at.isoformat(), reason)
        await _notify_action(guild=interaction.guild, user=utente, action_type="tempban", reason=reason, moderator=interaction.user, duration_seconds=duration_seconds, expires_at=expires_at)
        embed = discord.Embed(title="✅ Tempban eseguito", description=f"{utente.mention} bannato per {format_duration_human(duration_seconds)}.", colour=discord.Colour.green())
        attach_footer_meta(embed, service_name="moderazione_utenti", used_local_processing=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @utenti_group.command(name="grace", description="Assegna una grace manuale")
    async def grace(interaction: discord.Interaction, utente: discord.Member, durata: str | None = None, motivazione: str | None = None) -> None:
        if not await _ensure(interaction) or interaction.guild is None:
            return
        cfg = await _ensure_cfg(str(interaction.guild.id))
        duration_seconds = parse_duration_input(durata) if durata else int(cfg.get("grace_days_after_reminder", 7)) * 86400
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
        await ctx.database.extend_user_grace(str(interaction.guild.id), str(utente.id), datetime.now(timezone.utc).isoformat())
        reason = motivazione or await _default_reason(str(interaction.guild.id), "template_grace_reason", user=utente, guild=interaction.guild, moderator=interaction.user, duration_seconds=duration_seconds, expires_at=expires_at)
        await _notify_action(guild=interaction.guild, user=utente, action_type="grace", reason=reason, moderator=interaction.user, duration_seconds=duration_seconds, expires_at=expires_at)
        embed = discord.Embed(title="✅ Grace impostata", description=f"{utente.mention} in grace fino al {expires_at.strftime('%d/%m/%Y %H:%M UTC')}.", colour=discord.Colour.green())
        attach_footer_meta(embed, service_name="moderazione_utenti", used_local_processing=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @moderazione_group.command(name="tempban_users", description="Lista tempban attivi")
    async def tempban_users(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        rows = await ctx.database.list_active_tempbans(str(interaction.guild_id))
        lines = [f"• <@{row['user_id']}> · {row['action_type'] or 'tempban'} · scade {str(row['expires_at'])[:16]} · {row['reason'] or 'n/d'}" for row in rows]
        await _send_lines(interaction, title="⏳ Tempban attivi", lines=lines, prefix="tempban_users")

    @moderazione_group.command(name="grace_users", description="Lista grace attive")
    async def grace_users(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        rows = await ctx.database.list_active_grace_users(str(interaction.guild_id))
        lines = [f"• <@{row['user_id']}> · {row['action_type']} · scade {str(row['expires_at'])[:16]} · {row['reason'] or 'n/d'}" for row in rows]
        await _send_lines(interaction, title="🛟 Grace attive", lines=lines, prefix="grace_users")

    @moderazione_group.command(name="banned_users", description="Lista ban permanenti attivi")
    async def banned_users(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        rows = await ctx.database.list_active_bans(str(interaction.guild_id))
        lines = [f"• <@{row['user_id']}> · ban · {str(row['created_at'])[:16]} · {row['reason'] or 'n/d'}" for row in rows]
        await _send_lines(interaction, title="⛔ Ban permanenti", lines=lines, prefix="banned_users")

    @moderazione_group.command(name="kicked_users", description="Lista kick recenti")
    async def kicked_users(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        rows = await ctx.database.list_recent_kicked_users(str(interaction.guild_id))
        lines = [f"• <@{row['user_id']}> · {row['action_type']} · {str(row['created_at'])[:16]} · {row['reason'] or 'n/d'}" for row in rows]
        await _send_lines(interaction, title="👢 Kick recenti", lines=lines, prefix="kicked_users")
