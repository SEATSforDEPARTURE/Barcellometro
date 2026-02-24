from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import discord
from discord import app_commands

from app.plugins.commands_modular.command_helpers import describe_placeholders
from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.services.discord_embed_utils import FIELD_MAX, truncate

PERM = "barcellometro.inattivi.config"
TEMPLATE_HELP = f"Placeholder supportati: {describe_placeholders()} Es: {{display_name}}, {{days_inactive}}g."


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
        }
        try:
            return template.format(**sample)
        except Exception as exc:
            return f"[Errore render template: {exc}]\n{template}"

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

    @inattivi_group.command(name="status", description="Mostra configurazione inattivi corrente")
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

    @inattivi_group.command(name="auto_on", description="Abilita reminder→kick automatico per inattivi")
    async def inattivi_auto_on(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.set_inactivity_auto_enabled(str(interaction.guild_id), True)
        await interaction.response.send_message("✅ Auto inattivi ON.", ephemeral=True)

    @inattivi_group.command(name="auto_off", description="Disabilita reminder→kick automatico per inattivi")
    async def inattivi_auto_off(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.set_inactivity_auto_enabled(str(interaction.guild_id), False)
        await interaction.response.send_message("🛑 Auto inattivi OFF.", ephemeral=True)

    @inattivi_group.command(name="set_grace", description="Imposta i giorni di attesa dopo il reminder")
    @app_commands.describe(giorni="Giorni dopo il reminder prima di valutare kick/ban automatico")
    async def inattivi_set_grace(interaction: discord.Interaction, giorni: app_commands.Range[int, 1, 365]) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), grace_days_after_reminder=int(giorni))
        await interaction.response.send_message("✅ grace aggiornato.", ephemeral=True)

    @inattivi_group.command(name="set_reminder_cooldown", description="Imposta cooldown giorni tra reminder consecutivi")
    @app_commands.describe(giorni="Giorni minimi tra due reminder DM allo stesso utente")
    async def inattivi_set_reminder_cooldown(interaction: discord.Interaction, giorni: app_commands.Range[int, 1, 365]) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), reminder_cooldown_days=int(giorni))
        await interaction.response.send_message("✅ reminder cooldown aggiornato.", ephemeral=True)

    @inattivi_group.command(name="set_ban_days", description="Imposta durata ban temporaneo (giorni)")
    @app_commands.describe(giorni="Durata in giorni del ban temporaneo dopo kick inattività")
    async def inattivi_set_ban_days(interaction: discord.Interaction, giorni: app_commands.Range[int, 1, 365]) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), ban_days=int(giorni))
        await interaction.response.send_message("✅ ban_days aggiornato.", ephemeral=True)

    @inattivi_group.command(name="set_invite", description="Imposta il link invito usato nei DM inattivi")
    @app_commands.describe(url="URL invito da usare come {rejoin_link} nei template")
    async def inattivi_set_invite(interaction: discord.Interaction, url: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), invite_url=url)
        await interaction.response.send_message("✅ Invite impostato.", ephemeral=True)

    @inattivi_group.command(name="set_atrio", description="Imposta canale atrio per messaggi uscita inattivi")
    @app_commands.describe(canale="Canale testuale in cui notificare uscite per inattività")
    async def inattivi_set_atrio(interaction: discord.Interaction, canale: discord.TextChannel) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), atrio_channel_id=str(canale.id))
        await interaction.response.send_message("✅ Canale atrio impostato.", ephemeral=True)

    @inattivi_group.command(name="exclude_role_add", description="Esclude un ruolo dalla scansione inattivi")
    @app_commands.describe(ruolo="Ruolo da ignorare nel calcolo inattivi")
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

    @inattivi_group.command(name="exclude_role_remove", description="Rimuove un ruolo dalle esclusioni inattivi")
    @app_commands.describe(ruolo="Ruolo da reincludere nella scansione inattivi")
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

    @inattivi_group.command(name="default_set", description="Imposta policy base inattivi (giorni, finestra, minimo messaggi)")
    @app_commands.describe(
        inactive_days="Giorni senza messaggi per considerare inattivo",
        window_days="Finestra di analisi messaggi (giorni)",
        min_messages="Numero minimo messaggi nella finestra",
        mode="OR (basta una condizione) / AND (servono entrambe)",
        min_account_age_days="Esclude account più nuovi di questi giorni",
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

    @inattivi_group.command(name="role_set", description="Imposta policy inattivi per uno specifico ruolo")
    @app_commands.describe(
        role="Ruolo target",
        inactive_days="Giorni senza messaggi per inattività",
        window_days="Finestra analisi in giorni",
        min_messages="Messaggi minimi richiesti nella finestra",
        mode="OR (basta una condizione) / AND (servono entrambe)",
        min_account_age_days="Esclude account troppo nuovi",
        priority="Se più policy ruolo matchano, vince la priority più alta",
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

    @inattivi_group.command(name="role_del", description="Rimuove la policy inattivi di un ruolo")
    @app_commands.describe(role="Ruolo di cui eliminare la policy")
    async def inattivi_role_del(interaction: discord.Interaction, role: discord.Role) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await ctx.database.delete_inactivity_role_policy(str(interaction.guild_id), str(role.id))
        await interaction.response.send_message("✅ Policy ruolo rimossa.", ephemeral=True)

    @inattivi_group.command(name="template_reminder_set", description="Imposta template DM reminder (con placeholder)")
    @app_commands.describe(testo=TEMPLATE_HELP)
    async def inattivi_template_reminder_set(interaction: discord.Interaction, testo: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), dm_reminder_template=testo)
        await interaction.response.send_message("✅ Template reminder aggiornato.", ephemeral=True)

    @inattivi_group.command(name="template_kick_set", description="Imposta template DM kick (con placeholder)")
    @app_commands.describe(testo=TEMPLATE_HELP)
    async def inattivi_template_kick_set(interaction: discord.Interaction, testo: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), dm_kick_template=testo)
        await interaction.response.send_message("✅ Template kick aggiornato.", ephemeral=True)

    @inattivi_group.command(name="template_atrio_set", description="Imposta template atrio (con placeholder)")
    @app_commands.describe(testo=TEMPLATE_HELP)
    async def inattivi_template_atrio_set(interaction: discord.Interaction, testo: str) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        await _ensure_cfg(ctx, str(interaction.guild_id))
        await ctx.database.upsert_inactivity_config(str(interaction.guild_id), atrio_template=testo)
        await interaction.response.send_message("✅ Template atrio aggiornato.", ephemeral=True)

    @inattivi_group.command(name="template_show", description="Mostra i template attuali (reminder/kick/atrio).")
    async def inattivi_template_show(interaction: discord.Interaction) -> None:
        if not await _ensure(interaction) or interaction.guild_id is None:
            return
        cfg = await ctx.database.get_inactivity_config(str(interaction.guild_id))
        if cfg is None:
            await interaction.response.send_message("Nessuna configurazione inattivi presente.", ephemeral=True)
            return
        cfg = dict(cfg)

        reminder_raw = str(cfg.get("dm_reminder_template") or "Ciao {user}, sei inattivo su {server} da {days_inactive} giorni. Ti aspettiamo!")
        kick_raw = str(cfg.get("dm_kick_template") or "Ciao {user}, sei stato rimosso da {server} per inattività. Puoi rientrare: {rejoin_link}")
        atrio_raw = str(cfg.get("atrio_template") or "👋 {username} è uscito per inattività ({days_inactive}g).")

        reminder_preview = _render_preview(reminder_raw)
        kick_preview = _render_preview(kick_raw)
        atrio_preview = _render_preview(atrio_raw)

        embed = discord.Embed(title="🧩 Template inattivi", colour=discord.Colour.blue())
        extra_sections: list[str] = []

        def add_template_field(name: str, text: str) -> None:
            if len(text) <= FIELD_MAX:
                embed.add_field(name=name, value=text, inline=False)
            else:
                embed.add_field(name=name, value=truncate(text, FIELD_MAX), inline=False)
                extra_sections.append(f"## {name}\n{text}")

        add_template_field("📩 Template reminder", reminder_raw)
        add_template_field("🚪 Template kick", kick_raw)
        add_template_field("🏛 Template atrio", atrio_raw)
        add_template_field("🧪 Esempio reminder", reminder_preview)
        add_template_field("🧪 Esempio kick", kick_preview)
        add_template_field("🧪 Esempio atrio", atrio_preview)

        extra_file: discord.File | None = None
        if extra_sections:
            ts_name = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
            filename = f"templates_{ts_name}.txt"
            payload = "\n\n".join(extra_sections).encode("utf-8")
            extra_file = discord.File(io.BytesIO(payload), filename=filename)

        if extra_file is None:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True, file=extra_file)

    @inattivi_group.command(name="run", description="Esegui subito scansione inattivi e pannello moderazione")
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
