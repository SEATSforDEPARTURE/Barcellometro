from __future__ import annotations

import logging
import os

import discord
from discord import app_commands

from app.core.service_registry import ServiceRegistry

logger = logging.getLogger(__name__)


def setup(registry: ServiceRegistry) -> None:
    bot: discord.Client = registry.get("bot")
    database = registry.get("database")
    retention = registry.get("retention")
    backfill = registry.get("backfill")
    guard = registry.get("guard")
    status_service = registry.get("status")
    ai_service = registry.get("ai")
    voice_ingest = registry.get("voice_ingest") if registry.has("voice_ingest") else None
    config = registry.get("config")

    guild = discord.Object(id=config.guild_id)

    barcellometro_group = app_commands.Group(name="barcellometro", description="Controlli Barcellometro")
    role_group = app_commands.Group(name="role", description="Gestione permessi e limiti")
    stt_group = app_commands.Group(name="stt", description="Impostazioni STT")
    translate_group = app_commands.Group(name="translate", description="Impostazioni traduzione")
    audio_notes_group = app_commands.Group(name="audio_notes", description="Note vocali")
    voice_ingest_group = app_commands.Group(name="voice_ingest", description="Ingest da canale vocale")
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

    def voice_ingest_key(bot_id: int, key: str) -> str:
        return f"voice_ingest.{bot_id}.{key}"

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

    @voice_ingest_group.command(name="on", description="Abilita ingest vocale")
    @app_commands.describe(bot="Bot worker", voice_channel="Canale vocale", text_channel="Canale testuale")
    async def voice_ingest_on(
        interaction: discord.Interaction,
        bot: discord.User,
        voice_channel: discord.VoiceChannel | None = None,
        text_channel: discord.TextChannel | None = None,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.voice_ingest.on"):
            return
        if not bot.bot:
            await interaction.response.send_message("Seleziona un bot worker valido.", ephemeral=True)
            return
        if bot.id is None:
            await interaction.response.send_message("Bot worker non valido.", ephemeral=True)
            return
        resolved_voice = voice_channel
        if resolved_voice is None and isinstance(interaction.user, discord.Member):
            resolved_voice = interaction.user.voice.channel if interaction.user.voice else None
        if resolved_voice is None:
            await interaction.response.send_message("Specifica un canale vocale.", ephemeral=True)
            return
        resolved_text = text_channel or (interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None)
        if resolved_text is None:
            await interaction.response.send_message("Specifica un canale testuale.", ephemeral=True)
            return
        await set_setting(voice_ingest_key(bot.id, "enabled"), "true")
        await set_setting(voice_ingest_key(bot.id, "auto_join"), "true")
        await set_setting(voice_ingest_key(bot.id, "target_voice_channel_id"), str(resolved_voice.id))
        await set_setting(voice_ingest_key(bot.id, "target_text_channel_id"), str(resolved_text.id))
        min_users_key = voice_ingest_key(bot.id, "min_users_to_join")
        if await database.get_setting(min_users_key) is None:
            await set_setting(min_users_key, "1")
        await interaction.response.send_message(
            f"Ingest vocale abilitato su {resolved_voice.name}.",
            ephemeral=True,
        )
        if voice_ingest and resolved_voice and bot.user and bot.user.id == bot.id:
            await voice_ingest.join(resolved_voice)

    @voice_ingest_group.command(name="off", description="Disabilita ingest vocale")
    @app_commands.describe(bot="Bot worker")
    async def voice_ingest_off(interaction: discord.Interaction, bot: discord.User) -> None:
        if not await check_permission(interaction, "barcellometro.voice_ingest.off"):
            return
        if not bot.bot:
            await interaction.response.send_message("Seleziona un bot worker valido.", ephemeral=True)
            return
        await set_setting(voice_ingest_key(bot.id, "enabled"), "false")
        await interaction.response.send_message("Ingest vocale disabilitato.", ephemeral=True)
        if voice_ingest and bot.user and bot.user.id == bot.id:
            await voice_ingest.leave()

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

    bot.tree.add_command(barcellometro_group, guild=guild)
    bot.tree.add_command(status_group, guild=guild)

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
