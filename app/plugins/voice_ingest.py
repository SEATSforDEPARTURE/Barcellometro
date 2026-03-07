from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import tempfile
import subprocess
import wave
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid4

import discord
import aiosqlite

from app.core.service_registry import ServiceRegistry
from app.services.ingest import EventEnvelope, IngestService

logger = logging.getLogger(__name__)

_OPUS_GUARD_INSTALLED = False
_OPUS_GUARD_CORRUPTED_COUNT = 0
_OPUS_GUARD_THROTTLED_LOG: Optional[Callable[[int], None]] = None
_OPUS_GUARD_ORIGINAL_DECODE: Optional[Callable[..., Any]] = None

PCM_BYTES_PER_SECOND_48K_STEREO_S16 = 48000 * 2 * 2
MIN_CHUNK_SECONDS = 1.0
MIN_PCM_BYTES = int(0.35 * PCM_BYTES_PER_SECOND_48K_STEREO_S16)
MAX_CORRUPTION_RATIO = 0.45
CRITICAL_CORRUPTION_RATIO = 0.70
MIN_WAV_SECONDS = 0.6
OPUS_WARNING_LOG_FIRST = 5
OPUS_WARNING_LOG_EVERY = 100


def _increment_opus_corruption() -> None:
    global _OPUS_GUARD_CORRUPTED_COUNT
    _OPUS_GUARD_CORRUPTED_COUNT += 1
    if _OPUS_GUARD_THROTTLED_LOG is not None:
        _OPUS_GUARD_THROTTLED_LOG(_OPUS_GUARD_CORRUPTED_COUNT)


def _is_known_corrupted_opus_error(error: Exception) -> bool:
    return "corrupted stream" in str(error).lower()


def _install_opus_decode_guard() -> None:
    global _OPUS_GUARD_INSTALLED, _OPUS_GUARD_ORIGINAL_DECODE
    if _OPUS_GUARD_INSTALLED:
        return
    try:
        from discord.opus import OpusError
        from discord.ext.voice_recv import opus as vr_opus  # type: ignore
    except Exception:
        return

    decoder = getattr(vr_opus, "OpusDecoder", None)
    if decoder is None:
        return

    target_name = None
    if hasattr(decoder, "_decode_packet"):
        target_name = "_decode_packet"
    elif hasattr(decoder, "_process_packet"):
        target_name = "_process_packet"
    if target_name is None:
        return

    original = getattr(decoder, target_name)
    if getattr(original, "_barcello_guard", False):
        _OPUS_GUARD_INSTALLED = True
        return

    def _wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return original(self, *args, **kwargs)
        except OpusError as exc:
            if not _is_known_corrupted_opus_error(exc):
                logger.exception("Unexpected OpusError in decode guard")
                raise
            _increment_opus_corruption()
            if target_name == "_decode_packet":
                packet = args[0] if args else None
                return packet, b""
            return None

    setattr(_wrapped, "_barcello_guard", True)
    setattr(decoder, target_name, _wrapped)
    _OPUS_GUARD_INSTALLED = True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(text: str) -> str:
    return " ".join(text.lower().strip().split())


def _extract_pcm_bytes(payload: Any) -> Optional[bytes]:
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload)
    pcm_bytes = getattr(payload, "pcm", None)
    if pcm_bytes is None:
        pcm_bytes = getattr(payload, "audio", None)
    if pcm_bytes is None:
        pcm_bytes = getattr(payload, "data", None)
    if isinstance(pcm_bytes, (bytes, bytearray)):
        return bytes(pcm_bytes)
    return None


@dataclass
class _VoiceJob:
    job_id: str
    user_id: int
    guild_id: int
    voice_channel_id: int
    chunk_seconds: int
    audio_path: str
    enqueued_at: float
    session_id: str
    session_started_epoch: float
    total_frames: int = 0
    corrupted_frames: int = 0
    silent_frames: int = 0
    first_frame_ts: float = 0.0
    last_frame_ts: float = 0.0
    chunk_duration_sec: float = 0.0


@dataclass
class _ChunkStats:
    total_frames: int = 0
    corrupted_frames: int = 0
    silent_frames: int = 0
    first_frame_ts: float = 0.0
    last_frame_ts: float = 0.0
    pcm_bytes: int = 0
    corruption_start_counter: int = 0


def _should_log_corruption_event(count: int) -> bool:
    return count <= OPUS_WARNING_LOG_FIRST or (count % OPUS_WARNING_LOG_EVERY) == 0


def _estimate_chunk_duration(stats: _ChunkStats, chunk_seconds: int) -> float:
    if stats.first_frame_ts > 0 and stats.last_frame_ts >= stats.first_frame_ts:
        return max(0.0, stats.last_frame_ts - stats.first_frame_ts)
    return float(chunk_seconds)


def _chunk_corruption_ratio(total_frames: int, corrupted_frames: int) -> float:
    if total_frames <= 0:
        return 0.0
    return max(0.0, min(1.0, corrupted_frames / float(total_frames)))


def _evaluate_chunk_quality(
    *,
    pcm_bytes: int,
    duration_sec: float,
    total_frames: int,
    corrupted_frames: int,
) -> tuple[bool, str]:
    if duration_sec < MIN_CHUNK_SECONDS:
        return False, f"duration<{MIN_CHUNK_SECONDS}s"
    if pcm_bytes < MIN_PCM_BYTES:
        return False, f"pcm_bytes<{MIN_PCM_BYTES}"
    if total_frames <= 0:
        return False, "no_frames"
    if _chunk_corruption_ratio(total_frames, corrupted_frames) > MAX_CORRUPTION_RATIO:
        return False, f"corruption_ratio>{MAX_CORRUPTION_RATIO:.2f}"
    return True, "ok"


class VoiceIngestController:
    def __init__(self, join_cb: Callable[[discord.VoiceChannel], Awaitable[None]], leave_cb: Callable[[], Awaitable[None]]) -> None:
        self._join_cb = join_cb
        self._leave_cb = leave_cb

    async def join(self, channel: discord.VoiceChannel) -> None:
        await self._join_cb(channel)

    async def leave(self) -> None:
        await self._leave_cb()


def setup(registry: ServiceRegistry) -> None:
    logging.getLogger("discord.ext.voice_recv").setLevel(logging.WARNING)
    logging.getLogger("discord.ext.voice_recv.gateway").setLevel(logging.WARNING)
    logging.getLogger("discord.ext.voice_recv.reader").setLevel(logging.WARNING)
    bot: discord.Client = registry.get("bot")
    database = registry.get("database")
    ingest: IngestService = registry.get("ingest")
    stt_local = registry.get("stt.local")
    config = registry.get("config")

    queue: asyncio.Queue[_VoiceJob] = asyncio.Queue()
    worker_task: Optional[asyncio.Task[None]] = None
    enforcer_task: Optional[asyncio.Task[None]] = None
    voice_client: Optional[discord.VoiceClient] = None
    active_session_id: Optional[str] = None
    active_session_started: Optional[datetime] = None
    last_text_cache: dict[int, tuple[str, float]] = {}
    user_rate: dict[int, list[float]] = {}
    breaker_failures = 0
    breaker_until: Optional[float] = None
    leave_task: Optional[asyncio.Task[None]] = None
    current_voice_channel_id: Optional[int] = None
    current_guild_id: Optional[int] = None
    legacy_warned: set[str] = set()
    join_locks: dict[int, asyncio.Lock] = {}
    connecting_guilds: set[int] = set()
    first_frame_logged: set[int] = set()
    audio_buffers_by_user: dict[int, bytearray] = {}
    audio_buffers_by_ssrc: dict[int, bytearray] = {}
    chunk_stats_by_user: dict[int, _ChunkStats] = {}
    chunk_stats_by_ssrc: dict[int, _ChunkStats] = {}
    audio_buffer_start_by_user: dict[int, float] = {}
    audio_buffer_start_by_ssrc: dict[int, float] = {}
    pending_by_user: dict[int, int] = {}
    processed_chunks = 0
    dropped_chunks = 0
    stt_enqueued_chunks = 0
    stt_empty_chunks = 0
    active_session_started_epoch: Optional[float] = None
    last_log_ts: dict[str, float] = {}
    opus_corrupted_count = 0
    opus_guard_installed = False
    opus_decode_guard_installed = False

    def _spec_available() -> bool:
        return importlib.util.find_spec("discord.ext.voice_recv") is not None

    def _safe_is_connected(client: Optional[discord.VoiceClient]) -> bool:
        if client is None:
            return False
        try:
            return bool(client.is_connected())
        except Exception:
            return False

    async def _wait_until_voice_ready(
        client: Optional[discord.VoiceClient],
        *,
        guild_id: int,
        channel_id: int,
        timeout_sec: float = 4.0,
        interval_sec: float = 0.2,
    ) -> bool:
        deadline = time.monotonic() + timeout_sec
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            connected = _safe_is_connected(client)
            current_channel = getattr(client, "channel", None) if client is not None else None
            current_channel_id = getattr(current_channel, "id", None)
            channel_ok = current_channel_id in (None, channel_id)
            logger.info(
                "Voice ingest wait-ready guild=%s channel=%s attempt=%s connected=%s current_channel=%s",
                guild_id,
                channel_id,
                attempt,
                connected,
                current_channel_id,
            )
            if connected and channel_ok:
                return True
            await asyncio.sleep(interval_sec)
        logger.error(
            "Voice ingest wait-ready timeout guild=%s channel=%s connected=%s",
            guild_id,
            channel_id,
            _safe_is_connected(client),
        )
        return False

    async def _safe_disconnect(client: Optional[discord.VoiceClient], *, guild_id: int, channel_id: int, reason: str) -> None:
        if client is None:
            return
        try:
            if _safe_is_connected(client):
                logger.info(
                    "Voice ingest disconnecting guild=%s channel=%s reason=%s",
                    guild_id,
                    channel_id,
                    reason,
                )
                await client.disconnect(force=True)
        except Exception:
            logger.exception(
                "Voice ingest cleanup disconnect failed guild=%s channel=%s reason=%s",
                guild_id,
                channel_id,
                reason,
            )

    def _log_voice_stack_versions() -> None:
        discord_version = getattr(discord, "__version__", "unknown")
        voice_recv_version = "missing"
        davey_version = "missing"

        try:
            from discord.ext import voice_recv  # type: ignore

            voice_recv_version = getattr(voice_recv, "__version__", "unknown")
        except Exception:
            logger.warning("Voice stack warning: discord.ext.voice_recv is not available")

        try:
            import davey  # type: ignore

            davey_version = getattr(davey, "__version__", "unknown")
        except Exception:
            logger.warning("Voice stack warning: davey is not installed")

        logger.info(
            "Voice stack: discord.py=%s, voice_recv=%s, davey=%s",
            discord_version,
            voice_recv_version,
            davey_version,
        )

    def _throttled_log(key: str, level: int, message: str, every_sec: int = 30) -> None:
        now = time.time()
        last = last_log_ts.get(key, 0)
        if now - last < every_sec:
            return
        last_log_ts[key] = now
        logger.log(level, message)

    def _log_opus_corruption(count: int, error: Optional[Exception] = None) -> None:
        if not _should_log_corruption_event(count):
            return
        suffix = f": {error!r}" if error is not None else ""
        logger.warning("Opus corrupted stream ignored (count=%s%s)", count, suffix)

    def _increment_opus_corrupted(error: Optional[Exception] = None) -> None:
        nonlocal opus_corrupted_count
        if error is not None and not _is_known_corrupted_opus_error(error):
            logger.exception("Unexpected OpusError while decoding voice frame")
            return
        opus_corrupted_count += 1
        _log_opus_corruption(opus_corrupted_count, error)

    def _install_opus_guard() -> None:
        nonlocal opus_guard_installed
        if opus_guard_installed:
            return
        try:
            from discord.opus import OpusError
            from discord.ext.voice_recv import opus as vr_opus  # type: ignore
        except Exception:
            logger.debug("voice_recv opus module not available; skipping Opus guard")
            return
        decoder = getattr(vr_opus, "OpusDecoder", None)
        if decoder is None or not hasattr(decoder, "_decode_packet"):
            logger.debug("voice_recv OpusDecoder missing _decode_packet; skipping Opus guard")
            return
        original = decoder._decode_packet
        if getattr(original, "_barcello_guard", False):
            opus_guard_installed = True
            return

        def wrapped(self: Any, packet: Any) -> Any:
            try:
                return original(self, packet)
            except OpusError as exc:
                if not _is_known_corrupted_opus_error(exc):
                    logger.exception("Unexpected OpusError in voice_recv decoder")
                    raise
                _increment_opus_corrupted(exc)
                return packet, b""

        setattr(wrapped, "_barcello_guard", True)
        decoder._decode_packet = wrapped
        opus_guard_installed = True
        logger.info("Installed OpusError guard for voice_recv decoder")

    def _install_discord_opus_decode_guard() -> None:
        nonlocal opus_decode_guard_installed
        global _OPUS_GUARD_ORIGINAL_DECODE
        if opus_decode_guard_installed:
            return
        try:
            import discord.opus as d_opus
            from discord.opus import OpusError
        except Exception:
            logger.debug("discord.opus not available; skipping global opus decode guard")
            return
        current = d_opus.Decoder.decode
        if getattr(current, "_barcello_guard", False):
            opus_decode_guard_installed = True
            return
        _OPUS_GUARD_ORIGINAL_DECODE = current

        def wrapped(self: Any, data: Any, *, fec: bool = False) -> bytes:
            try:
                return current(self, data, fec=fec)
            except OpusError as exc:
                if not _is_known_corrupted_opus_error(exc):
                    logger.exception("Unexpected OpusError in global Decoder.decode")
                    raise
                _increment_opus_corrupted(exc)
                frame_size = getattr(self, "_frame_size", 960)
                channels = getattr(self, "_channels", 2)
                return b"\x00" * (frame_size * channels * 2)

        setattr(wrapped, "_barcello_guard", True)
        setattr(wrapped, "_barcello_guard_original", current)
        d_opus.Decoder.decode = wrapped
        opus_decode_guard_installed = True
        logger.info("Installed GLOBAL OpusError guard on discord.opus.Decoder.decode")

    try:
        from discord.ext.voice_recv import AudioSink as _AudioSink  # type: ignore
    except Exception:
        _AudioSink = object  # type: ignore

    class SafeSink(_AudioSink):
        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def wants_opus(self) -> bool:
            wants = getattr(self._inner, "wants_opus", None)
            return bool(wants()) if callable(wants) else False

        def write(self, user: Optional[discord.User], data: Any) -> None:
            try:
                self._inner.write(user, data)
            except Exception as exc:
                try:
                    from discord.opus import OpusError
                except Exception:
                    OpusError = None  # type: ignore[assignment]
                if OpusError is not None and isinstance(exc, OpusError):
                    if _is_known_corrupted_opus_error(exc):
                        _increment_opus_corrupted(exc)
                        return
                    logger.exception("Voice ingest sink unexpected OpusError")
                    raise
                logger.exception("Voice ingest sink write failed")

        def cleanup(self) -> None:
            cleanup = getattr(self._inner, "cleanup", None)
            if callable(cleanup):
                try:
                    cleanup()
                except Exception:
                    return

    async def _get_setting(key: str, default: str) -> str:
        if not bot.user:
            return default
        namespaced_key = f"voice_ingest.{bot.user.id}.{key}"
        stored = await database.get_setting(namespaced_key)
        if stored is not None:
            return stored
        legacy_key = f"voice_ingest.{key}"
        legacy_value = await database.get_setting(legacy_key)
        if legacy_value is not None:
            if legacy_key not in legacy_warned:
                logger.warning("Legacy setting %s detected; please migrate to %s.", legacy_key, namespaced_key)
                legacy_warned.add(legacy_key)
            return legacy_value
        return default

    async def _enabled() -> bool:
        return (await _get_setting("enabled", os.getenv("VOICE_INGEST_ENABLED", "false"))).lower() in {
            "1",
            "true",
            "yes",
            "y",
        }

    async def _privacy_mode() -> bool:
        return (await _get_setting("privacy_mode", "false")).lower() in {"1", "true", "yes", "y"}

    async def _auto_join() -> bool:
        return (await _get_setting("auto_join", "true")).lower() in {"1", "true", "yes", "y"}

    async def _target_voice_channel_id() -> Optional[int]:
        value = await _get_setting("target_voice_channel_id", "")
        return int(value) if value else None

    async def _target_text_channel_id() -> Optional[int]:
        value = await _get_setting("target_text_channel_id", "")
        return int(value) if value else None

    async def _start_session(guild_id: int, voice_channel_id: int) -> str:
        nonlocal active_session_id, active_session_started
        nonlocal current_guild_id, active_session_started_epoch, current_voice_channel_id
        nonlocal processed_chunks, dropped_chunks, stt_enqueued_chunks, stt_empty_chunks
        existing_session = await database.get_active_voice_session(str(guild_id), str(voice_channel_id))
        if existing_session is not None:
            existing_session_id = str(existing_session["voice_session_id"])
            existing_started = datetime.fromisoformat(existing_session["started_ts"])
            if existing_started.tzinfo is None:
                existing_started = existing_started.replace(tzinfo=timezone.utc)
            active_session_id = existing_session_id
            active_session_started = existing_started
            active_session_started_epoch = existing_started.timestamp()
            current_voice_channel_id = voice_channel_id
            current_guild_id = guild_id
            logger.info(
                "Active voice session already exists for channel=%s id=%s; reusing",
                voice_channel_id,
                existing_session_id,
            )
            processed_chunks = 0
            dropped_chunks = 0
            stt_enqueued_chunks = 0
            stt_empty_chunks = 0
            audio_buffers_by_user.clear()
            audio_buffers_by_ssrc.clear()
            chunk_stats_by_user.clear()
            chunk_stats_by_ssrc.clear()
            return existing_session_id
        processed_chunks = 0
        dropped_chunks = 0
        stt_enqueued_chunks = 0
        stt_empty_chunks = 0
        audio_buffers_by_user.clear()
        audio_buffers_by_ssrc.clear()
        chunk_stats_by_user.clear()
        chunk_stats_by_ssrc.clear()
        session_id = str(uuid4())
        active_session_id = session_id
        active_session_started = datetime.now(timezone.utc)
        active_session_started_epoch = time.time()
        current_voice_channel_id = voice_channel_id
        current_guild_id = guild_id
        try:
            await database.start_voice_session(
                voice_session_id=session_id,
                guild_id=str(guild_id),
                voice_channel_id=str(voice_channel_id),
                started_ts=_now_iso(),
                meta={"source": "voice_ingest"},
            )
        except aiosqlite.IntegrityError:
            existing_session = await database.get_active_voice_session(str(guild_id), str(voice_channel_id))
            if existing_session is not None:
                active_session_id = existing_session["voice_session_id"]
                existing_started = datetime.fromisoformat(existing_session["started_ts"])
                if existing_started.tzinfo is None:
                    existing_started = existing_started.replace(tzinfo=timezone.utc)
                active_session_started = existing_started
                active_session_started_epoch = active_session_started.timestamp()
                current_voice_channel_id = voice_channel_id
                current_guild_id = guild_id
                logger.warning(
                    "IntegrityError starting voice session; reusing existing active voice_session_id=%s",
                    active_session_id,
                )
                return str(active_session_id)
            raise
        await ingest.emit(
            EventEnvelope(
                event_id=str(uuid4()),
                event_type="voice.join",
                platform="discord",
                ts=_now_iso(),
                guild_id=str(guild_id),
                channel_id=str(voice_channel_id),
                thread_id=None,
                author_id=str(bot.user.id) if bot.user else None,
                content=None,
                meta={"voice_session_id": session_id},
            )
        )
        return session_id

    async def _end_session() -> None:
        nonlocal active_session_id, active_session_started, current_voice_channel_id, current_guild_id, active_session_started_epoch
        if not active_session_id:
            return
        logger.info(
            "Voice ingest session summary voice_session_id=%s chunks_processed=%s chunks_dropped=%s chunks_enqueued=%s stt_empty=%s opus_corrupted_total=%s",
            active_session_id,
            processed_chunks,
            dropped_chunks,
            stt_enqueued_chunks,
            stt_empty_chunks,
            opus_corrupted_count,
        )
        await database.end_voice_session(active_session_id, _now_iso())
        await ingest.emit(
            EventEnvelope(
                event_id=str(uuid4()),
                event_type="voice.leave",
                platform="discord",
                ts=_now_iso(),
                guild_id=str(current_guild_id) if current_guild_id is not None else None,
                channel_id=str(current_voice_channel_id) if current_voice_channel_id is not None else None,
                thread_id=None,
                author_id=str(bot.user.id) if bot.user else None,
                content=None,
                meta={"voice_session_id": active_session_id},
            )
        )
        active_session_id = None
        active_session_started = None
        current_voice_channel_id = None
        current_guild_id = None
        active_session_started_epoch = None

    async def _join_voice_channel(guild: discord.Guild, channel: discord.VoiceChannel) -> None:
        nonlocal voice_client
        lock = join_locks.setdefault(guild.id, asyncio.Lock())
        async with lock:
            if guild.id in connecting_guilds:
                logger.info("Voice ingest connect already in progress for guild=%s channel=%s", guild.id, channel.id)
                return
            existing = guild.voice_client
            if existing and not _safe_is_connected(existing):
                logger.warning(
                    "Voice ingest found stale voice client before join guild=%s channel=%s; cleaning up",
                    guild.id,
                    channel.id,
                )
                await _safe_disconnect(existing, guild_id=guild.id, channel_id=channel.id, reason="stale_before_join")
                voice_client = None
            elif existing and _safe_is_connected(existing):
                if existing.channel and existing.channel.id == channel.id:
                    logger.info("Voice ingest already connected guild=%s channel=%s", guild.id, channel.id)
                    return
                logger.info("Voice ingest moving guild=%s to channel=%s", guild.id, channel.id)
                await _end_session()
                await existing.move_to(channel)
                voice_client = existing
                ready = await _wait_until_voice_ready(voice_client, guild_id=guild.id, channel_id=channel.id)
                if not ready:
                    await _safe_disconnect(voice_client, guild_id=guild.id, channel_id=channel.id, reason="move_wait_timeout")
                    voice_client = None
                    raise discord.ClientException("Voice client not ready after move")
                await _start_session(guild.id, channel.id)
                logger.info("Voice ingest moved guild=%s channel=%s", guild.id, channel.id)
                return
            if not _spec_available():
                logger.warning("voice_recv not available; voice ingest disabled for guild=%s channel=%s", guild.id, channel.id)
                return
            from discord.ext import voice_recv  # type: ignore

            _install_opus_guard()
            _install_discord_opus_decode_guard()
            connecting_guilds.add(guild.id)
            try:
                logger.info("Voice ingest connect start guild=%s channel=%s", guild.id, channel.id)
                voice_client = await channel.connect(cls=voice_recv.VoiceRecvClient)
                logger.info(
                    "Voice ingest connect returned guild=%s channel=%s client=%s connected=%s",
                    guild.id,
                    channel.id,
                    type(voice_client).__name__ if voice_client is not None else None,
                    _safe_is_connected(voice_client),
                )
                ready = await _wait_until_voice_ready(voice_client, guild_id=guild.id, channel_id=channel.id)
                if not ready:
                    await _safe_disconnect(voice_client, guild_id=guild.id, channel_id=channel.id, reason="connect_wait_timeout")
                    voice_client = None
                    raise discord.ClientException("Voice client not ready after connect")

                logger.info("Voice ingest starting session guild=%s channel=%s", guild.id, channel.id)
                await _start_session(guild.id, channel.id)
                base_sink = voice_recv.BasicSink(_on_voice_data)
                logger.info("Voice ingest listen start guild=%s channel=%s", guild.id, channel.id)
                try:
                    voice_client.listen(SafeSink(base_sink))
                except discord.ClientException as exc:
                    logger.error(
                        "Voice ingest listen failed guild=%s channel=%s error=%s connected=%s",
                        guild.id,
                        channel.id,
                        type(exc).__name__,
                        _safe_is_connected(voice_client),
                    )
                    await _safe_disconnect(voice_client, guild_id=guild.id, channel_id=channel.id, reason="listen_client_exception")
                    voice_client = None
                    await _end_session()
                    raise
                except Exception:
                    logger.exception(
                        "Voice ingest listen unexpected failure guild=%s channel=%s connected=%s",
                        guild.id,
                        channel.id,
                        _safe_is_connected(voice_client),
                    )
                    await _safe_disconnect(voice_client, guild_id=guild.id, channel_id=channel.id, reason="listen_unexpected_exception")
                    voice_client = None
                    await _end_session()
                    raise
                logger.info("Voice ingest listen attached guild=%s channel=%s", guild.id, channel.id)
                logger.info("Voice ingest connect done guild=%s channel=%s", guild.id, channel.id)
            except Exception as exc:
                logger.exception(
                    "Voice ingest connect failure guild=%s channel=%s error=%s connected=%s",
                    guild.id,
                    channel.id,
                    type(exc).__name__,
                    _safe_is_connected(voice_client),
                )
                await _safe_disconnect(voice_client, guild_id=guild.id, channel_id=channel.id, reason="join_exception")
                voice_client = None
                if active_session_id is not None:
                    await _end_session()
                raise
            finally:
                connecting_guilds.discard(guild.id)

    async def _leave_voice_channel() -> None:
        nonlocal voice_client
        if voice_client and voice_client.is_connected():
            await voice_client.disconnect(force=True)
        voice_client = None
        await _end_session()

    async def _schedule_leave_if_empty(channel: discord.VoiceChannel) -> None:
        nonlocal leave_task
        if leave_task and not leave_task.done():
            return

        async def _delayed_leave() -> None:
            await asyncio.sleep(30)
            non_bot_members = [m for m in channel.members if not m.bot]
            if non_bot_members:
                return
            await _leave_voice_channel()

        leave_task = asyncio.create_task(_delayed_leave())
        def _log_leave_result(task_future: Any) -> None:
            try:
                task_future.result()
            except Exception:
                logger.exception("Voice ingest delayed leave failed")
        leave_task.add_done_callback(_log_leave_result)

    def _on_voice_data(user: Optional[discord.User], data: Any) -> None:
        nonlocal processed_chunks, dropped_chunks, stt_enqueued_chunks
        try:
            if active_session_id is None or active_session_started is None:
                return
            if current_voice_channel_id is None:
                return
            pcm_bytes = _extract_pcm_bytes(data)
            if pcm_bytes is None:
                _throttled_log(
                    "voice_ingest.bad_payload",
                    logging.WARNING,
                    f"Voice ingest received unsupported audio payload: {type(data)}",
                )
                return
            now = time.time()
            ssrc = getattr(data, "ssrc", None)
            if user is None:
                if ssrc is not None:
                    ssrc_id = int(ssrc)
                    buffer = audio_buffers_by_ssrc.setdefault(ssrc_id, bytearray())
                    stats = chunk_stats_by_ssrc.setdefault(ssrc_id, _ChunkStats(corruption_start_counter=opus_corrupted_count))
                    buffer.extend(pcm_bytes)
                    stats.total_frames += 1
                    stats.pcm_bytes += len(pcm_bytes)
                    if _is_silent(pcm_bytes):
                        stats.silent_frames += 1
                    stats.last_frame_ts = now
                    if stats.first_frame_ts == 0:
                        stats.first_frame_ts = now
                    audio_buffer_start_by_ssrc.setdefault(ssrc_id, now)
                else:
                    _throttled_log(
                        "voice_ingest.unknown_user",
                        logging.INFO,
                        "Voice ingest received audio with unknown user/ssrc; dropping.",
                    )
                return
            ssrc_id = int(ssrc) if ssrc is not None else None
            user_stats = chunk_stats_by_user.setdefault(user.id, _ChunkStats(corruption_start_counter=opus_corrupted_count))
            if ssrc_id is not None and ssrc_id in audio_buffers_by_ssrc:
                ssrc_buffer = audio_buffers_by_ssrc.pop(ssrc_id, bytearray())
                if ssrc_buffer:
                    audio_buffers_by_user.setdefault(user.id, bytearray()).extend(ssrc_buffer)
                ssrc_stats = chunk_stats_by_ssrc.pop(ssrc_id, None)
                if ssrc_stats is not None:
                    user_stats.total_frames += ssrc_stats.total_frames
                    user_stats.silent_frames += ssrc_stats.silent_frames
                    user_stats.pcm_bytes += ssrc_stats.pcm_bytes
                    if ssrc_stats.first_frame_ts and (user_stats.first_frame_ts == 0 or ssrc_stats.first_frame_ts < user_stats.first_frame_ts):
                        user_stats.first_frame_ts = ssrc_stats.first_frame_ts
                    if ssrc_stats.last_frame_ts > user_stats.last_frame_ts:
                        user_stats.last_frame_ts = ssrc_stats.last_frame_ts
                audio_buffer_start_by_ssrc.pop(ssrc_id, None)
            buffer = audio_buffers_by_user.setdefault(user.id, bytearray())
            if user.id not in first_frame_logged:
                first_frame_logged.add(user.id)
                logger.info("Voice ingest first frame for user %s", user.id)
            buffer.extend(pcm_bytes)
            user_stats.total_frames += 1
            user_stats.pcm_bytes += len(pcm_bytes)
            if _is_silent(pcm_bytes):
                user_stats.silent_frames += 1
            user_stats.last_frame_ts = now
            if user_stats.first_frame_ts == 0:
                user_stats.first_frame_ts = now
            start_ts = audio_buffer_start_by_user.setdefault(user.id, now)
            chunk_seconds = int(os.getenv("VOICE_INGEST_DEFAULT_CHUNK_SECONDS", "10"))
            if now - start_ts < chunk_seconds:
                return
            audio_buffer_start_by_user[user.id] = now
            chunk_data = bytes(buffer)
            buffer.clear()
            chunk_stats = chunk_stats_by_user.pop(user.id, user_stats)
            chunk_stats.corrupted_frames = max(0, opus_corrupted_count - chunk_stats.corruption_start_counter)
            chunk_duration_sec = _estimate_chunk_duration(chunk_stats, chunk_seconds)
            corruption_ratio = _chunk_corruption_ratio(chunk_stats.total_frames, chunk_stats.corrupted_frames)
            enqueue_allowed, drop_reason = _evaluate_chunk_quality(
                pcm_bytes=len(chunk_data),
                duration_sec=chunk_duration_sec,
                total_frames=chunk_stats.total_frames,
                corrupted_frames=chunk_stats.corrupted_frames,
            )
            if _is_silent(chunk_data):
                enqueue_allowed = False
                drop_reason = "silent_chunk"

            processed_chunks += 1
            if not enqueue_allowed:
                dropped_chunks += 1
                logger.info(
                    "Voice ingest chunk finalized job_id=%s user_id=%s bytes=%s duration=%.2fs frames_total=%s frames_corrupted=%s corruption_ratio=%.2f enqueue=no reason=%s",
                    "discarded",
                    user.id,
                    len(chunk_data),
                    chunk_duration_sec,
                    chunk_stats.total_frames,
                    chunk_stats.corrupted_frames,
                    corruption_ratio,
                    drop_reason,
                )
                if corruption_ratio >= CRITICAL_CORRUPTION_RATIO:
                    logger.warning(
                        "Voice ingest high corruption ratio user_id=%s frames_total=%s frames_corrupted=%s ratio=%.2f",
                        user.id,
                        chunk_stats.total_frames,
                        chunk_stats.corrupted_frames,
                        corruption_ratio,
                    )
                return
            job_id = str(uuid4())
            guild_id = current_guild_id
            if guild_id is None and voice_client and voice_client.guild:
                guild_id = voice_client.guild.id
            job = _VoiceJob(
                job_id=job_id,
                user_id=user.id,
                guild_id=guild_id or 0,
                voice_channel_id=current_voice_channel_id,
                chunk_seconds=chunk_seconds,
                audio_path=_save_chunk(chunk_data),
                enqueued_at=now,
                session_id=active_session_id,
                session_started_epoch=active_session_started_epoch or now,
                total_frames=chunk_stats.total_frames,
                corrupted_frames=chunk_stats.corrupted_frames,
                silent_frames=chunk_stats.silent_frames,
                first_frame_ts=chunk_stats.first_frame_ts,
                last_frame_ts=chunk_stats.last_frame_ts,
                chunk_duration_sec=chunk_duration_sec,
            )
            loop = bot.loop
            if loop is None or not loop.is_running():
                logger.warning("Voice ingest loop not ready; dropping audio chunk.")
                _cleanup_file(job.audio_path)
                dropped_chunks += 1
                return
            stt_enqueued_chunks += 1
            logger.info(
                "Voice ingest chunk finalized job_id=%s user_id=%s bytes=%s duration=%.2fs frames_total=%s frames_corrupted=%s corruption_ratio=%.2f enqueue=yes reason=ok",
                job_id,
                user.id,
                len(chunk_data),
                chunk_duration_sec,
                chunk_stats.total_frames,
                chunk_stats.corrupted_frames,
                corruption_ratio,
            )
            future = asyncio.run_coroutine_threadsafe(_enqueue(job), loop)

            def _log_enqueue_result(task_future: Any) -> None:
                try:
                    task_future.result()
                    logger.debug("Voice ingest enqueue completed for job_id=%s", job_id)
                except Exception:
                    logger.exception("Voice ingest enqueue failed")

            future.add_done_callback(_log_enqueue_result)
        except Exception:
            logger.exception("Voice ingest _on_voice_data crashed")

    def _save_chunk(data: bytes) -> str:
        tmp_dir = os.path.join(tempfile.gettempdir(), "voice_ingest")
        os.makedirs(tmp_dir, exist_ok=True)
        path = os.path.join(tmp_dir, f"{uuid4()}.raw")
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def _is_silent(data: bytes) -> bool:
        if not data:
            return True
        sample_count = len(data) // 2
        if sample_count == 0:
            return True
        total = 0
        for i in range(0, len(data) - 1, 2):
            sample = int.from_bytes(data[i : i + 2], byteorder="little", signed=True)
            total += sample * sample
        rms = (total / sample_count) ** 0.5
        return rms < 200

    async def _enqueue(job: _VoiceJob) -> None:
        nonlocal dropped_chunks, stt_enqueued_chunks
        max_queue = int(os.getenv("VOICE_INGEST_MAX_QUEUE", "50"))
        max_per_user = int(os.getenv("VOICE_INGEST_MAX_QUEUE_PER_USER", "5"))
        if queue.qsize() >= max_queue:
            logger.info("Voice ingest queue full; dropping chunk job_id=%s", job.job_id)
            dropped_chunks += 1
            stt_enqueued_chunks = max(0, stt_enqueued_chunks - 1)
            _cleanup_file(job.audio_path)
            return
        if pending_by_user.get(job.user_id, 0) >= max_per_user:
            dropped_chunks += 1
            stt_enqueued_chunks = max(0, stt_enqueued_chunks - 1)
            _cleanup_file(job.audio_path)
            return
        now = time.time()
        timestamps = [ts for ts in user_rate.get(job.user_id, []) if now - ts < 60]
        rate_limit = int(os.getenv("VOICE_INGEST_RATE_LIMIT_USER_PER_MIN", "6"))
        if len(timestamps) >= rate_limit:
            dropped_chunks += 1
            stt_enqueued_chunks = max(0, stt_enqueued_chunks - 1)
            _cleanup_file(job.audio_path)
            return
        timestamps.append(now)
        user_rate[job.user_id] = timestamps
        pending_by_user[job.user_id] = pending_by_user.get(job.user_id, 0) + 1
        await queue.put(job)

    async def _worker() -> None:
        nonlocal breaker_failures, breaker_until, stt_empty_chunks
        logger.info("Voice ingest worker started")
        semaphore = asyncio.Semaphore(int(os.getenv("VOICE_INGEST_MAX_CONCURRENT_STT", "1")))
        timeout_sec = int(os.getenv("VOICE_INGEST_STT_TIMEOUT_SEC", "60"))
        breaker_limit = int(os.getenv("VOICE_INGEST_CIRCUIT_BREAKER_FAILS", "5"))
        breaker_cooldown = int(os.getenv("VOICE_INGEST_CIRCUIT_BREAKER_COOLDOWN_SEC", "120"))
        min_chars = int(os.getenv("VOICE_INGEST_MIN_CHARS", "3"))
        ffmpeg_timeout = min(15, timeout_sec)
        while True:
            job = await queue.get()
            logger.debug("Voice ingest worker picked job_id=%s", job.job_id)
            wav_path: Optional[str] = None
            try:
                if breaker_until and time.time() < breaker_until:
                    continue
                if not os.path.exists(job.audio_path):
                    logger.warning("Voice ingest missing audio file %s; dropping.", job.audio_path)
                    continue
                if os.path.getsize(job.audio_path) <= 4096:
                    logger.info("Voice ingest chunk too small; dropping job_id=%s.", job.job_id)
                    continue
                normalized = await _normalize_audio(job.audio_path, ffmpeg_timeout)
                if normalized is None:
                    logger.error("Voice ingest normalization failed; dropping chunk job_id=%s.", job.job_id)
                    continue
                wav_path, duration = normalized
                if duration is not None and duration < MIN_WAV_SECONDS:
                    logger.info("Voice ingest wav too short; dropping job_id=%s duration=%.2fs", job.job_id, duration)
                    continue
                async with semaphore:
                    duration_label = f"{duration:.2f}s" if duration is not None else "unknown"
                    logger.info(
                        "Voice ingest STT starting job_id=%s duration=%s frames_total=%s frames_corrupted=%s",
                        job.job_id,
                        duration_label,
                        job.total_frames,
                        job.corrupted_frames,
                    )
                    transcript = await asyncio.wait_for(stt_local.transcribe(wav_path), timeout=timeout_sec)
                    logger.info("Voice ingest STT done job_id=%s chars=%s", job.job_id, len(transcript.text))
                text = transcript.text.strip()
                if len(text) < min_chars:
                    stt_empty_chunks += 1
                    logger.info(
                        "Voice ingest STT empty/short job_id=%s chars=%s duration=%.2fs frames_total=%s frames_corrupted=%s corruption_ratio=%.2f",
                        job.job_id,
                        len(text),
                        job.chunk_duration_sec,
                        job.total_frames,
                        job.corrupted_frames,
                        _chunk_corruption_ratio(job.total_frames, job.corrupted_frames),
                    )
                    continue
                normalized_text = _normalize_text(text)
                cached = last_text_cache.get(job.user_id)
                if cached and cached[0] == normalized_text and (time.time() - cached[1]) < 30:
                    continue
                last_text_cache[job.user_id] = (normalized_text, time.time())
                call_offset_ms = int((job.enqueued_at - job.session_started_epoch) * 1000)
                message_id = str(uuid4())
                await database.insert_message(
                    message_id=message_id,
                    guild_id=str(job.guild_id),
                    channel_id=str(job.voice_channel_id),
                    author_id=str(job.user_id),
                    ts=_now_iso(),
                    content=text,
                    reply_to_message_id=None,
                    mentions=[],
                    attachments=[],
                    embeds=[
                        {
                            "source": "voice_ingest_stt",
                            "voice_meta": {
                                "voice_session_id": job.session_id,
                                "voice_channel_id": str(job.voice_channel_id),
                                "call_offset_ms": call_offset_ms,
                                "chunk_seconds": job.chunk_seconds,
                                "stt_backend": "local",
                            },
                        }
                    ],
                )
                await ingest.emit(
                    EventEnvelope(
                        event_id=str(uuid4()),
                        event_type="voice.transcript",
                        platform="discord",
                        ts=_now_iso(),
                        guild_id=str(job.guild_id),
                        channel_id=str(job.voice_channel_id),
                        thread_id=None,
                        author_id=str(job.user_id),
                        content=text,
                        meta={
                            "voice_session_id": job.session_id,
                            "call_offset_ms": call_offset_ms,
                            "message_id": message_id,
                        },
                    )
                )
                breaker_failures = 0
            except Exception:
                logger.exception("Voice ingest failed")
                breaker_failures += 1
                if breaker_failures >= breaker_limit:
                    breaker_until = time.time() + breaker_cooldown
            finally:
                _cleanup_file(job.audio_path)
                if wav_path:
                    _cleanup_file(wav_path)
                pending_by_user[job.user_id] = max(0, pending_by_user.get(job.user_id, 1) - 1)
                if processed_chunks and processed_chunks % 20 == 0:
                    global_ratio = _chunk_corruption_ratio(processed_chunks + opus_corrupted_count, opus_corrupted_count)
                    logger.info(
                        "Voice ingest summary chunks_processed=%s chunks_dropped=%s chunks_enqueued=%s stt_empty=%s opus_corrupted_total=%s estimated_global_corruption=%.2f",
                        processed_chunks,
                        dropped_chunks,
                        stt_enqueued_chunks,
                        stt_empty_chunks,
                        opus_corrupted_count,
                        global_ratio,
                    )
                queue.task_done()

    async def _normalize_audio(path: str, timeout_sec: int) -> Optional[tuple[str, Optional[float]]]:
        try:
            tmp_dir = os.path.join(tempfile.gettempdir(), "voice_ingest")
            os.makedirs(tmp_dir, exist_ok=True)
            wav_path = os.path.join(tmp_dir, f"{uuid4()}.wav")
            result = await asyncio.to_thread(
                subprocess.run,
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "s16le",
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    "-i",
                    path,
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    wav_path,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            if result.returncode != 0:
                logger.error("ffmpeg failed: %s", result.stderr.strip())
                return None
            if not os.path.exists(wav_path) or os.path.getsize(wav_path) <= 4096:
                logger.error("ffmpeg output too small; dropping chunk.")
                return None
            logger.info("Voice ingest normalized audio with ffmpeg: %s -> %s", path, wav_path)
            duration = _wav_duration(wav_path)
            return wav_path, duration
        except subprocess.TimeoutExpired:
            logger.error("ffmpeg timed out after %ss for %s", timeout_sec, path)
            return None
        except Exception:
            logger.exception("Voice ingest ffmpeg normalization failed")
            return None

    def _wav_duration(path: str) -> Optional[float]:
        try:
            with wave.open(path, "rb") as handle:
                frames = handle.getnframes()
                rate = handle.getframerate()
            if rate <= 0:
                return None
            return frames / float(rate)
        except Exception:
            logger.debug("Voice ingest could not read wav duration for %s", path)
            return None

    def _cleanup_file(path: str) -> None:
        try:
            os.remove(path)
        except FileNotFoundError:
            return
        except Exception:
            logger.debug("Voice ingest failed to remove temp file %s", path)

    async def _enforce_privacy() -> None:
        logger.info("Voice ingest privacy enforcer started")
        while True:
            try:
                target_voice_id = await _target_voice_channel_id()
                if target_voice_id is None:
                    await asyncio.sleep(5)
                    continue
                channel = bot.get_channel(target_voice_id)
                if not isinstance(channel, discord.VoiceChannel):
                    await asyncio.sleep(5)
                    continue
                privacy = await _privacy_mode()
                if privacy:
                    if voice_client and voice_client.is_connected():
                        logger.info("Voice ingest privacy enabled; leaving channel %s", channel.id)
                        await _leave_voice_channel()
                else:
                    enabled = await _enabled()
                    auto_join = await _auto_join()
                    if enabled and auto_join:
                        non_bot_members = [m for m in channel.members if not m.bot]
                        if non_bot_members and (not voice_client or not voice_client.is_connected()):
                            logger.info("Voice ingest privacy off; auto-joining channel %s", channel.id)
                            await _join_voice_channel(channel.guild, channel)
                await asyncio.sleep(5)
            except Exception:
                logger.exception("Voice ingest privacy enforcer failed")
                await asyncio.sleep(5)

    async def _handle_voice_state(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if member.bot:
            return
        if config.guild_id > 0 and member.guild.id != config.guild_id:
            return
        if not await _enabled():
            return
        if await _privacy_mode():
            return
        before_channel = before.channel
        after_channel = after.channel
        if before_channel != after_channel:
            now_ts = _now_iso()
            if before_channel is None and after_channel is not None:
                await database.insert_voice_participant_event(
                    event_id=str(uuid4()),
                    guild_id=str(member.guild.id),
                    voice_channel_id=str(after_channel.id),
                    user_id=str(member.id),
                    username=member.display_name,
                    event_type="join",
                    ts=now_ts,
                    from_channel_id=None,
                    to_channel_id=str(after_channel.id),
                    meta={"source": "voice_state_update"},
                )
            elif before_channel is not None and after_channel is None:
                await database.insert_voice_participant_event(
                    event_id=str(uuid4()),
                    guild_id=str(member.guild.id),
                    voice_channel_id=str(before_channel.id),
                    user_id=str(member.id),
                    username=member.display_name,
                    event_type="leave",
                    ts=now_ts,
                    from_channel_id=str(before_channel.id),
                    to_channel_id=None,
                    meta={"source": "voice_state_update"},
                )
            elif before_channel is not None and after_channel is not None and before_channel.id != after_channel.id:
                await database.insert_voice_participant_event(
                    event_id=str(uuid4()),
                    guild_id=str(member.guild.id),
                    voice_channel_id=str(after_channel.id),
                    user_id=str(member.id),
                    username=member.display_name,
                    event_type="move",
                    ts=now_ts,
                    from_channel_id=str(before_channel.id),
                    to_channel_id=str(after_channel.id),
                    meta={"source": "voice_state_update"},
                )
            async def _resolve_session_id(guild_id: int, channel_id: int) -> tuple[Optional[str], bool]:
                if (
                    active_session_id
                    and current_guild_id == guild_id
                    and current_voice_channel_id == channel_id
                ):
                    return active_session_id, False
                session = await database.get_active_voice_session(str(guild_id), str(channel_id))
                if session is None:
                    return None, True
                return session["voice_session_id"], False

            async def _emit_voice_event(event_type: str, channel_id: int) -> None:
                session_id, lookup_failed = await _resolve_session_id(member.guild.id, channel_id)
                meta: dict[str, Any] = {"voice_session_id": session_id}
                if before_channel is not None:
                    meta["before_channel_id"] = str(before_channel.id)
                if after_channel is not None:
                    meta["after_channel_id"] = str(after_channel.id)
                if lookup_failed:
                    meta["session_lookup_failed"] = True
                await ingest.emit(
                    EventEnvelope(
                        event_id=str(uuid4()),
                        event_type=event_type,
                        platform="discord",
                        ts=_now_iso(),
                        guild_id=str(member.guild.id),
                        channel_id=str(channel_id),
                        thread_id=None,
                        author_id=str(member.id),
                        content=None,
                        meta=meta,
                    )
                )

            if before_channel is not None:
                await _emit_voice_event("voice.leave", before_channel.id)
            if after_channel is not None:
                await _emit_voice_event("voice.join", after_channel.id)
        target_voice_id = await _target_voice_channel_id()
        if target_voice_id is None:
            return
        voice_channel = member.guild.get_channel(target_voice_id)
        if not isinstance(voice_channel, discord.VoiceChannel):
            return
        auto_join = await _auto_join()
        min_users = int(await _get_setting("min_users_to_join", "1"))
        non_bot_members = [m for m in voice_channel.members if not m.bot]
        if auto_join and non_bot_members and len(non_bot_members) >= min_users:
            if not voice_client or not voice_client.is_connected():
                await _join_voice_channel(member.guild, voice_channel)
        if voice_client and voice_client.is_connected():
            if not non_bot_members:
                await _schedule_leave_if_empty(voice_channel)

    async def _handle_join_command(channel: discord.VoiceChannel) -> None:
        if not await _enabled():
            return
        if await _privacy_mode():
            return
        await _join_voice_channel(channel.guild, channel)

    async def _handle_leave_command() -> None:
        await _leave_voice_channel()

    async def _handle_text_message(message: discord.Message) -> None:
        if not await _enabled():
            return
        if not message.guild:
            return
        target_text_id = await _target_text_channel_id()
        target_voice_id = await _target_voice_channel_id()
        if not target_text_id or not target_voice_id:
            return
        if message.channel.id != target_text_id:
            return
        session = await database.get_active_voice_session(str(message.guild.id), str(target_voice_id))
        if session is None:
            return
        started_ts = datetime.fromisoformat(session["started_ts"])
        if started_ts.tzinfo is None:
            started_ts = started_ts.replace(tzinfo=timezone.utc)
        message_ts = message.created_at
        if message_ts.tzinfo is None:
            message_ts = message_ts.replace(tzinfo=timezone.utc)
        call_offset_ms = int((message_ts - started_ts).total_seconds() * 1000)
        embeds = message.embeds[0].to_dict() if message.embeds else {}
        embeds["voice_meta"] = {
            "voice_session_id": session["voice_session_id"],
            "voice_channel_id": str(target_voice_id),
            "call_offset_ms": call_offset_ms,
        }
        await ingest.emit(
            EventEnvelope(
                event_id=str(uuid4()),
                event_type="chat.message",
                platform="discord",
                ts=_now_iso(),
                guild_id=str(message.guild.id),
                channel_id=str(message.channel.id),
                thread_id=None,
                author_id=str(message.author.id),
                content=message.content,
                meta=embeds,
            )
        )

    controller_registered = False

    async def handle_ready() -> None:
        nonlocal worker_task
        nonlocal controller_registered
        nonlocal enforcer_task
        before = await database.fetchone(
            "SELECT COUNT(*) AS c FROM voice_sessions WHERE ended_ts IS NULL",
            (),
        )
        closed_count = await database.close_open_voice_sessions(
            ended_ts=_now_iso(),
            source=None,
        )
        after = await database.fetchone(
            "SELECT COUNT(*) AS c FROM voice_sessions WHERE ended_ts IS NULL",
            (),
        )
        logger.warning(
            "Voice sessions cleanup on startup: before=%s closed=%s after=%s",
            (before["c"] if before else None),
            closed_count,
            (after["c"] if after else None),
        )
        _log_voice_stack_versions()
        if worker_task is None:
            worker_task = asyncio.create_task(_worker())
            def _log_worker_result(task_future: Any) -> None:
                try:
                    task_future.result()
                except Exception:
                    logger.exception("Voice ingest worker task failed")
            worker_task.add_done_callback(_log_worker_result)
        if enforcer_task is None:
            enforcer_task = asyncio.create_task(_enforce_privacy())
            def _log_enforcer_result(task_future: Any) -> None:
                try:
                    task_future.result()
                except Exception:
                    logger.exception("Voice ingest privacy enforcer task failed")
            enforcer_task.add_done_callback(_log_enforcer_result)
        if not controller_registered:
            registry.register("voice_ingest", VoiceIngestController(_handle_join_command, _handle_leave_command))
            controller_registered = True

    bot.add_listener(handle_ready, "on_ready")
    bot.add_listener(_handle_voice_state, "on_voice_state_update")
    bot.add_listener(_handle_text_message, "on_message")
