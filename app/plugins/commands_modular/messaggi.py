from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.services.message_scheduler import calculate_initial_next_run


def _truncate(text: str, limit: int = 100) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def register_messaggi(messaggi_group: app_commands.Group, ctx: CommandContext) -> None:
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
        ogni_minuti="Intervallo in minuti",
        ora_inizio="Ora di inizio (HH:MM, Europe/Rome)",
        jitter_sec="Jitter opzionale in secondi",
        solo_se_inattivo_min="Invia solo se inattivo da X minuti",
    )
    async def messaggi_aggiungi(
        interaction: discord.Interaction,
        testo: str,
        ogni_minuti: int,
        ora_inizio: str,
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
            enabled=True,
            start_time_local=ora_inizio,
            interval_minutes=ogni_minuti,
            jitter_seconds=jitter_sec,
            only_if_idle_minutes=solo_se_inattivo_min,
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
            lines.append(
                " | ".join(
                    [
                        f"ID {row['id']}",
                        "on" if row["enabled"] else "off",
                        f"ogni {row['interval_minutes']}m",
                        f"start {row['start_time_local']}",
                        f"jitter {row['jitter_seconds']}s",
                        f"idle {row['only_if_idle_minutes']}m",
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
