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

    @inattivi_group.command(name="auto_on", description="Abilita modalità automatica inattivi")
    async def inattivi_auto_on(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.set_inactivity_auto_enabled(str(interaction.guild_id), True)
        await interaction.response.send_message("✅ Auto inattivi ON.", ephemeral=True)

    @inattivi_group.command(name="auto_off", description="Disabilita modalità automatica inattivi")
    async def inattivi_auto_off(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.set_inactivity_auto_enabled(str(interaction.guild_id), False)
        await interaction.response.send_message("🛑 Auto inattivi OFF.", ephemeral=True)

    @inattivi_group.command(name="set_grace", description="Imposta giorni grace dopo reminder")
    async def inattivi_set_grace(interaction: discord.Interaction, giorni: app_commands.Range[int, 1, 365]) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), grace_days_after_reminder=int(giorni))
        await interaction.response.send_message("✅ grace aggiornato.", ephemeral=True)

    @inattivi_group.command(name="set_reminder_cooldown", description="Imposta cooldown reminder")
    async def inattivi_set_reminder_cooldown(interaction: discord.Interaction, giorni: app_commands.Range[int, 1, 365]) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), reminder_cooldown_days=int(giorni))
        await interaction.response.send_message("✅ reminder cooldown aggiornato.", ephemeral=True)

    @inattivi_group.command(name="set_ban_days", description="Imposta durata ban temporaneo")
    async def inattivi_set_ban_days(interaction: discord.Interaction, giorni: app_commands.Range[int, 1, 365]) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), ban_days=int(giorni))
        await interaction.response.send_message("✅ ban_days aggiornato.", ephemeral=True)

    @inattivi_group.command(name="set_invite", description="Imposta link invito per rientro")
    async def inattivi_set_invite(interaction: discord.Interaction, url: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), invite_url=url)
        await interaction.response.send_message("✅ Invite impostato.", ephemeral=True)

    @inattivi_group.command(name="set_atrio", description="Imposta canale atrio")
    async def inattivi_set_atrio(interaction: discord.Interaction, canale: discord.TextChannel) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), atrio_channel_id=str(canale.id))
        await interaction.response.send_message("✅ Canale atrio impostato.", ephemeral=True)

    @inattivi_group.command(name="exclude_role_add", description="Aggiungi ruolo escluso da inattività")
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

    @inattivi_group.command(name="exclude_role_remove", description="Rimuovi ruolo escluso da inattività")
    async def inattivi_exclude_role_remove(interaction: discord.Interaction, ruolo: discord.Role) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        guild_id = str(interaction.guild_id)
        await _ensure_cfg(ctx, guild_id)
        cfg = await ctx.database.get_inactivity_config(guild_id)
        current = set(json.loads(cfg["excluded_role_ids_json"] or "[]")) if cfg else set()
        current.discard(str(ruolo.id))
        await ctx.database.upsert_inactivity_config(guild_id, excluded_role_ids_json=json.dumps(sorted(current)))
        await interaction.response.send_message("✅ Ruolo rimosso da esclusioni.", ephemeral=True)

    @inattivi_group.command(name="default_set", description="Imposta policy default inattivi")
    async def inattivi_default_set(
        interaction: discord.Interaction,
        inactive_days: int,
        window_days: int,
        min_messages: int,
        mode: str,
        min_account_age_days: int = 0,
    ) -> None:
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

    @inattivi_group.command(name="role_set", description="Imposta policy per ruolo")
    async def inattivi_role_set(
        interaction: discord.Interaction,
        role: discord.Role,
        inactive_days: int,
        window_days: int,
        min_messages: int,
        mode: str,
        min_account_age_days: int = 0,
        priority: int = 0,
    ) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        try:
            payload = _policy_payload(inactive_days, window_days, min_messages, mode, min_account_age_days)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await ctx.database.upsert_inactivity_role_policy(str(interaction.guild_id), str(role.id), payload, int(priority))
        await interaction.response.send_message("✅ Policy ruolo aggiornata.", ephemeral=True)

    @inattivi_group.command(name="role_del", description="Rimuovi policy per ruolo")
    async def inattivi_role_del(interaction: discord.Interaction, role: discord.Role) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.delete_inactivity_role_policy(str(interaction.guild_id), str(role.id))
        await interaction.response.send_message("✅ Policy ruolo rimossa.", ephemeral=True)

    @inattivi_group.command(name="template_reminder_set", description="Imposta template reminder DM")
    async def inattivi_template_reminder_set(interaction: discord.Interaction, testo: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), dm_reminder_template=testo)
        await interaction.response.send_message("✅ Template reminder aggiornato.", ephemeral=True)

    @inattivi_group.command(name="template_kick_set", description="Imposta template DM kick")
    async def inattivi_template_kick_set(interaction: discord.Interaction, testo: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), dm_kick_template=testo)
        await interaction.response.send_message("✅ Template kick aggiornato.", ephemeral=True)

    @inattivi_group.command(name="template_atrio_set", description="Imposta template messaggio atrio")
    async def inattivi_template_atrio_set(interaction: discord.Interaction, testo: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), atrio_template=testo)
        await interaction.response.send_message("✅ Template atrio aggiornato.", ephemeral=True)

    @inattivi_group.command(name="run", description="Esegui subito scansione inattivi")
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
