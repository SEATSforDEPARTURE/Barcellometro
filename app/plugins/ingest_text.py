from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from app.db.models.core import TextIngestChannelConfig, TextIngestMessage

ROME_TZ = ZoneInfo("Europe/Rome")
log = logging.getLogger("barcellometro.plugin.ingest_text")


def get_manifest():
    return {
        "name": "ingest_text",
        "version": "1.0.0",
        "description": "Ingest testuale: salvataggio messaggi e controlli per canale",
        "services_required": ["db_session_factory"],
        "services_optional": [],
        "tables_used": ["text_ingest_channel_config", "text_ingest_message"],
    }


def _get_registry(interaction: discord.Interaction):
    return getattr(interaction.client, "registry", None)


def _get_session_factory(registry):
    return registry.get("db_session_factory") if registry else None


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
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)
    except discord.NotFound:
        log.warning("check: interaction scaduta prima del defer (id=%s)", interaction.id)
        return
    registry = _get_registry(interaction)
    session_factory = _get_session_factory(registry)
    if session_factory is None:
        log.warning(
            "check: db_session_factory mancante (guild=%s channel=%s)",
            interaction.guild_id,
            interaction.channel_id,
        )
        await interaction.followup.send("❌ db_session_factory non disponibile.", ephemeral=True)
        return
    if interaction.guild_id is None:
        log.warning("check: comando in DM non supportato (user=%s)", interaction.user.id)
        await interaction.followup.send("⚠️ Comando disponibile solo nei server.", ephemeral=True)
        return

    channel_id = str(interaction.channel_id)
    guild_id = str(interaction.guild_id)

    try:
        with session_factory() as session:
            config = _get_or_create_config(session, guild_id, channel_id)

            if state is None and minutes is None:
                await interaction.followup.send(
                    "ℹ️ Stato ingest per questo canale:\n"
                    f"• attivo: {'on' if config.enabled else 'off'}\n"
                    f"• intervallo controllo: {config.check_interval_minutes} minuti",
                    ephemeral=True,
                )
                return

            if state is not None:
                normalized = state.strip().lower()
                if normalized not in {"on", "off"}:
                    await interaction.followup.send("⚠️ Usa 'on' o 'off' come stato.", ephemeral=True)
                    return
                config.enabled = normalized == "on"

            if minutes is not None:
                if minutes <= 0:
                    await interaction.followup.send("⚠️ I minuti devono essere > 0.", ephemeral=True)
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

            await interaction.followup.send(
                "✅ Configurazione aggiornata:\n"
                f"• attivo: {'on' if config.enabled else 'off'}\n"
                f"• intervallo controllo: {config.check_interval_minutes} minuti",
                ephemeral=True,
            )
    except Exception as e:
        log.exception("check: errore aggiornando config (guild=%s channel=%s)", guild_id, channel_id)
        await interaction.followup.send(f"❌ Errore aggiornando config: {e}", ephemeral=True)


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
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)
    except discord.NotFound:
        log.warning("backfill: interaction scaduta prima del defer (id=%s)", interaction.id)
        return
    registry = _get_registry(interaction)
    session_factory = _get_session_factory(registry)
    if session_factory is None:
        log.warning(
            "backfill: db_session_factory mancante (guild=%s channel=%s)",
            interaction.guild_id,
            interaction.channel_id,
        )
        await interaction.followup.send("❌ db_session_factory non disponibile.", ephemeral=True)
        return
    if interaction.guild_id is None:
        log.warning("backfill: comando in DM non supportato (user=%s)", interaction.user.id)
        await interaction.followup.send("⚠️ Comando disponibile solo nei server.", ephemeral=True)
        return

    channel_id = str(interaction.channel_id)
    guild_id = str(interaction.guild_id)

    try:
        with session_factory() as session:
            config = _get_or_create_config(session, guild_id, channel_id)

            if state is None and days is None:
                await interaction.followup.send(
                    "ℹ️ Stato backfill per questo canale:\n"
                    f"• attivo: {'on' if config.backfill_enabled else 'off'}\n"
                    f"• intervallo: {config.backfill_days} giorni",
                    ephemeral=True,
                )
                return

            if state is not None:
                normalized = state.strip().lower()
                if normalized not in {"on", "off"}:
                    await interaction.followup.send("⚠️ Usa 'on' o 'off' come stato.", ephemeral=True)
                    return
                config.backfill_enabled = normalized == "on"

            if days is not None:
                if days <= 0:
                    await interaction.followup.send("⚠️ I giorni devono essere > 0.", ephemeral=True)
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

            await interaction.followup.send(
                "✅ Backfill aggiornato:\n"
                f"• attivo: {'on' if config.backfill_enabled else 'off'}\n"
                f"• intervallo: {config.backfill_days} giorni",
                ephemeral=True,
            )

            if config.backfill_enabled:
                log.info(
                    "backfill: avvio task (guild=%s channel=%s days=%s)",
                    guild_id,
                    channel_id,
                    config.backfill_days,
                )
                asyncio.create_task(
                    _run_backfill(interaction.channel, session_factory, config.backfill_days)
                )
    except Exception as e:
        log.exception("backfill: errore aggiornando backfill (guild=%s channel=%s)", guild_id, channel_id)
        await interaction.followup.send(f"❌ Errore aggiornando backfill: {e}", ephemeral=True)


async def _run_backfill(channel: discord.abc.GuildChannel | None, session_factory, days: int) -> None:
    if channel is None or not isinstance(channel, discord.TextChannel):
        log.warning("backfill: channel non valido o non testuale")
        return
    cutoff = datetime.now(tz=ROME_TZ) - timedelta(days=days)
    log.info(
        "backfill: start (guild=%s channel=%s cutoff=%s)",
        channel.guild.id,
        channel.id,
        cutoff.isoformat(),
    )
    try:
        with session_factory() as session:
            count = 0
            async for message in channel.history(after=cutoff, oldest_first=False, limit=None):
                if _store_message(session, message):
                    count += 1
            session.commit()
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


def _store_message(
    session,
    message: discord.Message,
    time_since_last: float | None = None,
    activity_score: float | None = None,
) -> bool:
    existing = session.execute(
        select(TextIngestMessage.id).where(TextIngestMessage.message_id == str(message.id))
    ).scalar_one_or_none()
    if existing is not None:
        return False
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

    entry = TextIngestMessage(
        guild_id=str(message.guild.id),
        channel_id=str(message.channel.id),
        message_id=str(message.id),
        author_id=str(author.id),
        author_nickname=nickname,
        content=message.content,
        created_at=message.created_at.astimezone(ROME_TZ),
        roles_json=json.dumps(roles),
        write_speed=None,
        write_frequency=None,
        time_since_last_message=time_since_last,
        activity_score=activity_score,
        relationships_json=json.dumps(relationships),
    )
    session.add(entry)
    return True


class TextIngestCog(commands.Cog):
    def __init__(self, bot: commands.Bot, registry):
        self.bot = bot
        self.registry = registry
        self._last_message_at: dict[tuple[str, str, str], datetime] = {}
        self._message_counts: defaultdict[tuple[str, str], int] = defaultdict(int)
        self._check_task: asyncio.Task | None = None

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
            for config in configs:
                channel = self.bot.get_channel(int(config.channel_id))
                log.info(
                    "on_ready: backfill attivo (guild=%s channel=%s days=%s)",
                    config.guild_id,
                    config.channel_id,
                    config.backfill_days,
                )
                asyncio.create_task(_run_backfill(channel, session_factory, config.backfill_days))
            if self._check_task is None or self._check_task.done():
                self._check_task = asyncio.create_task(self._run_periodic_checks())
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
                for config in configs:
                    channel = self.bot.get_channel(int(config.channel_id))
                    if not isinstance(channel, discord.TextChannel):
                        log.warning(
                            "periodic_check: channel non valido (guild=%s channel=%s)",
                            config.guild_id,
                            config.channel_id,
                        )
                        continue
                    await self._sync_recent_messages(channel, session_factory, config.check_interval_minutes)
                sleep_for = min((c.check_interval_minutes for c in configs), default=10) * 60
                await asyncio.sleep(max(sleep_for, 60))
            except Exception:
                log.exception("periodic_check: errore nel loop")
                await asyncio.sleep(60)

    async def _sync_recent_messages(self, channel: discord.TextChannel, session_factory, minutes: int) -> None:
        cutoff = datetime.now(tz=ROME_TZ) - timedelta(minutes=minutes)
        last_seen = None
        try:
            with session_factory() as session:
                stmt = (
                    select(TextIngestMessage.created_at)
                    .where(TextIngestMessage.channel_id == str(channel.id))
                    .order_by(TextIngestMessage.created_at.desc())
                    .limit(1)
                )
                last_seen = session.execute(stmt).scalar_one_or_none()
        except Exception:
            log.exception(
                "periodic_check: errore leggendo ultimo messaggio (guild=%s channel=%s)",
                channel.guild.id,
                channel.id,
            )
            return
        start_from = last_seen if last_seen and last_seen > cutoff else cutoff
        log.info(
            "periodic_check: sync (guild=%s channel=%s from=%s)",
            channel.guild.id,
            channel.id,
            start_from.isoformat(),
        )
        try:
            with session_factory() as session:
                count = 0
                async for message in channel.history(after=start_from, oldest_first=True, limit=None):
                    if _store_message(session, message):
                        count += 1
                if count:
                    session.commit()
                    log.info(
                        "periodic_check: salvati %s messaggi (guild=%s channel=%s)",
                        count,
                        channel.guild.id,
                        channel.id,
                    )
                else:
                    log.info(
                        "periodic_check: nessun nuovo messaggio (guild=%s channel=%s)",
                        channel.guild.id,
                        channel.id,
                    )
        except Exception:
            log.exception(
                "periodic_check: errore sync (guild=%s channel=%s)",
                channel.guild.id,
                channel.id,
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.guild is None:
            return

        config = await self._check_channel_enabled(str(message.guild.id), str(message.channel.id))
        if not config or not config.enabled:
            log.debug(
                "on_message: ingest disattivato (guild=%s channel=%s)",
                message.guild.id,
                message.channel.id,
            )
            return

        session_factory = _get_session_factory(self.registry)
        if session_factory is None:
            log.warning("on_message: db_session_factory mancante")
            return

        key = (str(message.guild.id), str(message.channel.id), str(message.author.id))
        now = message.created_at.astimezone(ROME_TZ)
        last_at = self._last_message_at.get(key)
        time_since_last = (now - last_at).total_seconds() if last_at else None
        self._last_message_at[key] = now

        author_key = (str(message.guild.id), str(message.author.id))
        self._message_counts[author_key] += 1
        activity_score = float(self._message_counts[author_key])

        try:
            with session_factory() as session:
                if _store_message(
                    session,
                    message,
                    time_since_last=time_since_last,
                    activity_score=activity_score,
                ):
                    session.commit()
                    log.info(
                "on_message: salvato (guild=%s channel=%s author=%s)",
                message.guild.id,
                message.channel.id,
                message.author.id,
                    )
                else:
                    log.debug(
                        "on_message: duplicato ignorato (guild=%s channel=%s message=%s)",
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
    bot.add_cog(TextIngestCog(bot, registry))
