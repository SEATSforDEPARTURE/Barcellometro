from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from app.db.models.core import TextIngestChannelConfig
from app.services.ingest import IngestEvent, IngestService

ROME_TZ = ZoneInfo("Europe/Rome")
log = logging.getLogger("barcellometro.plugin.ingest_text")


def get_manifest():
    return {
        "name": "ingest_text",
        "version": "1.0.0",
        "description": "Ingest testuale: salvataggio messaggi e controlli per canale",
        "services_required": ["db_session_factory"],
        "services_optional": ["ingest_service"],
        "tables_used": ["text_ingest_channel_config", "ingest_events"],
    }


def _get_registry(interaction: discord.Interaction):
    return getattr(interaction.client, "registry", None)


def _get_session_factory(registry):
    return registry.get("db_session_factory") if registry else None


def _get_ingest_service(registry) -> IngestService | None:
    return registry.get("ingest_service") if registry else None


async def _safe_defer(interaction: discord.Interaction, context: str) -> None:
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)
    except discord.NotFound:
        log.warning("%s: interaction scaduta prima del defer (id=%s)", context, interaction.id)


async def _safe_send(interaction: discord.Interaction, message: str) -> None:
    try:
        await interaction.followup.send(message, ephemeral=True)
    except discord.HTTPException as exc:
        if exc.code == 40060:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(message, ephemeral=True)
            except discord.HTTPException:
                log.warning(
                    "interaction risposta già riconosciuta: impossibile inviare messaggio (id=%s)",
                    interaction.id,
                )
            return
        log.warning(
            "interaction errore risposta (code=%s id=%s)",
            exc.code,
            interaction.id,
        )
    except discord.NotFound:
        log.warning("interaction risposta scaduta: impossibile inviare messaggio (id=%s)", interaction.id)


def _get_or_create_config(session, guild_id: str, channel_id: str) -> TextIngestChannelConfig:
    stmt = select(TextIngestChannelConfig).where(
        (TextIngestChannelConfig.guild_id == guild_id)
        & (TextIngestChannelConfig.channel_id == channel_id)
    )
    config = session.execute(stmt).scalar_one_or_none()
    if config is None:
        config = TextIngestChannelConfig(guild_id=guild_id, channel_id=channel_id)
        session.add(config)
        session.flush()
    return config


def _get_group(bot: commands.Bot) -> app_commands.Group:
    existing = bot.tree.get_command("barcellometro")
    if isinstance(existing, app_commands.Group):
        return existing
    group = app_commands.Group(name="barcellometro", description="Comandi del Barcellometro")
    bot.tree.add_command(group)
    return group


@app_commands.command(name="check", description="Attiva/disattiva l'ingest testuale o imposta l'intervallo")
@app_commands.guild_only()
@app_commands.describe(
    state="on/off per attivare o disattivare l'ingest nel canale",
    minutes="Intervallo in minuti per controlli periodici (default 10)",
)
async def check(
    interaction: discord.Interaction,
    state: str | None = None,
    minutes: int | None = None,
):
    await _safe_defer(interaction, "check")
    registry = _get_registry(interaction)
    session_factory = _get_session_factory(registry)
    if session_factory is None:
        log.warning(
            "check: db_session_factory mancante (guild=%s channel=%s)",
            interaction.guild_id,
            interaction.channel_id,
        )
        await _safe_send(interaction, "❌ db_session_factory non disponibile.")
        return
    if interaction.guild_id is None:
        log.warning("check: comando in DM non supportato (user=%s)", interaction.user.id)
        await _safe_send(interaction, "⚠️ Comando disponibile solo nei server.")
        return

    channel_id = str(interaction.channel_id)
    guild_id = str(interaction.guild_id)

    try:
        with session_factory() as session:
            config = _get_or_create_config(session, guild_id, channel_id)

            if state is None and minutes is None:
                await _safe_send(
                    interaction,
                    "ℹ️ Stato ingest per questo canale:\n"
                    f"• attivo: {'on' if config.enabled else 'off'}\n"
                    f"• intervallo controllo: {config.check_interval_minutes} minuti",
                )
                return

            if state is not None:
                normalized = state.strip().lower()
                if normalized not in {"on", "off"}:
                    await _safe_send(interaction, "⚠️ Usa 'on' o 'off' come stato.")
                    return
                config.enabled = normalized == "on"

            if minutes is not None:
                if minutes <= 0:
                    await _safe_send(interaction, "⚠️ I minuti devono essere > 0.")
                    return
                config.check_interval_minutes = minutes

            config.updated_at = datetime.utcnow()
            session.commit()
            log.info(
                "check: config aggiornata (guild=%s channel=%s enabled=%s interval=%s)",
                guild_id,
                channel_id,
                config.enabled,
                config.check_interval_minutes,
            )

            await _safe_send(
                interaction,
                "✅ Configurazione aggiornata:\n"
                f"• attivo: {'on' if config.enabled else 'off'}\n"
                f"• intervallo controllo: {config.check_interval_minutes} minuti",
            )
    except Exception as e:
        log.exception("check: errore aggiornando config (guild=%s channel=%s)", guild_id, channel_id)
        await _safe_send(interaction, f"❌ Errore aggiornando config: {e}")


@app_commands.command(name="backfill", description="Configura il recupero storico dei messaggi")
@app_commands.guild_only()
@app_commands.describe(
    state="on/off per attivare o disattivare il backfill",
    days="Numero di giorni da recuperare (default 30)",
)
async def backfill(
    interaction: discord.Interaction,
    state: str | None = None,
    days: int | None = None,
):
    await _safe_defer(interaction, "backfill")
    registry = _get_registry(interaction)
    session_factory = _get_session_factory(registry)
    ingest_service = _get_ingest_service(registry)
    if session_factory is None:
        log.warning(
            "backfill: db_session_factory mancante (guild=%s channel=%s)",
            interaction.guild_id,
            interaction.channel_id,
        )
        await _safe_send(interaction, "❌ db_session_factory non disponibile.")
        return
    if interaction.guild_id is None:
        log.warning("backfill: comando in DM non supportato (user=%s)", interaction.user.id)
        await _safe_send(interaction, "⚠️ Comando disponibile solo nei server.")
        return

    channel_id = str(interaction.channel_id)
    guild_id = str(interaction.guild_id)

    try:
        with session_factory() as session:
            config = _get_or_create_config(session, guild_id, channel_id)

            if state is None and days is None:
                await _safe_send(
                    interaction,
                    "ℹ️ Stato backfill per questo canale:\n"
                    f"• attivo: {'on' if config.backfill_enabled else 'off'}\n"
                    f"• intervallo: {config.backfill_days} giorni",
                )
                return

            if state is not None:
                normalized = state.strip().lower()
                if normalized not in {"on", "off"}:
                    await _safe_send(interaction, "⚠️ Usa 'on' o 'off' come stato.")
                    return
                config.backfill_enabled = normalized == "on"

            if days is not None:
                if days <= 0:
                    await _safe_send(interaction, "⚠️ I giorni devono essere > 0.")
                    return
                config.backfill_days = days

            config.updated_at = datetime.utcnow()
            session.commit()
            log.info(
                "backfill: config aggiornata (guild=%s channel=%s enabled=%s days=%s)",
                guild_id,
                channel_id,
                config.backfill_enabled,
                config.backfill_days,
            )

            await _safe_send(
                interaction,
                "✅ Backfill aggiornato:\n"
                f"• attivo: {'on' if config.backfill_enabled else 'off'}\n"
                f"• intervallo: {config.backfill_days} giorni",
            )

            if config.backfill_enabled:
                if ingest_service is None:
                    log.warning("backfill: ingest_service mancante (guild=%s channel=%s)", guild_id, channel_id)
                    await _safe_send(interaction, "❌ ingest_service non disponibile.")
                    return
                log.info(
                    "backfill: avvio task (guild=%s channel=%s days=%s)",
                    guild_id,
                    channel_id,
                    config.backfill_days,
                )
                asyncio.create_task(
                    _run_backfill(interaction.channel, ingest_service, config.backfill_days)
                )
    except Exception as e:
        log.exception("backfill: errore aggiornando backfill (guild=%s channel=%s)", guild_id, channel_id)
        await _safe_send(interaction, f"❌ Errore aggiornando backfill: {e}")


async def _run_backfill(
    channel: discord.abc.GuildChannel | None,
    ingest_service: IngestService,
    days: int,
) -> None:
    if channel is None or not isinstance(channel, (discord.TextChannel, discord.Thread)):
        log.warning("backfill: channel non valido o non testuale (id=%s)", getattr(channel, "id", None))
        return
    cutoff = datetime.now(tz=ROME_TZ) - timedelta(days=days)
    log.info(
        "backfill: start (guild=%s channel=%s cutoff=%s)",
        channel.guild.id,
        channel.id,
        cutoff.isoformat(),
    )
    try:
        count = 0
        async for message in channel.history(after=cutoff, oldest_first=False, limit=None):
            event = _message_to_event(message)
            if event and await ingest_service.emit(event):
                count += 1
        if count == 0:
            log.warning(
                "backfill: nessun messaggio trovato (guild=%s channel=%s cutoff=%s)",
                channel.guild.id,
                channel.id,
                cutoff.isoformat(),
            )
        log.info(
            "backfill: completato (guild=%s channel=%s count=%s cutoff=%s)",
            channel.guild.id,
            channel.id,
            count,
            cutoff.isoformat(),
        )
    except Exception:
        log.exception("backfill: errore durante la lettura/scrittura (channel=%s)", getattr(channel, "id", None))
        return


def _message_to_event(message: discord.Message) -> IngestEvent | None:
    if message.guild is None:
        return None
    author = message.author
    nickname = getattr(author, "display_name", None) or getattr(author, "name", "unknown")
    roles = []
    if isinstance(author, discord.Member):
        roles = [str(role.id) for role in author.roles if role.name != "@everyone"]

    relationships = {
        "mentions": [str(user.id) for user in message.mentions],
        "reply_to": str(message.reference.resolved.author.id)
        if message.reference and isinstance(message.reference.resolved, discord.Message)
        else None,
    }

    metadata = {
        "author_nickname": nickname,
        "roles": roles,
        "relationships": relationships,
    }
    return IngestEvent(
        event_id=str(message.id),
        source="discord",
        event_type="message.create",
        guild_id=str(message.guild.id),
        channel_id=str(message.channel.id),
        author_id=str(author.id),
        content=message.content,
        created_at=message.created_at.astimezone(ROME_TZ),
        metadata=metadata,
    )


class TextIngestCog(commands.Cog):
    def __init__(self, bot: commands.Bot, registry):
        self.bot = bot
        self.registry = registry
        self._check_task: asyncio.Task | None = None
        self._ready_logged = False

    def _start_periodic_checks(self) -> None:
        if self._check_task is None or self._check_task.done():
            log.info("periodic_check: avvio loop")
            self._check_task = asyncio.create_task(self._run_periodic_checks())
        else:
            log.info("periodic_check: loop già attivo")

    async def _check_channel_enabled(self, guild_id: str, channel_id: str) -> TextIngestChannelConfig | None:
        session_factory = _get_session_factory(self.registry)
        if session_factory is None:
            log.warning("on_message: db_session_factory mancante")
            return None
        try:
            with session_factory() as session:
                stmt = select(TextIngestChannelConfig).where(
                    (TextIngestChannelConfig.guild_id == guild_id)
                    & (TextIngestChannelConfig.channel_id == channel_id)
                )
                return session.execute(stmt).scalar_one_or_none()
        except Exception:
            log.exception("on_message: errore leggendo config (guild=%s channel=%s)", guild_id, channel_id)
            return None

    @commands.Cog.listener()
    async def on_ready(self):
        session_factory = _get_session_factory(self.registry)
        if session_factory is None:
            log.warning("on_ready: db_session_factory mancante")
            return
        try:
            with session_factory() as session:
                stmt = select(TextIngestChannelConfig).where(TextIngestChannelConfig.backfill_enabled.is_(True))
                configs = session.execute(stmt).scalars().all()
            ingest_service = _get_ingest_service(self.registry)
            for config in configs:
                channel = self.bot.get_channel(int(config.channel_id))
                log.info(
                    "on_ready: backfill attivo (guild=%s channel=%s days=%s)",
                    config.guild_id,
                    config.channel_id,
                    config.backfill_days,
                )
                if ingest_service is None:
                    log.warning(
                        "on_ready: ingest_service mancante (guild=%s channel=%s)",
                        config.guild_id,
                        config.channel_id,
                    )
                    continue
                asyncio.create_task(_run_backfill(channel, ingest_service, config.backfill_days))
            if not self._ready_logged:
                log.info("on_ready: ingest_text pronto (bot=%s)", self.bot.user)
                self._ready_logged = True
            self._start_periodic_checks()
        except Exception:
            log.exception("on_ready: errore caricando config backfill")
            return

    async def _run_periodic_checks(self) -> None:
        while True:
            session_factory = _get_session_factory(self.registry)
            if session_factory is None:
                log.warning("periodic_check: db_session_factory mancante")
                await asyncio.sleep(60)
                continue
            try:
                with session_factory() as session:
                    stmt = select(TextIngestChannelConfig).where(TextIngestChannelConfig.enabled.is_(True))
                    configs = session.execute(stmt).scalars().all()
                ingest_service = _get_ingest_service(self.registry)
                stats = ingest_service.stats() if ingest_service else {}
                log.info(
                    "periodic_check: ok (canali_attivi=%s eventi=%s last_emit=%s)",
                    len(configs),
                    stats.get("count"),
                    stats.get("last_emit_at"),
                )
                sleep_for = min((c.check_interval_minutes for c in configs), default=10) * 60
                await asyncio.sleep(max(sleep_for, 60))
            except Exception:
                log.exception("periodic_check: errore nel loop")
                await asyncio.sleep(60)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.guild is None:
            return

        config = await self._check_channel_enabled(str(message.guild.id), str(message.channel.id))
        if (
            not config
            and isinstance(message.channel, discord.Thread)
            and message.channel.parent_id is not None
        ):
            config = await self._check_channel_enabled(str(message.guild.id), str(message.channel.parent_id))
            if config:
                log.info(
                    "on_message: uso config parent (guild=%s thread=%s parent=%s)",
                    message.guild.id,
                    message.channel.id,
                    message.channel.parent_id,
                )
        if not config or not config.enabled:
            log.debug(
                "on_message: ingest disattivato (guild=%s channel=%s)",
                message.guild.id,
                message.channel.id,
            )
            return

        ingest_service = _get_ingest_service(self.registry)
        if ingest_service is None:
            log.warning("on_message: ingest_service mancante")
            return

        try:
            event = _message_to_event(message)
            if event:
                if await ingest_service.emit(event):
                    log.debug(
                        "on_message: evento emesso (guild=%s channel=%s message=%s)",
                        message.guild.id,
                        message.channel.id,
                        message.id,
                    )
                else:
                    log.warning(
                        "on_message: emit fallito (guild=%s channel=%s message=%s)",
                        message.guild.id,
                        message.channel.id,
                        message.id,
                    )
        except Exception:
            log.exception(
                "on_message: errore salvataggio (guild=%s channel=%s author=%s)",
                message.guild.id,
                message.channel.id,
                message.author.id,
            )
            return


def setup(bot: commands.Bot, registry):
    group = _get_group(bot)
    group.add_command(check)
    group.add_command(backfill)
    settings = registry.get("settings")
    if settings and not registry.get("ingest_service"):
        registry.register("ingest_service", IngestService(settings.DB_URL))
    cog = TextIngestCog(bot, registry)
    bot.add_cog(cog)
    if bot.is_ready():
        cog._start_periodic_checks()
