from __future__ import annotations

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission

def _clean_opt(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _format_value(value: str | None) -> str:
    return value if value else "(non impostata)"


def register_admin(bm_group: app_commands.Group, ctx: CommandContext) -> None:
    @bm_group.command(name="check", description="Attiva/disattiva raccolta eventi")
    @app_commands.describe(state="on/off")
    @app_commands.choices(state=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
    async def check_command(interaction: discord.Interaction, state: app_commands.Choice[str]) -> None:
        if not await check_permission(interaction, "bm.check", ctx):
            return
        if not interaction.channel or not isinstance(interaction.channel, discord.abc.GuildChannel):
            await interaction.response.send_message("Questo comando funziona solo nei canali della guild.", ephemeral=True)
            return
        enabled = 1 if state.value == "on" else 0
        await ctx.database.upsert_channel(
            channel_id=str(interaction.channel.id),
            guild_id=str(interaction.guild_id),
            name=interaction.channel.name,
            enabled=enabled,
            channel_type=str(interaction.channel.type),
            category_id=str(interaction.channel.category_id) if interaction.channel.category_id else None,
            is_nsfw=1 if interaction.channel.is_nsfw() else 0,
            slowmode_delay=interaction.channel.slowmode_delay,
        )
        await interaction.response.send_message(
            f"Canale {'abilitato' if enabled else 'disabilitato'} per la raccolta eventi.",
            ephemeral=True,
        )

    @bm_group.command(name="retention", description="Gestisci la retention dei dati")
    @app_commands.describe(action="get/set", days="Numero di giorni di retention")
    @app_commands.choices(action=[app_commands.Choice(name="get", value="get"), app_commands.Choice(name="set", value="set")])
    async def retention_command(
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        days: int | None = None,
    ) -> None:
        if not await check_permission(interaction, "bm.retention", ctx):
            return
        if action.value == "get":
            current = await ctx.retention.get_retention_days()
            await interaction.response.send_message(f"Retention attuale: {current} giorni.", ephemeral=True)
            return
        if days is None or days <= 0:
            await interaction.response.send_message("Specifica un numero di giorni valido.", ephemeral=True)
            return
        await ctx.retention.set_retention_days(days)
        await interaction.response.send_message(f"Retention aggiornata a {days} giorni.", ephemeral=True)

    @bm_group.command(name="backfill", description="Gestisci il backfill dei dati")
    @app_commands.describe(state="on/off", days="Numero di giorni di backfill")
    @app_commands.choices(state=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
    async def backfill_command(
        interaction: discord.Interaction,
        state: app_commands.Choice[str] | None = None,
        days: int | None = None,
    ) -> None:
        if not await check_permission(interaction, "bm.backfill", ctx):
            return
        if interaction.response.is_done():
            responder = interaction.followup
        else:
            responder = interaction.response
        if state is None and days is None:
            current_days = await ctx.backfill.get_backfill_days()
            enabled = await ctx.backfill.is_enabled()
            await responder.send_message(
                f"Backfill {'attivo' if enabled else 'disattivato'} ({current_days} giorni).",
                ephemeral=True,
            )
            return

        if days is not None:
            if days <= 0:
                await responder.send_message("Specifica un numero di giorni valido.", ephemeral=True)
                return
            await ctx.backfill.set_backfill_days(days)

        if state is not None:
            await ctx.backfill.set_enabled(state.value == "on")

        if await ctx.backfill.is_enabled():
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True, thinking=True)
            result = await ctx.backfill.run_once(force_full_window=True)
            await interaction.followup.send(
                "Backfill completato. "
                f"Messaggi: {result.messages}, Eventi: {result.events}, Canali: {result.channels}, Errori: {result.errors}.",
                ephemeral=True,
            )
            return

        await responder.send_message("Backfill disattivato.", ephemeral=True)

    @bm_group.command(name="ai", description="Abilita o disabilita il servizio AI")
    @app_commands.describe(state="on/off")
    @app_commands.choices(state=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
    async def ai_command(interaction: discord.Interaction, state: app_commands.Choice[str]) -> None:
        if not await check_permission(interaction, "bm.ai", ctx):
            return
        enabled = state.value == "on"
        await ctx.ai.set_enabled(enabled)
        await interaction.response.send_message(
            f"AI {'abilitata' if enabled else 'disabilitata'}.",
            ephemeral=True,
        )

    @bm_group.command(name="ai-model", description="Imposta il modello AI per un task")
    @app_commands.describe(task="Task AI", model="Nome modello")
    @app_commands.choices(
        task=[
            app_commands.Choice(name="summary", value="summary"),
            app_commands.Choice(name="transcription", value="transcription"),
            app_commands.Choice(name="translation", value="translation"),
        ]
    )
    async def ai_model_command(
        interaction: discord.Interaction,
        task: app_commands.Choice[str],
        model: str,
    ) -> None:
        if not await check_permission(interaction, "bm.ai-model", ctx):
            return
        await ctx.ai.set_model(task.value, model)
        await interaction.response.send_message(
            f"Modello per {task.value} aggiornato a {model}.",
            ephemeral=True,
        )

    @bm_group.command(name="footer", description="Configura footer globali e per servizio")
    @app_commands.describe(
        version="Versione branding footer",
        frase_globale="Frase finale globale",
        servizio="Nome servizio per frase specifica",
        frase_servizio="Frase finale specifica servizio (vuota = reset)",
    )
    async def footer_command(
        interaction: discord.Interaction,
        version: str | None = None,
        frase_globale: str | None = None,
        servizio: str | None = None,
        frase_servizio: str | None = None,
    ) -> None:
        if not await check_permission(interaction, "bm.footer", ctx):
            return
        if ctx.footer is None:
            await interaction.response.send_message("Footer service non disponibile.", ephemeral=True)
            return

        v = _clean_opt(version)
        fg = _clean_opt(frase_globale)
        srv = _clean_opt(servizio)
        fs = _clean_opt(frase_servizio)

        if version is not None:
            await ctx.footer.set_version(v)
        if frase_globale is not None:
            await ctx.footer.set_global_phrase(fg)
        if servizio is not None:
            if srv is None:
                await interaction.response.send_message("Servizio non valido.", ephemeral=True)
                return
            await ctx.footer.set_service_phrase(srv, fs)

        if all(param is None for param in (version, frase_globale, servizio, frase_servizio)):
            current_version = await ctx.footer.get_version()
            current_global = await ctx.footer.get_global_phrase()
            phrases = await ctx.footer.get_service_phrases()
            lines = [
                f"Versione: {_format_value(current_version)}",
                f"Frase globale: {_format_value(current_global)}",
                "Frasi per servizio:",
            ]
            if phrases:
                lines.extend([f"- {name}: {text}" for name, text in phrases.items()])
            else:
                lines.append("- (nessuna)")
            await interaction.response.send_message("\n".join(lines), ephemeral=True)
            return

        await interaction.response.send_message("Configurazione footer aggiornata.", ephemeral=True)

    @bm_group.command(name="footer_status", description="Mostra footer renderizzato per tutti i servizi")
    async def footer_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.footer_status", ctx):
            return
        if ctx.footer is None:
            await interaction.response.send_message("Footer service non disponibile.", ephemeral=True)
            return

        service_phrases = await ctx.footer.get_service_phrases()
        global_phrase = await ctx.footer.get_global_phrase()
        known_services = await ctx.footer.get_known_services()
        service_sources = await ctx.footer.get_known_service_sources()
        lines: list[str] = []
        for service_name in known_services:
            footer, _ = await ctx.footer.render_footer(
                service_name=service_name,
                contributors=[],
                used_local_processing=True,
            )
            phrase = service_phrases.get(service_name) or global_phrase or "(nessuna)"
            source = ",".join(service_sources.get(service_name, [])) or "unknown"
            lines.append(f"{service_name} → {footer}\n  frase: {phrase}\n  origine: {source}")

        if not lines:
            await interaction.response.send_message("Nessun servizio footer noto.", ephemeral=True)
            return

        chunks: list[str] = []
        current = ""
        for line in lines:
            candidate = f"{current}\n{line}" if current else line
            if len(candidate) > 1800 and current:
                chunks.append(current)
                current = line
            else:
                current = candidate
        if current:
            chunks.append(current)

        await interaction.response.send_message(chunks[0], ephemeral=True)
        for extra in chunks[1:]:
            await interaction.followup.send(extra, ephemeral=True)
