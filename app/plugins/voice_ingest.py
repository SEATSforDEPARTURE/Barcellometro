from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import tempfile
import subprocess
from pathlib import Path
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid4

import discord

from app.core.service_registry import ServiceRegistry
from app.services.ingest import EventEnvelope, IngestService

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(text: str) -> str:
    return " ".join(text.lower().strip().split())


@dataclass
class _VoiceJob:
    user_id: int
    guild_id: int
    voice_channel_id: int
    chunk_seconds: int
    audio_path: str
    enqueued_at: float
    session_id: str


class VoiceIngestController:
    def __init__(self, join_cb: Callable[[discord.VoiceChannel], Awaitable[None]], leave_cb: Callable[[], Awaitable[None]]) -> None:
        self._join_cb = join_cb
        self._leave_cb = leave_cb

    async def join(self, channel: discord.VoiceChannel) -> None:
        await self._join_cb(channel)

    async def leave(self) -> None:
        await self._leave_cb()


def setup(registry: ServiceRegistry) -> None:
    bot: discord.Client = registry.get("bot")
    database = registry.get("database")
    ingest: IngestService = registry.get("ingest")
    stt_local = registry.get("stt.local")
    config = registry.get("config")

    queue: asyncio.Queue[_VoiceJob] = asyncio.Queue()
    worker_task: Optional[asyncio.Task[None]] = None
    voice_client: Optional[discord.VoiceClient] = None
    active_session_id: Optional[str] = None
    active_session_started: Optional[datetime] = None
    last_text_cache: dict[int, tuple[str, float]] = {}
    user_rate: dict[int, list[float]] = {}
    audio_buffers: dict[int, bytearray] = {}
    audio_buffer_start: dict[int, float] = {}
    breaker_failures = 0
    breaker_until: Optional[float] = None
    leave_task: Optional[asyncio.Task[None]] = None
    current_voice_channel_id: Optional[int] = None
    legacy_warned: set[str] = set()
    join_locks: dict[int, asyncio.Lock] = {}

    def _spec_available() -> bool:
        return importlib.util.find_spec("discord.ext.voice_recv") is not None

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

    async def _target_voice_channel_id() -> Optional[int]:
        value = await _get_setting("target_voice_channel_id", "")
        return int(value) if value else None

    async def _target_text_channel_id() -> Optional[int]:
        value = await _get_setting("target_text_channel_id", "")
        return int(value) if value else None

    async def _start_session(guild_id: int, voice_channel_id: int) -> None:
        nonlocal active_session_id, active_session_started
        session_id = str(uuid4())
        active_session_id = session_id
        active_session_started = datetime.now(timezone.utc)
        nonlocal current_voice_channel_id
        current_voice_channel_id = voice_channel_id
        await database.start_voice_session(
            voice_session_id=session_id,
            guild_id=str(guild_id),
            voice_channel_id=str(voice_channel_id),
            started_ts=_now_iso(),
            meta={"source": "voice_ingest"},
        )
        await ingest.emit(
            EventEnvelope(
                event_id=str(uuid4()),
                event_type="voice.join",
                platform="discord",
                ts=_now_iso(),
                guild_id=str(guild_id),
                channel_id=str(voice_channel_id),
                thread_id=None,
                author_id=None,
                content=None,
                meta={"voice_session_id": session_id},
            )
        )

    async def _end_session() -> None:
        nonlocal active_session_id, active_session_started, current_voice_channel_id
        if not active_session_id:
            return
        await database.end_voice_session(active_session_id, _now_iso())
        await ingest.emit(
            EventEnvelope(
                event_id=str(uuid4()),
                event_type="voice.leave",
                platform="discord",
                ts=_now_iso(),
                guild_id=None,
                channel_id=None,
                thread_id=None,
                author_id=None,
                content=None,
                meta={"voice_session_id": active_session_id},
            )
        )
        active_session_id = None
        active_session_started = None
        current_voice_channel_id = None

    async def _join_voice_channel(guild: discord.Guild, channel: discord.VoiceChannel) -> None:
        nonlocal voice_client
        lock = join_locks.setdefault(guild.id, asyncio.Lock())
        async with lock:
            existing = guild.voice_client
            if existing and existing.is_connected():
                if existing.channel and existing.channel.id == channel.id:
                    return
                await existing.move_to(channel)
                voice_client = existing
                await _start_session(guild.id, channel.id)
                logger.info("Voice ingest moved to channel %s", channel.id)
                return
        if not _spec_available():
            logger.warning("voice_recv not available; voice ingest disabled")
            return
        from discord.ext import voice_recv  # type: ignore

        voice_client = await channel.connect(cls=voice_recv.VoiceRecvClient)
        await _start_session(guild.id, channel.id)
        voice_client.listen(voice_recv.BasicSink(_on_voice_data))
        logger.info("Voice ingest joined channel %s", channel.id)

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

    def _on_voice_data(user: discord.User, data: Any) -> None:
        if active_session_id is None or active_session_started is None:
            return
        if current_voice_channel_id is None:
            return
        pcm_bytes: Optional[bytes] = None
        if isinstance(data, (bytes, bytearray)):
            pcm_bytes = bytes(data)
        else:
            pcm_bytes = getattr(data, "pcm", None)
            if pcm_bytes is None:
                pcm_bytes = getattr(data, "audio", None)
            if pcm_bytes is None:
                pcm_bytes = getattr(data, "data", None)
        if not isinstance(pcm_bytes, (bytes, bytearray)):
            logger.warning("Voice ingest received unsupported audio payload: %s", type(data))
            return
        now = time.time()
        buffer = audio_buffers.setdefault(user.id, bytearray())
        buffer.extend(pcm_bytes)
        start_ts = audio_buffer_start.setdefault(user.id, now)
        chunk_seconds = int(os.getenv("VOICE_INGEST_DEFAULT_CHUNK_SECONDS", "10"))
        if now - start_ts < chunk_seconds:
            return
        audio_buffer_start[user.id] = now
        chunk_data = bytes(buffer)
        buffer.clear()
        if _is_silent(chunk_data):
            return
        job = _VoiceJob(
            user_id=user.id,
            guild_id=user.guild.id if isinstance(user, discord.Member) else 0,
            voice_channel_id=current_voice_channel_id,
            chunk_seconds=chunk_seconds,
            audio_path=_save_chunk(chunk_data),
            enqueued_at=now,
            session_id=active_session_id,
        )
        loop = bot.loop
        if loop is None or not loop.is_running():
            logger.warning("Voice ingest loop not ready; dropping audio chunk.")
            return
        future = asyncio.run_coroutine_threadsafe(_enqueue(job), loop)
        logger.debug("Voice ingest enqueued job for user %s", user.id)
        def _log_enqueue_result(task_future: Any) -> None:
            try:
                task_future.result()
                logger.debug("Voice ingest enqueue completed for user %s", user.id)
            except Exception:
                logger.exception("Voice ingest enqueue failed")
        future.add_done_callback(_log_enqueue_result)

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
        max_queue = int(os.getenv("VOICE_INGEST_MAX_QUEUE", "50"))
        max_per_user = int(os.getenv("VOICE_INGEST_MAX_QUEUE_PER_USER", "5"))
        if queue.qsize() >= max_queue:
            logger.info("Voice ingest queue full; dropping chunk")
            return
        if len([item for item in queue._queue if item.user_id == job.user_id]) >= max_per_user:
            return
        now = time.time()
        timestamps = [ts for ts in user_rate.get(job.user_id, []) if now - ts < 60]
        rate_limit = int(os.getenv("VOICE_INGEST_RATE_LIMIT_USER_PER_MIN", "6"))
        if len(timestamps) >= rate_limit:
            return
        timestamps.append(now)
        user_rate[job.user_id] = timestamps
        await queue.put(job)

    async def _worker() -> None:
        nonlocal breaker_failures, breaker_until
        semaphore = asyncio.Semaphore(int(os.getenv("VOICE_INGEST_MAX_CONCURRENT_STT", "1")))
        timeout_sec = int(os.getenv("VOICE_INGEST_STT_TIMEOUT_SEC", "60"))
        breaker_limit = int(os.getenv("VOICE_INGEST_CIRCUIT_BREAKER_FAILS", "5"))
        breaker_cooldown = int(os.getenv("VOICE_INGEST_CIRCUIT_BREAKER_COOLDOWN_SEC", "120"))
        min_chars = int(os.getenv("VOICE_INGEST_MIN_CHARS", "3"))
        while True:
            job = await queue.get()
            try:
                if breaker_until and time.time() < breaker_until:
                    continue
                if not os.path.exists(job.audio_path):
                    logger.warning("Voice ingest missing audio file %s; dropping.", job.audio_path)
                    continue
                if os.path.getsize(job.audio_path) <= 4096:
                    logger.info("Voice ingest chunk too small; dropping.")
                    continue
                async with semaphore:
                    try:
                        transcript = await asyncio.wait_for(stt_local.transcribe(job.audio_path), timeout=timeout_sec)
                    except Exception:
                        logger.exception("Voice ingest STT failed; retrying with ffmpeg")
                        wav_path = _reencode_to_wav(job.audio_path)
                        if wav_path is None:
                            logger.error("Voice ingest fallback failed; dropping chunk.")
                            continue
                        transcript = await asyncio.wait_for(stt_local.transcribe(wav_path), timeout=timeout_sec)
                text = transcript.text.strip()
                if len(text) < min_chars:
                    continue
                normalized = _normalize_text(text)
                cached = last_text_cache.get(job.user_id)
                if cached and cached[0] == normalized and (time.time() - cached[1]) < 30:
                    continue
                last_text_cache[job.user_id] = (normalized, time.time())
                call_offset_ms = int((datetime.now(timezone.utc) - active_session_started).total_seconds() * 1000)
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
                queue.task_done()

    def _reencode_to_wav(path: str) -> Optional[str]:
        try:
            tmp_dir = os.path.join(tempfile.gettempdir(), "voice_ingest")
            os.makedirs(tmp_dir, exist_ok=True)
            wav_path = os.path.join(tmp_dir, f"{Path(path).stem}.wav")
            result = subprocess.run(
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
            )
            if result.returncode != 0:
                logger.error("ffmpeg failed: %s", result.stderr.strip())
                return None
            if not os.path.exists(wav_path) or os.path.getsize(wav_path) <= 4096:
                logger.error("ffmpeg output too small; dropping chunk.")
                return None
            logger.info("Voice ingest re-encoded chunk to %s", wav_path)
            return wav_path
        except Exception:
            logger.exception("Voice ingest ffmpeg fallback failed")
            return None

    async def _handle_voice_state(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if not await _enabled():
            return
        target_voice_id = await _target_voice_channel_id()
        if target_voice_id is None:
            return
        voice_channel = member.guild.get_channel(target_voice_id)
        if not isinstance(voice_channel, discord.VoiceChannel):
            return
        auto_join = (await _get_setting("auto_join", "true")).lower() in {"1", "true", "yes", "y"}
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
        await _join_voice_channel(channel.guild, channel)

    async def _handle_leave_command() -> None:
        if not await _enabled():
            return
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
        if worker_task is None:
            worker_task = asyncio.create_task(_worker())
        if not controller_registered:
            registry.register("voice_ingest", VoiceIngestController(_handle_join_command, _handle_leave_command))
            controller_registered = True

    bot.add_listener(handle_ready, "on_ready")
    bot.add_listener(_handle_voice_state, "on_voice_state_update")
    bot.add_listener(_handle_text_message, "on_message")
