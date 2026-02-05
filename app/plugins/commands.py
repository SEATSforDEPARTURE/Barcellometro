from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

import discord
from discord import app_commands

from app.core.service_registry import ServiceRegistry
from app.services.barcello import BarcelloService
from app.services.entitlements import EntitlementsService
from app.services.ingest import EventEnvelope, IngestService

logger = logging.getLogger(__name__)


def setup(registry: ServiceRegistry) -> None:
    bot: discord.Client = registry.get("bot")
    database = registry.get("database")
    entitlements = EntitlementsService(database)
    registry.register("entitlements", entitlements)
    barcello = BarcelloService(database)
    registry.register("barcello", barcello)
    retention = registry.get("retention")
    backfill = registry.get("backfill")
    guard = registry.get("guard")
    status_service = registry.get("status")
    ai_service = registry.get("ai")
    voice_ingest = registry.get("voice_ingest") if registry.has("voice_ingest") else None
    ingest: IngestService = registry.get("ingest")
    config = registry.get("config")

    guild = discord.Object(id=config.guild_id)

    barcellometro_group = app_commands.Group(name="barcellometro", description="Controlli Barcellometro")
    role_group = app_commands.Group(name="role", description="Gestione permessi e limiti")
    stt_group = app_commands.Group(name="stt", description="Impostazioni STT")
    translate_group = app_commands.Group(name="translate", description="Impostazioni traduzione")
    audio_notes_group = app_commands.Group(name="audio_notes", description="Note vocali")
    voice_ingest_group = app_commands.Group(name="voice_ingest", description="Ingest da canale vocale")
    privacy_group = app_commands.Group(name="privacy", description="Privacy per voice ingest")
    status_group = app_commands.Group(name="status", description="Stato servizi")
    barcellometro_group.add_command(role_group)
    barcellometro_group.add_command(stt_group)
    barcellometro_group.add_command(translate_group)
    barcellometro_group.add_command(audio_notes_group)
    barcellometro_group.add_command(voice_ingest_group)

    async def check_permission(interaction: discord.Interaction, command_name: str) -> bool:
        guild = interaction.guild
        is_admin = bool(guild and interaction.user.guild_permissions.administrator)
        role_ids = [role.id for role in getattr(interaction.user, "roles", [])]
        result = await guard.check_command(
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
            role_ids=role_ids,
            command=command_name,
            is_admin=is_admin,
        )
        if result.allowed:
            return True
        message = result.reason
        if result.remaining is not None:
            message += f" Utilizzi rimanenti: {result.remaining}."
        if result.cooldown_remaining is not None:
            message += f" Cooldown: {result.cooldown_remaining}s."
        ephemeral = interaction.guild_id is not None
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(message, ephemeral=ephemeral)
        return False

    async def ensure_admin(interaction: discord.Interaction) -> bool:
        guild = interaction.guild
        is_admin = bool(guild and interaction.user.guild_permissions.administrator)
        if is_admin:
            return True
        ephemeral = interaction.guild_id is not None
        if interaction.response.is_done():
            await interaction.followup.send("Solo admin.", ephemeral=ephemeral)
        else:
            await interaction.response.send_message("Solo admin.", ephemeral=ephemeral)
        return False

    async def set_setting(key: str, value: str) -> None:
        await database.set_setting(key, value)

    async def get_setting(key: str, default: str) -> str:
        stored = await database.get_setting(key)
        return stored if stored is not None else default

    async def send_ephemeral(interaction: discord.Interaction, message: str) -> None:
        ephemeral = interaction.guild_id is not None
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(message, ephemeral=ephemeral)

    def voice_ingest_key(bot_id: int, key: str) -> str:
        return f"voice_ingest.{bot_id}.{key}"

    async def resolve_voice_channel(
        interaction: discord.Interaction,
        voice_channel: discord.VoiceChannel | None,
    ) -> discord.VoiceChannel | None:
        if voice_channel is not None:
            return voice_channel
        if isinstance(interaction.user, discord.Member) and interaction.user.voice:
            return interaction.user.voice.channel
        return None

    async def resolve_affected_bots(voice_channel: discord.VoiceChannel) -> list[int]:
        bot_ids = {member.id for member in voice_channel.members if member.bot}
        if not bot_ids:
            bot_ids.update(
                int(bot_id)
                for bot_id in await database.find_voice_ingest_bots_for_voice_channel(str(voice_channel.id))
                if bot_id.isdigit()
            )
        return sorted(bot_ids)

    async def emit_privacy_event(
        interaction: discord.Interaction,
        event_type: str,
        voice_channel: discord.VoiceChannel,
        affected_bot_ids: list[int],
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        await ingest.emit(
            EventEnvelope(
                event_id=str(uuid4()),
                event_type=event_type,
                platform="discord",
                ts=ts,
                guild_id=str(interaction.guild_id) if interaction.guild_id else None,
                channel_id=str(voice_channel.id),
                thread_id=None,
                author_id=str(interaction.user.id),
                content=None,
                meta={"voice_channel_id": str(voice_channel.id), "affected_bot_ids": affected_bot_ids},
            )
        )

    @barcellometro_group.command(name="check", description="Abilita o disabilita la raccolta eventi nel canale")
    @app_commands.describe(state="on/off")
    @app_commands.choices(state=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
    async def check_command(interaction: discord.Interaction, state: app_commands.Choice[str]) -> None:
        if not await check_permission(interaction, "barcellometro.check"):
            return
        if not interaction.channel or not isinstance(interaction.channel, discord.abc.GuildChannel):
            await interaction.response.send_message("Questo comando funziona solo nei canali della guild.", ephemeral=True)
            return
        enabled = 1 if state.value == "on" else 0
        await database.upsert_channel(
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

    @barcellometro_group.command(name="retention", description="Gestisci la retention dei dati")
    @app_commands.describe(action="get/set", days="Numero di giorni di retention")
    @app_commands.choices(action=[app_commands.Choice(name="get", value="get"), app_commands.Choice(name="set", value="set")])
    async def retention_command(
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        days: int | None = None,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.retention"):
            return
        if action.value == "get":
            current = await retention.get_retention_days()
            await interaction.response.send_message(f"Retention attuale: {current} giorni.", ephemeral=True)
            return
        if days is None or days <= 0:
            await interaction.response.send_message("Specifica un numero di giorni valido.", ephemeral=True)
            return
        await retention.set_retention_days(days)
        await interaction.response.send_message(f"Retention aggiornata a {days} giorni.", ephemeral=True)

    @barcellometro_group.command(name="backfill", description="Gestisci il backfill dei dati")
    @app_commands.describe(state="on/off", days="Numero di giorni di backfill")
    @app_commands.choices(state=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
    async def backfill_command(
        interaction: discord.Interaction,
        state: app_commands.Choice[str] | None = None,
        days: int | None = None,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.backfill"):
            return
        if interaction.response.is_done():
            responder = interaction.followup
        else:
            responder = interaction.response
        if state is None and days is None:
            current_days = await backfill.get_backfill_days()
            enabled = await backfill.is_enabled()
            await responder.send_message(
                f"Backfill {'attivo' if enabled else 'disattivato'} ({current_days} giorni).",
                ephemeral=True,
            )
            return

        if days is not None:
            if days <= 0:
                await responder.send_message("Specifica un numero di giorni valido.", ephemeral=True)
                return
            await backfill.set_backfill_days(days)

        if state is not None:
            await backfill.set_enabled(state.value == "on")

        if await backfill.is_enabled():
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True, thinking=True)
            result = await backfill.run_once(force_full_window=True)
            await interaction.followup.send(
                "Backfill completato. "
                f"Messaggi: {result.messages}, Eventi: {result.events}, Canali: {result.channels}, Errori: {result.errors}.",
                ephemeral=True,
            )
            return

        await responder.send_message("Backfill disattivato.", ephemeral=True)

    @barcellometro_group.command(name="ai", description="Abilita o disabilita il servizio AI")
    @app_commands.describe(state="on/off")
    @app_commands.choices(state=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
    async def ai_command(interaction: discord.Interaction, state: app_commands.Choice[str]) -> None:
        if not await check_permission(interaction, "barcellometro.ai"):
            return
        enabled = state.value == "on"
        await ai_service.set_enabled(enabled)
        await interaction.response.send_message(
            f"AI {'abilitata' if enabled else 'disabilitata'}.",
            ephemeral=True,
        )

    @barcellometro_group.command(name="ai-model", description="Imposta il modello AI per un task")
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
        if not await check_permission(interaction, "barcellometro.ai-model"):
            return
        await ai_service.set_model(task.value, model)
        await interaction.response.send_message(
            f"Modello per {task.value} aggiornato a {model}.",
            ephemeral=True,
        )

    @stt_group.command(name="backend", description="Imposta il backend STT")
    @app_commands.choices(
        backend=[
            app_commands.Choice(name="local", value="local"),
            app_commands.Choice(name="ai", value="ai"),
        ]
    )
    async def stt_backend_command(
        interaction: discord.Interaction,
        backend: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.stt.backend"):
            return
        await set_setting("stt.backend", backend.value)
        await interaction.response.send_message(f"Backend STT impostato su {backend.value}.", ephemeral=True)

    @stt_group.command(name="model", description="Imposta il modello STT locale")
    @app_commands.choices(
        model=[
            app_commands.Choice(name="small", value="small"),
            app_commands.Choice(name="medium", value="medium"),
            app_commands.Choice(name="large-v3", value="large-v3"),
        ]
    )
    async def stt_model_command(
        interaction: discord.Interaction,
        model: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.stt.model"):
            return
        await set_setting("stt.local.model", model.value)
        await interaction.response.send_message(f"Modello STT impostato su {model.value}.", ephemeral=True)

    @stt_group.command(name="compute", description="Imposta il compute type STT locale")
    @app_commands.choices(
        compute=[
            app_commands.Choice(name="int8", value="int8"),
            app_commands.Choice(name="int8_float16", value="int8_float16"),
            app_commands.Choice(name="float16", value="float16"),
        ]
    )
    async def stt_compute_command(
        interaction: discord.Interaction,
        compute: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.stt.compute"):
            return
        await set_setting("stt.local.compute_type", compute.value)
        await interaction.response.send_message(f"Compute STT impostato su {compute.value}.", ephemeral=True)

    @stt_group.command(name="beam", description="Imposta il beam size STT locale")
    @app_commands.choices(
        beam=[
            app_commands.Choice(name="1", value="1"),
            app_commands.Choice(name="3", value="3"),
            app_commands.Choice(name="5", value="5"),
        ]
    )
    async def stt_beam_command(
        interaction: discord.Interaction,
        beam: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.stt.beam"):
            return
        await set_setting("stt.local.beam_size", beam.value)
        await interaction.response.send_message(f"Beam STT impostato su {beam.value}.", ephemeral=True)

    @stt_group.command(name="language", description="Imposta la lingua STT locale")
    @app_commands.choices(
        language=[
            app_commands.Choice(name="it", value="it"),
            app_commands.Choice(name="auto", value="auto"),
        ]
    )
    async def stt_language_command(
        interaction: discord.Interaction,
        language: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.stt.language"):
            return
        await set_setting("stt.local.language_hint", language.value)
        await interaction.response.send_message(f"Lingua STT impostata su {language.value}.", ephemeral=True)

    @translate_group.command(name="backend", description="Imposta il backend di traduzione")
    @app_commands.choices(
        backend=[
            app_commands.Choice(name="local", value="local"),
            app_commands.Choice(name="ai", value="ai"),
        ]
    )
    async def translate_backend_command(
        interaction: discord.Interaction,
        backend: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.translate.backend"):
            return
        await set_setting("translate.backend", backend.value)
        await interaction.response.send_message(
            f"Backend traduzione impostato su {backend.value}.",
            ephemeral=True,
        )

    @translate_group.command(name="target", description="Imposta la lingua target")
    @app_commands.choices(target=[app_commands.Choice(name="it", value="it")])
    async def translate_target_command(
        interaction: discord.Interaction,
        target: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.translate.target"):
            return
        await set_setting("translate.target_lang", target.value)
        await interaction.response.send_message(
            f"Lingua target impostata su {target.value}.",
            ephemeral=True,
        )

    @audio_notes_group.command(name="on", description="Abilita le note vocali")
    async def audio_notes_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.audio_notes.on"):
            return
        await set_setting("audio_notes.enabled", "true")
        await interaction.response.send_message("Note vocali abilitate.", ephemeral=True)

    @audio_notes_group.command(name="off", description="Disabilita le note vocali")
    async def audio_notes_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.audio_notes.off"):
            return
        await set_setting("audio_notes.enabled", "false")
        await interaction.response.send_message("Note vocali disabilitate.", ephemeral=True)

    @audio_notes_group.command(name="status", description="Mostra lo stato note vocali")
    async def audio_notes_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.audio_notes.status"):
            return
        enabled = (await get_setting("audio_notes.enabled", "false")).lower() in {"1", "true", "yes", "y"}
        max_mb = await get_setting("audio_notes.max_mb", os.getenv("AUDIO_NOTES_MAX_MB", "25"))
        max_duration = await get_setting("audio_notes.max_duration_s", os.getenv("AUDIO_NOTES_MAX_DURATION_S", "180"))
        max_chars = await get_setting("audio_notes.discord_max_chars", os.getenv("AUDIO_NOTES_DISCORD_MAX_CHARS", "1900"))
        queue_max = await get_setting("audio_notes.queue_max", os.getenv("AUDIO_NOTES_QUEUE_MAX", "50"))
        await interaction.response.send_message(
            "Audio notes "
            f"{'attivo' if enabled else 'disattivo'} | "
            f"max_mb={max_mb}, max_duration_s={max_duration}, max_chars={max_chars}, queue_max={queue_max}",
            ephemeral=True,
        )

    @audio_notes_group.command(name="limits", description="Imposta i limiti note vocali")
    @app_commands.describe(
        max_mb="Massimo MB",
        max_duration_s="Durata massima in secondi",
        discord_max_chars="Massimo caratteri per messaggio",
        queue_max="Dimensione coda",
    )
    async def audio_notes_limits_command(
        interaction: discord.Interaction,
        max_mb: int,
        max_duration_s: int,
        discord_max_chars: int,
        queue_max: int,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.audio_notes.limits"):
            return
        if max_mb <= 0 or max_duration_s <= 0 or discord_max_chars <= 0 or queue_max <= 0:
            await interaction.response.send_message("Specifica limiti validi (> 0).", ephemeral=True)
            return
        await set_setting("audio_notes.max_mb", str(max_mb))
        await set_setting("audio_notes.max_duration_s", str(max_duration_s))
        await set_setting("audio_notes.discord_max_chars", str(discord_max_chars))
        await set_setting("audio_notes.queue_max", str(queue_max))
        await interaction.response.send_message("Limiti note vocali aggiornati.", ephemeral=True)

    @privacy_group.command(name="on", description="Attiva privacy (disconnette il bot dal vocale)")
    @app_commands.describe(voice_channel="Canale vocale (opzionale)")
    async def privacy_on(
        interaction: discord.Interaction,
        voice_channel: discord.VoiceChannel | None = None,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.privacy.on"):
            return
        resolved_voice = await resolve_voice_channel(interaction, voice_channel)
        if resolved_voice is None:
            await interaction.response.send_message("Specifica un canale vocale.", ephemeral=True)
            return
        bot_ids = await resolve_affected_bots(resolved_voice)
        if not bot_ids:
            await interaction.response.send_message("Nessun bot configurato per questo canale vocale.", ephemeral=True)
            return
        for bot_id in bot_ids:
            await set_setting(voice_ingest_key(bot_id, "privacy_mode"), "true")
            await set_setting(voice_ingest_key(bot_id, "auto_join"), "false")
            await set_setting(voice_ingest_key(bot_id, "enabled"), "true")
        await emit_privacy_event(interaction, "voice.privacy_on", resolved_voice, bot_ids)
        if voice_ingest and bot.user and bot.user.id in bot_ids:
            await voice_ingest.leave()
        await interaction.response.send_message(
            f"Privacy attivata per {resolved_voice.name}. Bot interessati: {len(bot_ids)}.",
            ephemeral=True,
        )

    @privacy_group.command(name="off", description="Disattiva privacy (riabilita auto-join)")
    @app_commands.describe(voice_channel="Canale vocale (opzionale)")
    async def privacy_off(
        interaction: discord.Interaction,
        voice_channel: discord.VoiceChannel | None = None,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.privacy.off"):
            return
        resolved_voice = await resolve_voice_channel(interaction, voice_channel)
        if resolved_voice is None:
            await interaction.response.send_message("Specifica un canale vocale.", ephemeral=True)
            return
        bot_ids = await resolve_affected_bots(resolved_voice)
        if not bot_ids:
            await interaction.response.send_message("Nessun bot configurato per questo canale vocale.", ephemeral=True)
            return
        for bot_id in bot_ids:
            await set_setting(voice_ingest_key(bot_id, "privacy_mode"), "false")
            await set_setting(voice_ingest_key(bot_id, "auto_join"), "true")
            await set_setting(voice_ingest_key(bot_id, "enabled"), "true")
        await emit_privacy_event(interaction, "voice.privacy_off", resolved_voice, bot_ids)
        non_bot_members = [m for m in resolved_voice.members if not m.bot]
        if voice_ingest and bot.user and bot.user.id in bot_ids and non_bot_members:
            await voice_ingest.join(resolved_voice)
        await interaction.response.send_message(
            f"Privacy disattivata per {resolved_voice.name}. Bot interessati: {len(bot_ids)}.",
            ephemeral=True,
        )

    @privacy_group.command(name="status", description="Mostra lo stato privacy")
    @app_commands.describe(voice_channel="Canale vocale (opzionale)")
    async def privacy_status(
        interaction: discord.Interaction,
        voice_channel: discord.VoiceChannel | None = None,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.privacy.status"):
            return
        resolved_voice = await resolve_voice_channel(interaction, voice_channel)
        if resolved_voice is None:
            await interaction.response.send_message("Specifica un canale vocale.", ephemeral=True)
            return
        bot_ids = await resolve_affected_bots(resolved_voice)
        if not bot_ids:
            await interaction.response.send_message("Nessun bot configurato per questo canale vocale.", ephemeral=True)
            return
        states = []
        for bot_id in bot_ids:
            privacy_mode = (await get_setting(voice_ingest_key(bot_id, "privacy_mode"), "false")).lower() in {"1", "true", "yes", "y"}
            auto_join = (await get_setting(voice_ingest_key(bot_id, "auto_join"), "true")).lower() in {"1", "true", "yes", "y"}
            enabled = (await get_setting(voice_ingest_key(bot_id, "enabled"), "true")).lower() in {"1", "true", "yes", "y"}
            states.append((bot_id, privacy_mode, auto_join, enabled))
        privacy_values = {state[1] for state in states}
        last_event = await database.get_last_privacy_event(str(resolved_voice.id))
        last_change = "N/A"
        if last_event:
            actor = f"<@{last_event['actor_id']}>" if last_event.get("actor_id") else "sconosciuto"
            last_change = f"{last_event['event_type']} alle {last_event['ts']} da {actor}"
        if len(privacy_values) == 1:
            status = "ON" if True in privacy_values else "OFF"
            message = (
                f"Privacy {status} su {resolved_voice.name}. Bot: {len(bot_ids)}. "
                f"Ultimo cambio: {last_change}"
            )
        else:
            lines = [
                f"Bot {bot_id}: privacy={'ON' if privacy else 'OFF'}, auto_join={auto_join}, enabled={enabled}"
                for bot_id, privacy, auto_join, enabled in states
            ]
            message = (
                f"Privacy su {resolved_voice.name} (stati misti):\n"
                + "\n".join(lines)
                + f"\nUltimo cambio: {last_change}"
            )
        await interaction.response.send_message(message, ephemeral=True)

    @voice_ingest_group.command(name="join", description="Join manuale del canale vocale")
    @app_commands.describe(voice_channel="Canale vocale")
    async def voice_ingest_join(
        interaction: discord.Interaction,
        voice_channel: discord.VoiceChannel,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.voice_ingest.join"):
            return
        if not bot.user:
            await interaction.response.send_message("Bot non pronto.", ephemeral=True)
            return
        await set_setting(voice_ingest_key(bot.user.id, "target_voice_channel_id"), str(voice_channel.id))
        await interaction.response.send_message(
            f"Richiesto join su {voice_channel.name}.",
            ephemeral=True,
        )
        if voice_ingest:
            await voice_ingest.join(voice_channel)

    @voice_ingest_group.command(name="leave", description="Leave manuale del canale vocale")
    async def voice_ingest_leave(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.voice_ingest.leave"):
            return
        await interaction.response.send_message("Richiesto leave dal canale vocale.", ephemeral=True)
        if voice_ingest:
            await voice_ingest.leave()

    @status_group.command(name="barcellometro", description="Stato generale o di un servizio/plugin")
    @app_commands.describe(service="Nome servizio o plugin")
    async def status_barcellometro(interaction: discord.Interaction, service: str | None = None) -> None:
        if not await check_permission(interaction, "status.barcellometro"):
            return
        if service:
            status = status_service.component_status(service)
            message = (
                f"**{service}**\n"
                f"Active: {status['active']}\n"
                f"State: {status['state']}\n"
                f"Metrics: {status['metrics']}"
            )
            await interaction.response.send_message(message, ephemeral=True)
            return
        general = await status_service.general_status()
        message = (
            "**Barcellometro Status**\n"
            f"Bot: online\n"
            f"DB Path: {general['db_path']}\n"
            f"Retention Days: {general['retention_days']}\n"
            f"Enabled Channels: {general['enabled_channels']}\n"
            f"Users: {general['users_count']}\n"
            f"Messages: {general['messages_count']}\n"
            f"Events: {general['events_count']}\n"
            f"Last Event: {general['last_event_ts']}"
        )
        await interaction.response.send_message(message, ephemeral=True)

    # Settings JSON for /barcello (entitlements.policies):
    # {
    #   "commands": {
    #     "barcello": {
    #       "profiles": {
    #         "<profile>": {
    #           "allowed": true,
    #           "output": {
    #             "show_score": true,
    #             "show_motivation": true,
    #             "show_trend": true,
    #             "show_advice": true,
    #             "show_mod_metrics": false
    #           },
    #           "capabilities": ["analysis.ai_preferred"],
    #           "messages": {
    #             "dm_text": "Serve PLUS.",
    #             "footer_text": "Passa a PRO per il trend."
    #           }
    #         }
    #       }
    #     }
    #   },
    #   "features": {
    #     "ai": { "allowed_profiles": ["role2", "role3", "mod"] }
    #   }
    # }
    @app_commands.command(name="barcello", description="Mostra lo stato del barcello (in DM)")
    @app_commands.describe(window_minutes="Finestra in minuti")
    async def barcello_command(interaction: discord.Interaction, window_minutes: int | None = None) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Questo comando funziona solo nei canali della guild.")
            return

        entitlements_service: EntitlementsService = registry.get("entitlements")
        config = await entitlements_service.get_command_profile_config(interaction.user, "barcello")
        profile = await entitlements_service.resolve_profile(interaction.user)

        async def try_send_dm(content: str) -> bool:
            try:
                await interaction.user.send(content)
                return True
            except discord.Forbidden:
                return False

        if not config["allowed"]:
            dm_text = config["messages"].get("dm_text", "Serve almeno PLUS per usare /barcello.")
            if await try_send_dm(dm_text):
                await send_ephemeral(interaction, "Ti ho inviato un DM")
            else:
                await send_ephemeral(interaction, "Apri i DM per ricevere la risposta")
            return

        if not await check_permission(interaction, "barcello"):
            return

        if window_minutes is None:
            raw_default = await get_setting("barcello.default_window_minutes", "30")
            try:
                window_minutes = int(raw_default)
            except ValueError:
                window_minutes = 30
        if window_minutes <= 0:
            window_minutes = 30

        result = await barcello.compute_channel(
            str(interaction.guild_id),
            str(interaction.channel_id),
            window_minutes,
        )

        reasons_lines = [f"- {reason['label']} ({reason['summary']})" for reason in result.reasons]
        reasons_text = "\n".join(reasons_lines) if reasons_lines else "Nessun segnale critico rilevato."
        trend_text = ""
        if result.trend:
            direction = result.trend.get("direction", "stable")
            delta = result.trend.get("delta", 0)
            trend_label = {"stable": "stabile", "improving": "in miglioramento", "worsening": "in peggioramento"}.get(
                direction,
                direction,
            )
            trend_text = f"Trend {trend_label} (Δ {delta:+d})."
        advice_text = "\n".join(f"- {item}" for item in (result.advice or []))

        if "analysis.ai_preferred" in (config.get("capabilities") or []):
            if registry.has("ai"):
                ai_enabled = await entitlements_service.is_feature_allowed(interaction.user, "ai")
                ai_service_enabled = ai_service.is_enabled() if ai_service else False
                if ai_enabled and ai_service_enabled and ai_service:
                    client = ai_service.client()
                    model = ai_service.get_model("summary")
                    if client and model:
                        try:
                            response = await client.responses.create(
                                model=model,
                                input=[
                                    {
                                        "role": "system",
                                        "content": (
                                            "Riscrivi i testi forniti in italiano, tono neutro e conciso. "
                                            "Non includere nomi utenti o attribuzioni personali. "
                                            "Non aggiungere dettagli non presenti. "
                                            "Restituisci solo JSON con chiavi: motivation, trend, advice."
                                        ),
                                    },
                                    {
                                        "role": "user",
                                        "content": json.dumps(
                                            {"motivation": reasons_text, "trend": trend_text, "advice": advice_text},
                                            ensure_ascii=False,
                                        ),
                                    },
                                ],
                            )
                            ai_payload = json.loads(response.output_text.strip())
                            reasons_text = ai_payload.get("motivation", reasons_text) or reasons_text
                            trend_text = ai_payload.get("trend", trend_text) or trend_text
                            advice_text = ai_payload.get("advice", advice_text) or advice_text
                        except Exception:  # noqa: BLE001
                            logger.exception("AI barcello enrichment failed")

        lines: list[str] = []
        output_flags = config.get("output", {})
        if output_flags.get("show_score"):
            lines.append(f"Score: {result.score}/100")
            lines.append(f"Colore: {result.color}")
            lines.append(f"Finestra: {window_minutes} min")
        if output_flags.get("show_motivation"):
            lines.append("Motivazioni:")
            lines.append(reasons_text)
        if output_flags.get("show_trend") and trend_text:
            lines.append(trend_text)
        if output_flags.get("show_advice") and advice_text:
            lines.append("Consigli:")
            lines.append(advice_text)
        if output_flags.get("show_mod_metrics") and profile == "mod":
            lines.append("Metriche aggregate:")
            metrics_lines = [f"- {key}: {value}" for key, value in result.metrics.items()]
            lines.extend(metrics_lines or ["- Nessuna metrica disponibile."])

        footer_text = config.get("messages", {}).get("footer_text")
        if footer_text:
            lines.append(footer_text)

        dm_content = "\n".join(lines).strip() or "Nessun dato disponibile."
        if await try_send_dm(dm_content):
            await send_ephemeral(interaction, "Ti ho inviato un DM")
        else:
            await send_ephemeral(interaction, "Apri i DM per ricevere la risposta")

    bot.tree.add_command(barcellometro_group, guild=guild)
    bot.tree.add_command(status_group, guild=guild)
    bot.tree.add_command(privacy_group, guild=guild)
    bot.tree.add_command(barcello_command, guild=guild)

    @role_group.command(name="set-role", description="Imposta limiti per un ruolo su un comando")
    @app_commands.describe(role="Ruolo", command="Nome comando", usage_limit="Limite utilizzi (vuoto = illimitato)", cooldown_seconds="Cooldown in secondi")
    async def role_set_command(
        interaction: discord.Interaction,
        role: discord.Role,
        command: str,
        usage_limit: int | None = None,
        cooldown_seconds: int | None = None,
    ) -> None:
        if not await ensure_admin(interaction):
            return
        if usage_limit is not None and usage_limit <= 0:
            await interaction.response.send_message("Specifica un limite utilizzi valido.", ephemeral=True)
            return
        if cooldown_seconds is not None and cooldown_seconds < 0:
            await interaction.response.send_message("Specifica un cooldown valido.", ephemeral=True)
            return
        await database.upsert_role_policy(
            guild_id=str(interaction.guild_id),
            role_id=str(role.id),
            command=command,
            usage_limit=usage_limit,
            cooldown_seconds=cooldown_seconds,
        )
        await interaction.response.send_message("Policy ruolo aggiornata.", ephemeral=True)

    @role_group.command(name="set-user", description="Imposta limiti per un utente su un comando")
    @app_commands.describe(user="Utente", command="Nome comando", usage_limit="Limite utilizzi (vuoto = illimitato)", cooldown_seconds="Cooldown in secondi")
    async def user_set_command(
        interaction: discord.Interaction,
        user: discord.User,
        command: str,
        usage_limit: int | None = None,
        cooldown_seconds: int | None = None,
    ) -> None:
        if not await ensure_admin(interaction):
            return
        if usage_limit is not None and usage_limit <= 0:
            await interaction.response.send_message("Specifica un limite utilizzi valido.", ephemeral=True)
            return
        if cooldown_seconds is not None and cooldown_seconds < 0:
            await interaction.response.send_message("Specifica un cooldown valido.", ephemeral=True)
            return
        await database.upsert_user_policy(
            guild_id=str(interaction.guild_id),
            user_id=str(user.id),
            command=command,
            usage_limit=usage_limit,
            cooldown_seconds=cooldown_seconds,
        )
        await interaction.response.send_message("Policy utente aggiornata.", ephemeral=True)

    @role_group.command(name="clear-role", description="Rimuove la policy di un ruolo")
    @app_commands.describe(role="Ruolo", command="Nome comando")
    async def role_clear_command(
        interaction: discord.Interaction,
        role: discord.Role,
        command: str,
    ) -> None:
        if not await ensure_admin(interaction):
            return
        await database.delete_role_policy(
            guild_id=str(interaction.guild_id),
            role_id=str(role.id),
            command=command,
        )
        await interaction.response.send_message("Policy ruolo rimossa.", ephemeral=True)

    @role_group.command(name="clear-user", description="Rimuove la policy di un utente")
    @app_commands.describe(user="Utente", command="Nome comando")
    async def user_clear_command(
        interaction: discord.Interaction,
        user: discord.User,
        command: str,
    ) -> None:
        if not await ensure_admin(interaction):
            return
        await database.delete_user_policy(
            guild_id=str(interaction.guild_id),
            user_id=str(user.id),
            command=command,
        )
        await interaction.response.send_message("Policy utente rimossa.", ephemeral=True)

    @role_group.command(name="show-role", description="Mostra le policy di un ruolo")
    @app_commands.describe(role="Ruolo")
    async def role_show_command(interaction: discord.Interaction, role: discord.Role) -> None:
        if not await ensure_admin(interaction):
            return
        rows = await database.fetch_role_policies(str(interaction.guild_id), str(role.id))
        if not rows:
            await interaction.response.send_message("Nessuna policy per questo ruolo.", ephemeral=True)
            return
        lines = []
        for row in rows:
            limit = row["usage_limit"] if row["usage_limit"] is not None else "∞"
            cooldown = row["cooldown_seconds"] if row["cooldown_seconds"] is not None else "∞"
            lines.append(f"{row['command']}: limit={limit} cooldown={cooldown}")
        await interaction.response.send_message("\\n".join(lines), ephemeral=True)

    @role_group.command(name="show-user", description="Mostra le policy di un utente")
    @app_commands.describe(user="Utente")
    async def user_show_command(interaction: discord.Interaction, user: discord.User) -> None:
        if not await ensure_admin(interaction):
            return
        rows = await database.fetch_user_policies(str(interaction.guild_id), str(user.id))
        if not rows:
            await interaction.response.send_message("Nessuna policy per questo utente.", ephemeral=True)
            return
        lines = []
        for row in rows:
            limit = row["usage_limit"] if row["usage_limit"] is not None else "∞"
            cooldown = row["cooldown_seconds"] if row["cooldown_seconds"] is not None else "∞"
            lines.append(f"{row['command']}: limit={limit} cooldown={cooldown}")
        await interaction.response.send_message("\\n".join(lines), ephemeral=True)

    async def handle_ready() -> None:
        try:
            synced = await bot.tree.sync(guild=guild)
            logger.info("Synced %s commands for guild %s", len(synced), config.guild_id)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to sync commands")

    bot.add_listener(handle_ready, "on_ready")
