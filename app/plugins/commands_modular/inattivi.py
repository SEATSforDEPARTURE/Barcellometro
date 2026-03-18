from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone

import discord
from zoneinfo import ZoneInfo
from discord import app_commands

from app.plugins.commands_modular.command_helpers import describe_placeholders
from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.services.discord_embed_utils import FIELD_MAX, truncate
from app.services.footer import attach_footer_meta, attach_footer_meta_to_all

PERM = "inattivi.config"
TEMPLATE_HELP = f"Placeholder supportati: {describe_placeholders()} Es: {{display_name}}, {{days_inactive}}g."
ROME = ZoneInfo("Europe/Rome")


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

    def _render_preview(template: str) -> str:
        sample = {
            "user": "@ExampleUser",
            "username": "ExampleUser",
            "display_name": "Example",
            "user_id": "1234567890",
            "server": "Barcellometro",
            "guild_id": "987654321",
            "days_inactive": 39,
            "window_days": 30,
            "min_messages": 1,
            "message_count": 0,
            "grace_days": 7,
            "reminder_count": 1,
            "ban_days": 7,
            "rejoin_link": "https://discord.gg/XXXX",
            "reason": "Inattività",
            "inactivity_text": "è stato inattivo per 39 giorni",
        }
        try:
            return template.format(**sample)
        except Exception as exc:
            return f"[Errore render template: {exc}]\n{template}"

    def _format_remaining(deadline: datetime, now: datetime) -> str:
        delta = deadline - now
        if delta.total_seconds() <= 0:
            return "scaduto"
        total = int(delta.total_seconds())
        days = total // 86400
        hours = (total % 86400) // 3600
        minutes = max(1, (total % 3600) // 60)
        if days > 0:
            return f"-{days}g {hours}h"
        if hours > 0:
            return f"-{hours}h {minutes}m"
        return f"-{minutes}m"

    async def _send_lines_with_txt(interaction: discord.Interaction, *, title: str, lines: list[str], txt_prefix: str) -> None:
        ts_name = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        payload = "\n".join(lines) if lines else "Nessun risultato."
        txt_file = discord.File(io.BytesIO(payload.encode("utf-8")), filename=f"{txt_prefix}_{ts_name}.txt")

        if not lines:
            embed = discord.Embed(title=title, description="Nessun risultato.", colour=discord.Colour.blue())
            attach_footer_meta(embed, service_name="inattivi", used_local_processing=True)
            await interaction.response.send_message(embed=embed, ephemeral=True, file=txt_file)
            return

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

        embeds: list[discord.Embed] = []
        total = len(chunks)
        for i, chunk in enumerate(chunks[:10], start=1):
            suffix = f" ({i}/{total})" if total > 1 else ""
            embeds.append(discord.Embed(title=f"{title}{suffix}", description=chunk, colour=discord.Colour.blue()))
        if total > 10:
            embeds[-1].add_field(name="Nota", value="Lista completa in allegato .txt", inline=False)

        attach_footer_meta_to_all(embeds, service_name="inattivi", used_local_processing=True)
        await interaction.response.send_message(embeds=embeds, ephemeral=True, file=txt_file)

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

    @inattivi_group.command(name="status", description="Stato inattivi")
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
            f"cooldown={cfg['reminder_cooldown_days']} | ban_days={cfg['ban_days']} | notify={cfg['notify_channel_id'] or cfg['atrio_channel_id'] or 'n/d'} | "
            f"invite={cfg['invite_url'] or 'n/d'} | role_policies={len(policies)}",
            ephemeral=True,
        )

    @inattivi_group.command(name="auto_on", description="Abilita automazione inattivi")
    async def inattivi_auto_on(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.set_inactivity_auto_enabled(str(interaction.guild_id), True)
        await interaction.response.send_message("✅ Auto inattivi ON.", ephemeral=True)

    @inattivi_group.command(name="auto_off", description="Disabilita automazione inattivi")
    async def inattivi_auto_off(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.set_inactivity_auto_enabled(str(interaction.guild_id), False)
        await interaction.response.send_message("🛑 Auto inattivi OFF.", ephemeral=True)

    @inattivi_group.command(name="set_grace", description="Imposta attesa post-reminder")
    @app_commands.describe(giorni="Giorni post reminder")
    async def inattivi_set_grace(interaction: discord.Interaction, giorni: app_commands.Range[int, 1, 365]) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), grace_days_after_reminder=int(giorni))
        await interaction.response.send_message("✅ grace aggiornato.", ephemeral=True)

    @inattivi_group.command(name="set_reminder_cooldown", description="Imposta cooldown reminder")
    @app_commands.describe(giorni="Cooldown reminder (giorni)")
    async def inattivi_set_reminder_cooldown(interaction: discord.Interaction, giorni: app_commands.Range[int, 1, 365]) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), reminder_cooldown_days=int(giorni))
        await interaction.response.send_message("✅ reminder cooldown aggiornato.", ephemeral=True)

    @inattivi_group.command(name="set_ban_days", description="Imposta ban temporaneo")
    @app_commands.describe(giorni="Durata ban (giorni)")
    async def inattivi_set_ban_days(interaction: discord.Interaction, giorni: app_commands.Range[int, 1, 365]) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), ban_days=int(giorni))
        await interaction.response.send_message("✅ ban_days aggiornato.", ephemeral=True)

    @inattivi_group.command(name="set_invite", description="Imposta link rientro")
    @app_commands.describe(url="URL invito rejoin")
    async def inattivi_set_invite(interaction: discord.Interaction, url: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), invite_url=url)
        await interaction.response.send_message("✅ Invite impostato.", ephemeral=True)


    @inattivi_group.command(name="exclude_role_add", description="Escludi ruolo da inattivi")
    @app_commands.describe(ruolo="Ruolo da ignorare")
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

    @inattivi_group.command(name="exclude_role_remove", description="Rimuovi esclusione ruolo")
    @app_commands.describe(ruolo="Ruolo da reincludere")
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

    @inattivi_group.command(name="default_set", description="Imposta policy base inattivi")
    @app_commands.describe(
        inactive_days="Giorni inattività",
        window_days="Finestra di analisi messaggi (giorni)",
        min_messages="Numero minimo messaggi nella finestra",
        mode="OR o AND",
        min_account_age_days="Escludi account più nuovi",
    )
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

    @inattivi_group.command(name="role_set", description="Imposta policy inattivi ruolo")
    @app_commands.describe(
        role="Ruolo target",
        inactive_days="Giorni inattività",
        window_days="Finestra analisi in giorni",
        min_messages="Min messaggi finestra",
        mode="OR o AND",
        min_account_age_days="Esclude account troppo nuovi",
        priority="Priorità policy ruolo",
    )
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

    @inattivi_group.command(name="role_del", description="Rimuovi policy inattivi ruolo")
    @app_commands.describe(role="Ruolo policy")
    async def inattivi_role_del(interaction: discord.Interaction, role: discord.Role) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.delete_inactivity_role_policy(str(interaction.guild_id), str(role.id))
        await interaction.response.send_message("✅ Policy ruolo rimossa.", ephemeral=True)

    @inattivi_group.command(name="template_reminder_set", description="Template reminder DM")
    @app_commands.describe(testo=TEMPLATE_HELP)
    async def inattivi_template_reminder_set(interaction: discord.Interaction, testo: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), dm_reminder_template=testo)
        await interaction.response.send_message("✅ Template reminder aggiornato.", ephemeral=True)






    @inattivi_group.command(name="run", description="Esegui scansione inattivi")
    async def inattivi_run(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        if ctx.inactive_members_moderation is None:
            await interaction.response.send_message("❌ Servizio inattivi non disponibile.", ephemeral=True)
            return
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)
        target_channel_id = str(interaction.channel_id)
        await ctx.inactive_members_moderation.handle_post_activity_report(str(interaction.guild_id), target_channel_id)
        await interaction.followup.send("✅ Esecuzione completata.", ephemeral=True)
