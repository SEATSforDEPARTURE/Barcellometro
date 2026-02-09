from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.services.message_scheduler import calculate_initial_next_run

QUIET_DEFAULT_START = "01:00"
QUIET_DEFAULT_END = "08:30"
CAP_DEFAULT = 6

MOOD_CHOICES = [
    app_commands.Choice(name="AUTO", value="AUTO"),
    app_commands.Choice(name="IGNORE_BARCELLO", value="IGNORE_BARCELLO"),
    app_commands.Choice(name="GREEN_ONLY", value="GREEN_ONLY"),
    app_commands.Choice(name="YELLOW_ONLY", value="YELLOW_ONLY"),
    app_commands.Choice(name="RED_ONLY", value="RED_ONLY"),
]


async def _ensure_setting(ctx: CommandContext, key: str, default: str) -> str:
    stored = await ctx.database.get_setting(key)
    if stored is None:
        await ctx.database.set_setting(key, default)
        return default
    return stored


def _truncate(text: str, limit: int = 100) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def register_messaggi(messaggi_group: app_commands.Group, ctx: CommandContext) -> None:
    @messaggi_group.command(name="quiet_status", description="Stato quiet hours")
    async def messaggi_quiet_status(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.messaggi.quiet.status", ctx):
            return
        enabled = await _ensure_setting(ctx, "messages_quiet_enabled", "1")
        start = await _ensure_setting(ctx, "messages_quiet_start", QUIET_DEFAULT_START)
        end = await _ensure_setting(ctx, "messages_quiet_end", QUIET_DEFAULT_END)
        await interaction.response.send_message(
            f"Quiet hours {'abilitate' if enabled == '1' else 'disabilitate'}: {start}–{end}.",
            ephemeral=True,
        )

    @messaggi_group.command(name="quiet_on", description="Abilita quiet hours")
    async def messaggi_quiet_on(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.messaggi.quiet.on", ctx):
            return
        await ctx.database.set_setting("messages_quiet_enabled", "1")
        await interaction.response.send_message("Quiet hours abilitate.", ephemeral=True)

    @messaggi_group.command(name="quiet_off", description="Disabilita quiet hours")
    async def messaggi_quiet_off(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.messaggi.quiet.off", ctx):
            return
        await ctx.database.set_setting("messages_quiet_enabled", "0")
        await interaction.response.send_message("Quiet hours disabilitate.", ephemeral=True)

    @messaggi_group.command(name="quiet_set", description="Imposta quiet hours")
    @app_commands.describe(start="Ora inizio (HH:MM)", end="Ora fine (HH:MM)")
    async def messaggi_quiet_set(interaction: discord.Interaction, start: str, end: str) -> None:
        if not await check_permission(interaction, "barcellometro.messaggi.quiet.set", ctx):
            return
        await ctx.database.set_setting("messages_quiet_start", start)
        await ctx.database.set_setting("messages_quiet_end", end)
        await interaction.response.send_message(f"Quiet hours aggiornate: {start}–{end}.", ephemeral=True)

    @messaggi_group.command(name="cap_status", description="Stato cap giornaliero")
    async def messaggi_cap_status(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.messaggi.cap.status", ctx):
            return
        enabled = await _ensure_setting(ctx, "messages_daily_cap_enabled", "1")
        cap = await _ensure_setting(ctx, "messages_daily_cap", str(CAP_DEFAULT))
        await interaction.response.send_message(
            f"Cap giornaliero {'attivo' if enabled == '1' else 'disattivo'}: {cap} invii/giorno.",
            ephemeral=True,
        )

    @messaggi_group.command(name="cap_on", description="Abilita cap giornaliero")
    async def messaggi_cap_on(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.messaggi.cap.on", ctx):
            return
        await ctx.database.set_setting("messages_daily_cap_enabled", "1")
        await interaction.response.send_message("Cap giornaliero abilitato.", ephemeral=True)

    @messaggi_group.command(name="cap_off", description="Disabilita cap giornaliero")
    async def messaggi_cap_off(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.messaggi.cap.off", ctx):
            return
        await ctx.database.set_setting("messages_daily_cap_enabled", "0")
        await interaction.response.send_message("Cap giornaliero disabilitato.", ephemeral=True)

    @messaggi_group.command(name="cap_set", description="Imposta cap giornaliero")
    @app_commands.describe(n="Numero massimo invii per canale")
    async def messaggi_cap_set(interaction: discord.Interaction, n: int) -> None:
        if not await check_permission(interaction, "barcellometro.messaggi.cap.set", ctx):
            return
        if n <= 0:
            await interaction.response.send_message("Il cap deve essere > 0.", ephemeral=True)
            return
        await ctx.database.set_setting("messages_daily_cap", str(n))
        await interaction.response.send_message(f"Cap giornaliero impostato a {n}.", ephemeral=True)

    @messaggi_group.command(name="on", description="Abilita i messaggi automatici nel canale corrente")
    async def messaggi_on(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.messaggi.on", ctx):
            return
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("Usa il comando in un canale della guild.", ephemeral=True)
            return
        await ctx.database.set_message_channel_enabled(str(interaction.guild_id), str(interaction.channel_id), True)
        await interaction.response.send_message("Messaggi community abilitati in questo canale.", ephemeral=True)

    @messaggi_group.command(name="off", description="Disabilita i messaggi automatici nel canale corrente")
    async def messaggi_off(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.messaggi.off", ctx):
            return
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("Usa il comando in un canale della guild.", ephemeral=True)
            return
        await ctx.database.set_message_channel_enabled(str(interaction.guild_id), str(interaction.channel_id), False)
        await interaction.response.send_message("Messaggi community disabilitati in questo canale.", ephemeral=True)

    @messaggi_group.command(name="status", description="Mostra lo stato dei messaggi automatici nel canale")
    async def messaggi_status(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.messaggi.status", ctx):
            return
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("Usa il comando in un canale della guild.", ephemeral=True)
            return
        enabled = await ctx.database.get_message_channel_status(str(interaction.guild_id), str(interaction.channel_id))
        active_campaigns = await ctx.database.list_message_campaigns(str(interaction.guild_id), include_disabled=False)
        await interaction.response.send_message(
            f"Canale {'abilitato' if enabled else 'disabilitato'}.\n"
            f"Campagne attive: {len(active_campaigns)}.",
            ephemeral=True,
        )

    @messaggi_group.command(name="aggiungi", description="Aggiungi una nuova campagna custom")
    @app_commands.describe(
        testo="Testo del messaggio",
        testo_verde="Testo per mood verde",
        testo_giallo="Testo per mood giallo",
        testo_rosso="Testo per mood rosso",
        mood_mode="Modalità barcello",
        ogni_minuti="Intervallo in minuti",
        ora_inizio="Ora di inizio (HH:MM, Europe/Rome)",
        jitter_sec="Jitter opzionale in secondi",
        solo_se_inattivo_min="Invia solo se inattivo da X minuti",
    )
    @app_commands.choices(mood_mode=MOOD_CHOICES)
    async def messaggi_aggiungi(
        interaction: discord.Interaction,
        testo: str,
        ogni_minuti: int,
        ora_inizio: str,
        testo_verde: Optional[str] = None,
        testo_giallo: Optional[str] = None,
        testo_rosso: Optional[str] = None,
        mood_mode: Optional[app_commands.Choice[str]] = None,
        jitter_sec: Optional[int] = 0,
        solo_se_inattivo_min: Optional[int] = 0,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.messaggi.aggiungi", ctx):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("Usa il comando in una guild.", ephemeral=True)
            return
        if ogni_minuti <= 0:
            await interaction.response.send_message("ogni_minuti deve essere > 0.", ephemeral=True)
            return
        if jitter_sec is None:
            jitter_sec = 0
        if solo_se_inattivo_min is None:
            solo_se_inattivo_min = 0
        now = datetime.now(timezone.utc)
        try:
            next_run = calculate_initial_next_run(now, ora_inizio, ogni_minuti, ctx.timezone)
        except ValueError as exc:
            await interaction.response.send_message(f"Errore ora_inizio: {exc}", ephemeral=True)
            return
        campaign_id = await ctx.database.create_message_campaign(
            guild_id=str(interaction.guild_id),
            campaign_type="CUSTOM",
            name=None,
            text=testo,
            text_green=testo_verde,
            text_yellow=testo_giallo,
            text_red=testo_rosso,
            enabled=True,
            start_time_local=ora_inizio,
            interval_minutes=ogni_minuti,
            jitter_seconds=jitter_sec,
            only_if_idle_minutes=solo_se_inattivo_min,
            mood_mode=mood_mode.value if mood_mode else "AUTO",
            next_run_at=next_run.isoformat(),
            created_by=str(interaction.user.id),
        )
        await interaction.response.send_message(
            f"Campagna creata con ID {campaign_id}. Prossima esecuzione: {next_run.isoformat()}",
            ephemeral=True,
        )

    @messaggi_group.command(name="lista", description="Elenca le campagne attive")
    async def messaggi_lista(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.messaggi.lista", ctx):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("Usa il comando in una guild.", ephemeral=True)
            return
        campaigns = await ctx.database.list_message_campaigns(str(interaction.guild_id), include_disabled=True)
        if not campaigns:
            await interaction.response.send_message("Nessuna campagna configurata.", ephemeral=True)
            return
        lines = []
        for row in campaigns:
            variants = []
            if row["text_green"]:
                variants.append("G")
            if row["text_yellow"]:
                variants.append("Y")
            if row["text_red"]:
                variants.append("R")
            variant_str = "".join(variants) if variants else "-"
            lines.append(
                " | ".join(
                    [
                        f"ID {row['id']}",
                        "on" if row["enabled"] else "off",
                        f"ogni {row['interval_minutes']}m",
                        f"start {row['start_time_local']}",
                        f"jitter {row['jitter_seconds']}s",
                        f"idle {row['only_if_idle_minutes']}m",
                        f"mode {row['mood_mode']}",
                        f"var {variant_str}",
                        f"last {row['last_sent_at'] or '-'}",
                        f"next {row['next_run_at']}",
                        _truncate(row["text"] or ""),
                    ]
                )
            )
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @messaggi_group.command(name="cancella", description="Rimuove una campagna")
    @app_commands.describe(id="ID campagna")
    async def messaggi_cancella(interaction: discord.Interaction, id: int) -> None:
        if not await check_permission(interaction, "barcellometro.messaggi.cancella", ctx):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("Usa il comando in una guild.", ephemeral=True)
            return
        campaign = await ctx.database.get_message_campaign(str(interaction.guild_id), id)
        if not campaign:
            await interaction.response.send_message("Campagna non trovata.", ephemeral=True)
            return
        await ctx.database.soft_delete_message_campaign(str(interaction.guild_id), id)
        await interaction.response.send_message(f"Campagna {id} rimossa.", ephemeral=True)

    @messaggi_group.command(name="pausa", description="Metti in pausa una campagna")
    @app_commands.describe(id="ID campagna")
    async def messaggi_pausa(interaction: discord.Interaction, id: int) -> None:
        if not await check_permission(interaction, "barcellometro.messaggi.pausa", ctx):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("Usa il comando in una guild.", ephemeral=True)
            return
        campaign = await ctx.database.get_message_campaign(str(interaction.guild_id), id)
        if not campaign:
            await interaction.response.send_message("Campagna non trovata.", ephemeral=True)
            return
        await ctx.database.set_message_campaign_enabled(str(interaction.guild_id), id, False)
        await interaction.response.send_message(f"Campagna {id} in pausa.", ephemeral=True)

    @messaggi_group.command(name="riprendi", description="Riprendi una campagna")
    @app_commands.describe(id="ID campagna")
    async def messaggi_riprendi(interaction: discord.Interaction, id: int) -> None:
        if not await check_permission(interaction, "barcellometro.messaggi.riprendi", ctx):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("Usa il comando in una guild.", ephemeral=True)
            return
        campaign = await ctx.database.get_message_campaign(str(interaction.guild_id), id)
        if not campaign:
            await interaction.response.send_message("Campagna non trovata.", ephemeral=True)
            return
        now = datetime.now(timezone.utc)
        next_run = calculate_initial_next_run(now, campaign["start_time_local"], int(campaign["interval_minutes"]), ctx.timezone)
        await ctx.database.set_message_campaign_enabled(str(interaction.guild_id), id, True)
        await ctx.database.update_campaign_next_run(str(interaction.guild_id), id, next_run.isoformat(), campaign["last_sent_at"])
        await interaction.response.send_message(
            f"Campagna {id} riattivata. Prossima esecuzione: {next_run.isoformat()}",
            ephemeral=True,
        )

    @messaggi_group.command(name="test", description="Invia subito il messaggio della campagna")
    @app_commands.describe(id="ID campagna")
    async def messaggi_test(interaction: discord.Interaction, id: int) -> None:
        if not await check_permission(interaction, "barcellometro.messaggi.test", ctx):
            return
        if interaction.guild_id is None or interaction.channel is None:
            await interaction.response.send_message("Usa il comando in una guild.", ephemeral=True)
            return
        campaign = await ctx.database.get_message_campaign(str(interaction.guild_id), id)
        if not campaign:
            await interaction.response.send_message("Campagna non trovata.", ephemeral=True)
            return
        enabled = await ctx.database.get_message_channel_status(str(interaction.guild_id), str(interaction.channel_id))
        if not enabled:
            await interaction.response.send_message("Canale non abilitato: invio forzato.", ephemeral=True)
        else:
            await interaction.response.send_message("Invio test in corso.", ephemeral=True)
        if isinstance(interaction.channel, discord.abc.Messageable):
            await interaction.channel.send(content=str(campaign["text"] or ""))
