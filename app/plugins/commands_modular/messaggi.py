from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Optional

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.plugins.commands_modular.command_helpers import add_group_once, count_child_commands
from app.services.scheduler_utils import calculate_initial_next_run

QUIET_DEFAULT_START = "01:00"
QUIET_DEFAULT_END = "08:30"
CAP_DEFAULT = 6

logger = logging.getLogger(__name__)

MOOD_CHOICES = [
    app_commands.Choice(name="AUTO", value="AUTO"),
    app_commands.Choice(name="IGNORE_BARCELLO", value="IGNORE_BARCELLO"),
    app_commands.Choice(name="GREEN_ONLY", value="GREEN_ONLY"),
    app_commands.Choice(name="YELLOW_ONLY", value="YELLOW_ONLY"),
    app_commands.Choice(name="RED_ONLY", value="RED_ONLY"),
    app_commands.Choice(name="BLACK_ONLY", value="BLACK_ONLY"),
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


def validate_campaign_texts(
    *,
    testo: Optional[str],
    testo_verde: Optional[str],
    testo_giallo: Optional[str],
    testo_rosso: Optional[str],
    testo_nero: Optional[str],
    mood_mode: str,
) -> Optional[str]:
    values = [testo, testo_verde, testo_giallo, testo_rosso, testo_nero]
    if not any(value for value in values):
        return (
            "Devi inserire almeno `testo` (fallback) oppure una variante tra "
            "`testo_verde`, `testo_giallo`, `testo_rosso`, `testo_nero`."
        )
    if mood_mode == "IGNORE_BARCELLO" and not testo:
        return "Con mood_mode=IGNORE_BARCELLO devi valorizzare `testo`."
    return None


def register_messaggi(campagne_group: app_commands.Group, ctx: CommandContext) -> None:
    servizi_group = app_commands.Group(name="servizi", description="Servizi editoriali campagne")
    add_group_once(campagne_group, servizi_group, logger)
    logger.debug("Registered /%s with children=%d", campagne_group.qualified_name or campagne_group.name, count_child_commands(campagne_group))
    @campagne_group.command(name="quiet_status", description="Stato quiet hours")
    async def messaggi_quiet_status(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "campagne.quiet.status", ctx):
            return
        enabled = await _ensure_setting(ctx, "messages_quiet_enabled", "1")
        start = await _ensure_setting(ctx, "messages_quiet_start", QUIET_DEFAULT_START)
        end = await _ensure_setting(ctx, "messages_quiet_end", QUIET_DEFAULT_END)
        await interaction.response.send_message(
            f"Quiet hours {'abilitate' if enabled == '1' else 'disabilitate'}: {start}–{end}.",
            ephemeral=True,
        )

    @campagne_group.command(name="quiet_on", description="Abilita quiet hours")
    async def messaggi_quiet_on(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "campagne.quiet.on", ctx):
            return
        await ctx.database.set_setting("messages_quiet_enabled", "1")
        await interaction.response.send_message("Quiet hours abilitate.", ephemeral=True)

    @campagne_group.command(name="quiet_off", description="Disabilita quiet hours")
    async def messaggi_quiet_off(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "campagne.quiet.off", ctx):
            return
        await ctx.database.set_setting("messages_quiet_enabled", "0")
        await interaction.response.send_message("Quiet hours disabilitate.", ephemeral=True)

    @campagne_group.command(name="quiet_set", description="Imposta quiet hours")
    @app_commands.describe(start="Ora inizio (HH:MM)", end="Ora fine (HH:MM)")
    async def messaggi_quiet_set(interaction: discord.Interaction, start: str, end: str) -> None:
        if not await check_permission(interaction, "campagne.quiet.set", ctx):
            return
        await ctx.database.set_setting("messages_quiet_start", start)
        await ctx.database.set_setting("messages_quiet_end", end)
        await interaction.response.send_message(f"Quiet hours aggiornate: {start}–{end}.", ephemeral=True)

    @campagne_group.command(name="cap_status", description="Stato cap giornaliero")
    async def messaggi_cap_status(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "campagne.cap.status", ctx):
            return
        enabled = await _ensure_setting(ctx, "messages_daily_cap_enabled", "1")
        cap = await _ensure_setting(ctx, "messages_daily_cap", str(CAP_DEFAULT))
        await interaction.response.send_message(
            f"Cap giornaliero {'attivo' if enabled == '1' else 'disattivo'}: {cap} invii/giorno.",
            ephemeral=True,
        )

    @campagne_group.command(name="cap_on", description="Abilita cap giornaliero")
    async def messaggi_cap_on(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "campagne.cap.on", ctx):
            return
        await ctx.database.set_setting("messages_daily_cap_enabled", "1")
        await interaction.response.send_message("Cap giornaliero abilitato.", ephemeral=True)

    @campagne_group.command(name="cap_off", description="Disabilita cap giornaliero")
    async def messaggi_cap_off(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "campagne.cap.off", ctx):
            return
        await ctx.database.set_setting("messages_daily_cap_enabled", "0")
        await interaction.response.send_message("Cap giornaliero disabilitato.", ephemeral=True)

    @campagne_group.command(name="cap_set", description="Imposta cap giornaliero")
    @app_commands.describe(n="Max invii canale")
    async def messaggi_cap_set(interaction: discord.Interaction, n: int) -> None:
        if not await check_permission(interaction, "campagne.cap.set", ctx):
            return
        if n <= 0:
            await interaction.response.send_message("Il cap deve essere > 0.", ephemeral=True)
            return
        await ctx.database.set_setting("messages_daily_cap", str(n))
        await interaction.response.send_message(f"Cap giornaliero impostato a {n}.", ephemeral=True)

    @campagne_group.command(name="on", description="Abilita campagne nel canale")
    async def messaggi_on(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "campagne.on", ctx):
            return
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("Usa il comando in un canale della guild.", ephemeral=True)
            return
        await ctx.database.set_message_channel_enabled(str(interaction.guild_id), str(interaction.channel_id), True)
        await interaction.response.send_message("Messaggi auto abilitati in questo canale.", ephemeral=True)

    @campagne_group.command(name="off", description="Disabilita campagne nel canale")
    async def messaggi_off(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "campagne.off", ctx):
            return
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("Usa il comando in un canale della guild.", ephemeral=True)
            return
        await ctx.database.set_message_channel_enabled(str(interaction.guild_id), str(interaction.channel_id), False)
        await interaction.response.send_message("Messaggi auto disabilitati in questo canale.", ephemeral=True)

    @campagne_group.command(name="status", description="Stato campagne nel canale")
    async def messaggi_status(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "campagne.status", ctx):
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

    @campagne_group.command(name="aggiungi", description="Aggiungi una nuova campagna custom")
    @app_commands.describe(
        testo="Testo fallback",
        testo_verde="Testo per mood verde",
        testo_giallo="Testo per mood giallo",
        testo_rosso="Testo per mood rosso",
        testo_nero="Testo per Barcello ⚫",
        mood_mode="Modalità barcello",
        ogni_minuti="Intervallo in minuti",
        ora_inizio="Ora di inizio (HH:MM, Europe/Rome)",
        jitter_sec="Jitter opzionale in secondi",
        solo_se_inattivo_min="Invia solo se inattivo da X minuti",
        embed_title="Titolo embed opzionale",
        embed_color="Colore embed opzionale",
    )
    @app_commands.choices(mood_mode=MOOD_CHOICES)
    async def messaggi_aggiungi(
        interaction: discord.Interaction,
        ogni_minuti: int,
        ora_inizio: str,
        testo: Optional[str] = None,
        testo_verde: Optional[str] = None,
        testo_giallo: Optional[str] = None,
        testo_rosso: Optional[str] = None,
        testo_nero: Optional[str] = None,
        mood_mode: Optional[app_commands.Choice[str]] = None,
        jitter_sec: Optional[int] = 0,
        solo_se_inattivo_min: Optional[int] = 0,
        embed_title: Optional[str] = None,
        embed_color: Optional[str] = None,
    ) -> None:
        if not await check_permission(interaction, "campagne.aggiungi", ctx):
            return
        if interaction.guild_id is None or interaction.channel_id is None:
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
        resolved_mood_mode = mood_mode.value if mood_mode else "AUTO"
        validation_error = validate_campaign_texts(
            testo=testo,
            testo_verde=testo_verde,
            testo_giallo=testo_giallo,
            testo_rosso=testo_rosso,
            testo_nero=testo_nero,
            mood_mode=resolved_mood_mode,
        )
        if validation_error:
            await interaction.response.send_message(validation_error, ephemeral=True)
            return
        if ctx.message_scheduler is not None and not ctx.message_scheduler.is_valid_embed_color(embed_color):
            await interaction.response.send_message("embed_color non valido. Usa #RRGGBB, RRGGBB oppure 0xRRGGBB.", ephemeral=True)
            return

        campaign_id = await ctx.database.create_message_campaign(
            guild_id=str(interaction.guild_id),
            channel_id=str(interaction.channel_id),
            campaign_type="CUSTOM",
            name=None,
            text=testo,
            text_green=testo_verde,
            text_yellow=testo_giallo,
            text_red=testo_rosso,
            text_black=testo_nero,
            enabled=True,
            start_time_local=ora_inizio,
            interval_minutes=ogni_minuti,
            jitter_seconds=jitter_sec,
            only_if_idle_minutes=solo_se_inattivo_min,
            mood_mode=resolved_mood_mode,
            next_run_at=next_run.isoformat(),
            created_by=str(interaction.user.id),
            embed_title=embed_title,
            embed_color=embed_color,
        )
        await interaction.response.send_message(
            f"Campagna creata con ID {campaign_id}. Prossima esecuzione: {next_run.isoformat()}",
            ephemeral=True,
        )

    @campagne_group.command(name="lista", description="Elenca le campagne attive")
    async def messaggi_lista(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "campagne.lista", ctx):
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
            variants.append(f"V{'✅' if row['text'] else '—'}")
            variants.append(f"G{'✅' if row['text_green'] else '—'}")
            variants.append(f"Y{'✅' if row['text_yellow'] else '—'}")
            variants.append(f"R{'✅' if row['text_red'] else '—'}")
            variants.append(f"N{'✅' if row['text_black'] else '—'}")
            variant_str = " ".join(variants)
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
                        f"embed_title {row['embed_title'] or '-'}",
                        f"embed_color {row['embed_color'] or '-'}",
                        f"base: {_truncate(row['text'] or '')}" if row["text"] else "base: —",
                    ]
                )
            )
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @campagne_group.command(name="cancella", description="Rimuove una campagna")
    @app_commands.describe(id="ID campagna")
    async def messaggi_cancella(interaction: discord.Interaction, id: int) -> None:
        if not await check_permission(interaction, "campagne.cancella", ctx):
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

    @campagne_group.command(name="pausa", description="Metti in pausa una campagna")
    @app_commands.describe(id="ID campagna")
    async def messaggi_pausa(interaction: discord.Interaction, id: int) -> None:
        if not await check_permission(interaction, "campagne.pausa", ctx):
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

    @campagne_group.command(name="riprendi", description="Riprendi una campagna")
    @app_commands.describe(id="ID campagna")
    async def messaggi_riprendi(interaction: discord.Interaction, id: int) -> None:
        if not await check_permission(interaction, "campagne.riprendi", ctx):
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

    @campagne_group.command(name="test", description="Invia campagna ora")
    @app_commands.describe(id="ID campagna")
    async def messaggi_test(interaction: discord.Interaction, id: int) -> None:
        if not await check_permission(interaction, "campagne.test", ctx):
            return
        if interaction.guild_id is None or interaction.channel is None:
            await interaction.response.send_message("Usa il comando in una guild.", ephemeral=True)
            return
        campaign = await ctx.database.get_message_campaign(str(interaction.guild_id), id)
        if not campaign:
            await interaction.response.send_message("Campagna non trovata.", ephemeral=True)
            return
        if not isinstance(campaign, dict) and hasattr(campaign, "keys"):
            campaign = dict(campaign)
        if ctx.message_scheduler is None:
            await interaction.response.send_message("Servizio scheduler non disponibile.", ephemeral=True)
            return
        enabled = await ctx.database.get_message_channel_status(str(interaction.guild_id), str(interaction.channel_id))
        if not enabled:
            await interaction.response.send_message("Canale non abilitato: invio forzato.", ephemeral=True)
        else:
            await interaction.response.send_message("Invio test in corso.", ephemeral=True)
        if isinstance(interaction.channel, discord.abc.Messageable):
            rendered_text, _, _ = await ctx.message_scheduler.preview_campaign_text(
                campaign,
                channel_id_override=str(interaction.channel_id),
            )
            await ctx.message_scheduler.send_campaign_embed(interaction.channel, campaign, rendered_text)

    @servizi_group.command(name="notizie", description="Configura campagna editoriale notizie")
    @app_commands.describe(
        time_local="Ora invio (HH:MM)",
        interval_minutes="Intervallo in minuti",
        embed_title="Titolo embed",
        embed_color="Colore embed (#RRGGBB)",
        sources="Fonti CSV o URL RSS separate da virgola",
        categories="Categorie CSV (es: trash,spettacolo,viral)",
    )
    async def campagne_notizie(
        interaction: discord.Interaction,
        time_local: str,
        interval_minutes: int,
        embed_title: Optional[str] = None,
        embed_color: Optional[str] = None,
        sources: Optional[str] = None,
        categories: Optional[str] = None,
    ) -> None:
        if not await check_permission(interaction, "campagne.notizie", ctx):
            return
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("Usa il comando in una guild.", ephemeral=True)
            return
        if interval_minutes <= 0:
            await interaction.response.send_message("interval_minutes deve essere > 0.", ephemeral=True)
            return
        now = datetime.now(timezone.utc)
        try:
            next_run = calculate_initial_next_run(now, time_local, interval_minutes, ctx.timezone)
        except ValueError as exc:
            await interaction.response.send_message(f"Errore time_local: {exc}", ephemeral=True)
            return
        cfg_id = await ctx.database.create_campaign_content_config(
            guild_id=str(interaction.guild_id),
            channel_id=str(interaction.channel_id),
            service_type="NEWS",
            enabled=True,
            time_local=time_local,
            interval_minutes=interval_minutes,
            embed_title=embed_title,
            embed_color=embed_color,
            sources_json=json.dumps([s.strip() for s in (sources or "").split(",") if s.strip()]),
            categories_json=categories,
            next_run_at=next_run.isoformat(),
        )
        await interaction.response.send_message(f"Servizio notizie creato (ID {cfg_id}), next_run={next_run.isoformat()}", ephemeral=True)

    @servizi_group.command(name="meteo", description="Configura campagna editoriale meteo")
    @app_commands.describe(
        time_local="Ora invio (HH:MM)",
        interval_minutes="Intervallo in minuti",
        embed_title="Titolo embed",
        embed_color="Colore embed (#RRGGBB)",
        sources="Fonti CSV",
    )
    async def campagne_meteo(
        interaction: discord.Interaction,
        time_local: str,
        interval_minutes: int,
        embed_title: Optional[str] = None,
        embed_color: Optional[str] = None,
        sources: Optional[str] = None,
    ) -> None:
        if not await check_permission(interaction, "campagne.meteo", ctx):
            return
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("Usa il comando in una guild.", ephemeral=True)
            return
        now = datetime.now(timezone.utc)
        try:
            next_run = calculate_initial_next_run(now, time_local, interval_minutes, ctx.timezone)
        except ValueError as exc:
            await interaction.response.send_message(f"Errore time_local: {exc}", ephemeral=True)
            return
        cfg_id = await ctx.database.create_campaign_content_config(
            guild_id=str(interaction.guild_id),
            channel_id=str(interaction.channel_id),
            service_type="WEATHER",
            enabled=True,
            time_local=time_local,
            interval_minutes=interval_minutes,
            embed_title=embed_title,
            embed_color=embed_color,
            sources_json=json.dumps([s.strip() for s in (sources or "").split(",") if s.strip()]),
            categories_json=None,
            next_run_at=next_run.isoformat(),
        )
        await interaction.response.send_message(f"Servizio meteo creato (ID {cfg_id}), next_run={next_run.isoformat()}", ephemeral=True)

    @servizi_group.command(name="oroscopo", description="Configura campagna editoriale oroscopo")
    @app_commands.describe(
        time_local="Ora invio (HH:MM)",
        interval_minutes="Intervallo in minuti",
        embed_title="Titolo embed",
        embed_color="Colore embed (#RRGGBB)",
        sources="Fonti CSV",
    )
    async def campagne_oroscopo(
        interaction: discord.Interaction,
        time_local: str,
        interval_minutes: int,
        embed_title: Optional[str] = None,
        embed_color: Optional[str] = None,
        sources: Optional[str] = None,
    ) -> None:
        if not await check_permission(interaction, "campagne.oroscopo", ctx):
            return
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("Usa il comando in una guild.", ephemeral=True)
            return
        now = datetime.now(timezone.utc)
        try:
            next_run = calculate_initial_next_run(now, time_local, interval_minutes, ctx.timezone)
        except ValueError as exc:
            await interaction.response.send_message(f"Errore time_local: {exc}", ephemeral=True)
            return
        cfg_id = await ctx.database.create_campaign_content_config(
            guild_id=str(interaction.guild_id),
            channel_id=str(interaction.channel_id),
            service_type="HOROSCOPE",
            enabled=True,
            time_local=time_local,
            interval_minutes=interval_minutes,
            embed_title=embed_title,
            embed_color=embed_color,
            sources_json=json.dumps([s.strip() for s in (sources or "").split(",") if s.strip()]),
            categories_json=None,
            next_run_at=next_run.isoformat(),
        )
        await interaction.response.send_message(f"Servizio oroscopo creato (ID {cfg_id}), next_run={next_run.isoformat()}", ephemeral=True)

    @servizi_group.command(name="lista", description="Lista servizi editoriali")
    async def campagne_servizi_lista(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "campagne.servizi_lista", ctx):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("Usa il comando in una guild.", ephemeral=True)
            return
        rows = await ctx.database.list_campaign_content_configs(str(interaction.guild_id), include_disabled=True)
        if not rows:
            await interaction.response.send_message("Nessun servizio editoriale configurato.", ephemeral=True)
            return
        lines = []
        for row in rows:
            lines.append(
                f"ID {row['id']} | {row['service_type']} | {'on' if row['enabled'] else 'off'} | ogni {row['interval_minutes']}m | start {row['time_local']} | next {row['next_run_at']}"
            )
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @servizi_group.command(name="on", description="Riattiva servizio editoriale")
    @app_commands.describe(id="ID servizio")
    async def campagne_servizi_on(interaction: discord.Interaction, id: int) -> None:
        if not await check_permission(interaction, "campagne.servizi_on", ctx):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("Usa il comando in una guild.", ephemeral=True)
            return
        row = await ctx.database.get_campaign_content_config(str(interaction.guild_id), id)
        if not row:
            await interaction.response.send_message("Servizio non trovato.", ephemeral=True)
            return
        await ctx.database.set_campaign_content_enabled(str(interaction.guild_id), id, True)
        await interaction.response.send_message(f"Servizio {id} attivato.", ephemeral=True)

    @servizi_group.command(name="off", description="Disattiva servizio editoriale")
    @app_commands.describe(id="ID servizio")
    async def campagne_servizi_off(interaction: discord.Interaction, id: int) -> None:
        if not await check_permission(interaction, "campagne.servizi_off", ctx):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("Usa il comando in una guild.", ephemeral=True)
            return
        row = await ctx.database.get_campaign_content_config(str(interaction.guild_id), id)
        if not row:
            await interaction.response.send_message("Servizio non trovato.", ephemeral=True)
            return
        await ctx.database.set_campaign_content_enabled(str(interaction.guild_id), id, False)
        await interaction.response.send_message(f"Servizio {id} in pausa.", ephemeral=True)

    @servizi_group.command(name="delete", description="Cancella servizio editoriale")
    @app_commands.describe(id="ID servizio")
    async def campagne_servizi_delete(interaction: discord.Interaction, id: int) -> None:
        if not await check_permission(interaction, "campagne.servizi_delete", ctx):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("Usa il comando in una guild.", ephemeral=True)
            return
        row = await ctx.database.get_campaign_content_config(str(interaction.guild_id), id)
        if not row:
            await interaction.response.send_message("Servizio non trovato.", ephemeral=True)
            return
        await ctx.database.soft_delete_campaign_content_config(str(interaction.guild_id), id)
        await interaction.response.send_message(f"Servizio {id} eliminato.", ephemeral=True)

    @servizi_group.command(name="test", description="Esegue subito un servizio editoriale")
    @app_commands.describe(id="ID servizio")
    async def campagne_servizi_test(interaction: discord.Interaction, id: int) -> None:
        if not await check_permission(interaction, "campagne.servizi_test", ctx):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("Usa il comando in una guild.", ephemeral=True)
            return
        row = await ctx.database.get_campaign_content_config(str(interaction.guild_id), id)
        if not row:
            await interaction.response.send_message("Servizio non trovato.", ephemeral=True)
            return
        service = getattr(ctx.message_scheduler, "_campaign_content_service", None) if ctx.message_scheduler is not None else None
        if service is None:
            await interaction.response.send_message("Servizio campagne editoriali non disponibile.", ephemeral=True)
            return
        await interaction.response.send_message("Invio test in corso.", ephemeral=True)
        payload = dict(row)
        stype = str(payload.get("service_type") or "").upper()
        if stype == "NEWS":
            await service.execute_news_service(payload)
        elif stype == "WEATHER":
            await service.execute_weather_service(payload)
        elif stype == "HOROSCOPE":
            await service.execute_horoscope_service(payload)
