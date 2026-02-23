from __future__ import annotations

import json

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission

PERM = "barcellometro.inattivi.config"


def _normalize_mode(mode: str) -> str:
    upper = mode.upper()
    if upper not in {"OR", "AND"}:
        raise ValueError("mode deve essere OR o AND")
    return upper


def _policy_payload(inactive_days: int, window_days: int, min_messages: int, mode: str, min_account_age_days: int) -> str:
    return json.dumps(
        {
            "inactive_days": int(inactive_days),
            "window_days": int(window_days),
            "min_messages": int(min_messages),
            "mode": _normalize_mode(mode),
            "min_account_age_days": int(min_account_age_days),
        }
    )


async def _ensure_cfg(ctx: CommandContext, guild_id: str) -> None:
    if await ctx.database.get_inactivity_config(guild_id) is None:
        await ctx.database.upsert_inactivity_config(guild_id)


def register_inattivi(inattivi_group: app_commands.Group, ctx: CommandContext) -> None:
    async def _ensure(interaction: discord.Interaction) -> bool:
        return await check_permission(interaction, PERM, ctx)

    @inattivi_group.command(name="on", description="Abilita gestione inattivi")
    async def inattivi_on(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.set_inactivity_enabled(str(interaction.guild_id), True)
        await interaction.response.send_message("✅ Gestione inattivi abilitata.", ephemeral=True)

    @inattivi_group.command(name="off", description="Disabilita gestione inattivi")
    async def inattivi_off(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.set_inactivity_enabled(str(interaction.guild_id), False)
        await interaction.response.send_message("🛑 Gestione inattivi disabilitata.", ephemeral=True)

    @inattivi_group.command(name="status", description="Stato gestione inattivi")
    async def inattivi_status(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        guild_id = str(interaction.guild_id)
        cfg = await ctx.database.get_inactivity_config(guild_id)
        if cfg is None:
            await interaction.response.send_message("Nessuna configurazione inattivi presente.", ephemeral=True)
            return
        policies = await ctx.database.list_inactivity_role_policies(guild_id)
        await interaction.response.send_message(
            f"enabled={'on' if cfg['enabled'] else 'off'} | auto={'on' if cfg['auto_enabled'] else 'off'} | grace={cfg['grace_days_after_reminder']} | "
            f"cooldown={cfg['reminder_cooldown_days']} | ban_days={cfg['ban_days']} | atrio={cfg['atrio_channel_id'] or 'n/d'} | "
            f"invite={cfg['invite_url'] or 'n/d'} | role_policies={len(policies)}",
            ephemeral=True,
        )

    auto_group = app_commands.Group(name="auto", description="Modalità automatica")

    @auto_group.command(name="on", description="Abilita modalità automatica")
    async def inattivi_auto_on(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.set_inactivity_auto_enabled(str(interaction.guild_id), True)
        await interaction.response.send_message("✅ Auto inattivi ON.", ephemeral=True)

    @auto_group.command(name="off", description="Disabilita modalità automatica")
    async def inattivi_auto_off(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.set_inactivity_auto_enabled(str(interaction.guild_id), False)
        await interaction.response.send_message("🛑 Auto inattivi OFF.", ephemeral=True)

    inattivi_group.add_command(auto_group)

    @inattivi_group.command(name="grace", description="Imposta grace days")
    async def inattivi_grace(interaction: discord.Interaction, giorni: app_commands.Range[int, 1, 365]) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), grace_days_after_reminder=int(giorni))
        await interaction.response.send_message("✅ Aggiornato.", ephemeral=True)

    @inattivi_group.command(name="reminder-cooldown", description="Imposta reminder cooldown")
    async def inattivi_reminder_cooldown(interaction: discord.Interaction, giorni: app_commands.Range[int, 1, 365]) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), reminder_cooldown_days=int(giorni))
        await interaction.response.send_message("✅ Aggiornato.", ephemeral=True)

    @inattivi_group.command(name="ban-days", description="Imposta durata ban")
    async def inattivi_ban_days(interaction: discord.Interaction, giorni: app_commands.Range[int, 1, 365]) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), ban_days=int(giorni))
        await interaction.response.send_message("✅ Aggiornato.", ephemeral=True)

    invite_group = app_commands.Group(name="invite", description="Gestione invite")
    atrio_group = app_commands.Group(name="atrio", description="Gestione atrio")
    exclude_role_group = app_commands.Group(name="exclude-role", description="Ruoli esclusi")
    default_group = app_commands.Group(name="default", description="Policy default")
    role_group = app_commands.Group(name="role", description="Policy ruoli")
    template_group = app_commands.Group(name="template", description="Template messaggi")
    reminder_group = app_commands.Group(name="reminder", description="Template reminder")
    kick_group = app_commands.Group(name="kick", description="Template kick")
    atrio_template_group = app_commands.Group(name="atrio", description="Template atrio")

    @invite_group.command(name="set", description="Imposta invite url")
    async def inattivi_invite_set(interaction: discord.Interaction, url: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), invite_url=url)
        await interaction.response.send_message("✅ Invite impostato.", ephemeral=True)

    @atrio_group.command(name="set", description="Imposta canale atrio")
    async def inattivi_atrio_set(interaction: discord.Interaction, canale: discord.TextChannel) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), atrio_channel_id=str(canale.id))
        await interaction.response.send_message("✅ Atrio impostato.", ephemeral=True)

    @exclude_role_group.command(name="add", description="Aggiungi ruolo escluso")
    async def inattivi_exclude_role_add(interaction: discord.Interaction, ruolo: discord.Role) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        guild_id = str(interaction.guild_id)
        await _ensure_cfg(ctx, guild_id)
        cfg = await ctx.database.get_inactivity_config(guild_id)
        current = set(json.loads(cfg["excluded_role_ids_json"] or "[]")) if cfg else set()
        current.add(str(ruolo.id))
        await ctx.database.upsert_inactivity_config(guild_id, excluded_role_ids_json=json.dumps(sorted(current)))
        await interaction.response.send_message("✅ Ruolo escluso.", ephemeral=True)

    @exclude_role_group.command(name="remove", description="Rimuovi ruolo escluso")
    async def inattivi_exclude_role_remove(interaction: discord.Interaction, ruolo: discord.Role) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        guild_id = str(interaction.guild_id)
        await _ensure_cfg(ctx, guild_id)
        cfg = await ctx.database.get_inactivity_config(guild_id)
        current = set(json.loads(cfg["excluded_role_ids_json"] or "[]")) if cfg else set()
        current.discard(str(ruolo.id))
        await ctx.database.upsert_inactivity_config(guild_id, excluded_role_ids_json=json.dumps(sorted(current)))
        await interaction.response.send_message("✅ Ruolo rimosso.", ephemeral=True)

    @default_group.command(name="set", description="Imposta policy default")
    async def inattivi_default_set(interaction: discord.Interaction, inactive_days: int, window_days: int, min_messages: int, mode: str, min_account_age_days: int = 0) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        try:
            payload = _policy_payload(inactive_days, window_days, min_messages, mode, min_account_age_days)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), default_policy_json=payload)
        await interaction.response.send_message("✅ Policy default aggiornata.", ephemeral=True)

    @role_group.command(name="set", description="Imposta policy ruolo")
    async def inattivi_role_set(interaction: discord.Interaction, role: discord.Role, inactive_days: int, window_days: int, min_messages: int, mode: str, min_account_age_days: int = 0, priority: int = 0) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        try:
            payload = _policy_payload(inactive_days, window_days, min_messages, mode, min_account_age_days)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await ctx.database.upsert_inactivity_role_policy(str(interaction.guild_id), str(role.id), payload, int(priority))
        await interaction.response.send_message("✅ Policy ruolo aggiornata.", ephemeral=True)

    @role_group.command(name="del", description="Rimuovi policy ruolo")
    async def inattivi_role_del(interaction: discord.Interaction, role: discord.Role) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.delete_inactivity_role_policy(str(interaction.guild_id), str(role.id))
        await interaction.response.send_message("✅ Policy ruolo rimossa.", ephemeral=True)

    @reminder_group.command(name="set", description="Template reminder")
    async def inattivi_template_reminder_set(interaction: discord.Interaction, testo: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), dm_reminder_template=testo)
        await interaction.response.send_message("✅ Template reminder aggiornato.", ephemeral=True)

    @kick_group.command(name="set", description="Template kick")
    async def inattivi_template_kick_set(interaction: discord.Interaction, testo: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), dm_kick_template=testo)
        await interaction.response.send_message("✅ Template kick aggiornato.", ephemeral=True)

    @atrio_template_group.command(name="set", description="Template atrio")
    async def inattivi_template_atrio_set(interaction: discord.Interaction, testo: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), atrio_template=testo)
        await interaction.response.send_message("✅ Template atrio aggiornato.", ephemeral=True)

    @inattivi_group.command(name="run", description="Esegui subito gestione inattivi")
    async def inattivi_run(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        if ctx.inactive_members_moderation is None:
            await interaction.response.send_message("❌ Servizio inattivi non disponibile.", ephemeral=True)
            return
        cfg = await ctx.database.get_activity_monitoring_config(str(interaction.guild_id))
        mod_channel_id = str(cfg["mod_channel_id"]) if cfg and cfg["mod_channel_id"] else str(interaction.channel_id)
        await ctx.inactive_members_moderation.handle_post_activity_report(str(interaction.guild_id), mod_channel_id)
        await interaction.response.send_message("✅ Esecuzione completata.", ephemeral=True)

    template_group.add_command(reminder_group)
    template_group.add_command(kick_group)
    template_group.add_command(atrio_template_group)
    inattivi_group.add_command(invite_group)
    inattivi_group.add_command(atrio_group)
    inattivi_group.add_command(exclude_role_group)
    inattivi_group.add_command(default_group)
    inattivi_group.add_command(role_group)
    inattivi_group.add_command(template_group)
