from __future__ import annotations

import asyncio
from collections import deque
import importlib
import importlib.util
import logging
import os
import tempfile
import subprocess
import wave
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Awaitable, Callable, Literal, Optional
from uuid import uuid4

import discord
import aiosqlite

from app.core.service_registry import ServiceRegistry
from app.services.ingest import EventEnvelope, IngestService
from app.services.voice_receive_adapter import VoiceReceiveAdapter
from app.vendor.voice_recv import DecodeErrorContext

logger = logging.getLogger(__name__)

PCM_SAMPLE_RATE = 48000
PCM_CHANNELS = 1
PCM_SAMPLE_WIDTH_BYTES = 2
PCM_BYTES_PER_SECOND_48K_MONO_S16 = PCM_SAMPLE_RATE * PCM_CHANNELS * PCM_SAMPLE_WIDTH_BYTES
MIN_CHUNK_SECONDS = 1.0
MIN_PCM_BYTES = int(0.35 * PCM_BYTES_PER_SECOND_48K_MONO_S16)
MAX_CORRUPTION_RATIO = 0.45
VOICE_INGEST_MAX_CORRUPTION_RATIO_ENV = "VOICE_INGEST_MAX_CORRUPTION_RATIO"
CRITICAL_CORRUPTION_RATIO = 0.70
MIN_WAV_SECONDS = 0.6
OPUS_WARNING_LOG_FIRST = 3
OPUS_SUMMARY_LOG_INTERVAL_SEC = 30
DECODE_STORM_WINDOW_SEC = 6.0
DECODE_STORM_ERROR_THRESHOLD = 24
DECODE_STORM_NO_PCM_SEC = 4.0
DECODE_STORM_RECONNECT_BACKOFF_SEC = 1.2
MAX_DECODE_STORM_RECOVERIES = 1
DEFAULT_MIN_SPEECH_RATIO = 0.20
DEFAULT_MIN_AVG_RMS = 250.0
DEFAULT_FRAME_SILENCE_RMS = 220.0
DEFAULT_MIN_SPOKEN_SECONDS = 0.45
KNOWN_HALLUCINATION_TEXTS = {
    "sottotitoli creati dalla comunita amara org",
}


def _is_known_corrupted_opus_error(error: Exception) -> bool:
    message = str(error).lower()
    recoverable_tokens = ("corrupted stream", "invalid argument", "buffer too small", "decode failed")
    return any(token in message for token in recoverable_tokens)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(text: str) -> str:
    return " ".join(text.lower().strip().split())


def _safe_increment(counter_name: str, increment: Callable[[], None]) -> None:
    try:
        increment()
    except Exception:
        logger.warning("Voice ingest metric update failed for %s", counter_name, exc_info=True)


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
    non_silent_frames: int = 0
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
    non_silent_frames: int = 0
    total_rms: float = 0.0
    rms_min: float = 0.0
    rms_max: float = 0.0


VoiceConnStateValue = Literal["idle", "connecting", "connected", "disconnecting", "reconnecting", "failed", "failed_runtime_incompatible"]


@dataclass
class _VoiceConnectionState:
    guild_id: int
    state: VoiceConnStateValue = "idle"
    channel_id: Optional[int] = None
    listener_attached: bool = False
    reason: str = "startup"


def _should_log_corruption_event(count: int) -> bool:
    return count <= OPUS_WARNING_LOG_FIRST


def _should_emit_periodic_summary(now_ts: float, last_ts: float, interval_sec: int = OPUS_SUMMARY_LOG_INTERVAL_SEC) -> bool:
    return now_ts - last_ts >= interval_sec


def _safe_average(total: float, count: int) -> float:
    if count <= 0:
        return 0.0
    return total / float(count)


def _pcm_duration_seconds(
    pcm_bytes: int,
    *,
    sample_rate: int = PCM_SAMPLE_RATE,
    channels: int = PCM_CHANNELS,
    sample_width_bytes: int = PCM_SAMPLE_WIDTH_BYTES,
) -> float:
    bytes_per_second = sample_rate * channels * sample_width_bytes
    if bytes_per_second <= 0:
        return 0.0
    return max(0.0, pcm_bytes / float(bytes_per_second))


def _duration_mismatch_warning(chunk_duration: float, raw_duration: float, wav_duration: float) -> Optional[str]:
    largest = max(chunk_duration, raw_duration, wav_duration, 0.001)
    spread = max(chunk_duration, raw_duration, wav_duration) - min(chunk_duration, raw_duration, wav_duration)
    if spread / largest > 0.20 and spread > 0.40:
        return f"duration mismatch chunk={chunk_duration:.2f}s raw={raw_duration:.2f}s wav={wav_duration:.2f}s"
    return None


def _get_configured_max_corruption_ratio() -> float:
    raw = os.getenv(VOICE_INGEST_MAX_CORRUPTION_RATIO_ENV, "").strip()
    if not raw:
        return MAX_CORRUPTION_RATIO
    try:
        value = float(raw)
    except ValueError:
        return MAX_CORRUPTION_RATIO
    if value < 0.1 or value > 0.95:
        return MAX_CORRUPTION_RATIO
    return value


def _count_error_matches(error_counts: dict[str, int], needle: str) -> int:
    n = needle.lower()
    return sum(count for key, count in error_counts.items() if n in key.lower())


def _is_decode_corruption_storm(
    *,
    error_count_in_window: int,
    window_sec: float,
    threshold: int,
    processed_chunks: int,
    last_pcm_frame_ts: float,
    now_ts: float,
    no_pcm_sec: float,
) -> bool:
    if window_sec <= 0 or threshold <= 0:
        return False
    if error_count_in_window < threshold:
        return False
    if processed_chunks > 0:
        return False
    if last_pcm_frame_ts <= 0:
        return True
    return (now_ts - last_pcm_frame_ts) >= no_pcm_sec
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
    non_silent_frames: int,
    avg_rms: float,
    rms_min: float,
    rms_max: float,
    max_corruption_ratio: float = MAX_CORRUPTION_RATIO,
) -> tuple[bool, str]:
    min_speech_ratio = _get_env_float("VOICE_INGEST_MIN_SPEECH_RATIO", DEFAULT_MIN_SPEECH_RATIO, minimum=0.01, maximum=1.0)
    min_avg_rms = _get_env_float("VOICE_INGEST_MIN_AVG_RMS", DEFAULT_MIN_AVG_RMS, minimum=1.0, maximum=4000.0)
    min_spoken_seconds = _get_env_float("VOICE_INGEST_MIN_SPOKEN_SECONDS", DEFAULT_MIN_SPOKEN_SECONDS, minimum=0.05, maximum=15.0)
    if duration_sec < MIN_CHUNK_SECONDS:
        return False, f"duration<{MIN_CHUNK_SECONDS}s"
    if pcm_bytes < MIN_PCM_BYTES:
        return False, f"pcm_bytes<{MIN_PCM_BYTES}"
    if total_frames <= 0:
        return False, "no_frames"
    if _chunk_corruption_ratio(total_frames, corrupted_frames) > max_corruption_ratio:
        return False, "high_corruption"
    speech_ratio = non_silent_frames / float(total_frames)
    spoken_seconds = duration_sec * speech_ratio
    if speech_ratio < min_speech_ratio or spoken_seconds < min_spoken_seconds:
        return False, "low_speech"
    if avg_rms < min_avg_rms:
        return False, "low_rms"
    dynamic_range = max(0.0, rms_max - rms_min)
    if dynamic_range < max(80.0, min_avg_rms * 0.2) and speech_ratio < 0.45:
        return False, "likely_noise_only"
    return True, "ok"


def _get_env_float(name: str, default: float, *, minimum: Optional[float] = None, maximum: Optional[float] = None) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    if maximum is not None and value > maximum:
        return default
    return value


def _normalize_text_for_match(text: str) -> str:
    lowered = unicodedata.normalize("NFKD", text.lower())
    ascii_only = "".join(ch for ch in lowered if not unicodedata.combining(ch))
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in ascii_only)
    return " ".join(cleaned.split())


def _is_likely_hallucinated_text(text: str) -> tuple[bool, str]:
    normalized = _normalize_text_for_match(text)
    if not normalized:
        return True, "empty"
    for known in KNOWN_HALLUCINATION_TEXTS:
        similarity = SequenceMatcher(a=normalized, b=known).ratio()
        if known in normalized or normalized in known or similarity >= 0.88:
            return True, "boilerplate"
    tokens = normalized.split()
    if len(tokens) <= 3 and len(set(tokens)) <= 1:
        return True, "repetitive_short"
    if len(tokens) >= 6:
        unique_ratio = len(set(tokens)) / float(len(tokens))
        if unique_ratio < 0.35:
            return True, "repetitive"
    return False, "ok"


def _is_known_boilerplate_text(text: str) -> bool:
    normalized = _normalize_text_for_match(text)
    condensed = normalized.replace(" ", "")
    for known in KNOWN_HALLUCINATION_TEXTS:
        known_norm = _normalize_text_for_match(known)
        known_condensed = known_norm.replace(" ", "")
        if known_norm in normalized or known_condensed in condensed:
            return True
    return False


def _should_reject_repeated_text(
    *,
    cache: dict[int, dict[str, list[float]]],
    user_id: int,
    normalized_text: str,
    now_ts: float,
    window_sec: int,
    max_repeats: int,
) -> bool:
    per_user = cache.setdefault(user_id, {})
    for key in list(per_user.keys()):
        per_user[key] = [ts for ts in per_user[key] if now_ts - ts <= window_sec]
        if not per_user[key]:
            del per_user[key]
    seen = per_user.setdefault(normalized_text, [])
    seen.append(now_ts)
    return len(seen) > max_repeats


def _build_session_summary(
    *,
    chunks_processed: int,
    chunks_dropped: int,
    chunks_enqueued: int,
    chunks_sent_to_stt: int,
    chunks_saved_to_db: int,
    stt_success_count: int,
    stt_empty_count: int,
    stt_hallucinated_chunks: int,
    stt_rejected_boilerplate: int,
    chunks_dropped_high_corruption: int,
    chunks_dropped_low_speech: int,
    chunks_dropped_low_rms: int,
    chunks_dropped_no_speech_after_vad: int,
    opus_corrupted_total: int,
    avg_corruption_ratio: float,
) -> dict[str, float | int]:
    coherent_sent = min(max(0, chunks_sent_to_stt), max(0, chunks_enqueued))
    coherent_saved = min(max(0, chunks_saved_to_db), coherent_sent)
    return {
        "chunks_processed": max(0, chunks_processed),
        "chunks_dropped": max(0, chunks_dropped),
        "chunks_enqueued": max(0, chunks_enqueued),
        "chunks_sent_to_stt": coherent_sent,
        "chunks_saved_to_db": coherent_saved,
        "stt_success_count": max(0, stt_success_count),
        "stt_empty_count": max(0, stt_empty_count),
        "stt_hallucinated_chunks": max(0, stt_hallucinated_chunks),
        "stt_rejected_boilerplate": max(0, stt_rejected_boilerplate),
        "chunks_dropped_high_corruption": max(0, chunks_dropped_high_corruption),
        "chunks_dropped_low_speech": max(0, chunks_dropped_low_speech),
        "chunks_dropped_low_rms": max(0, chunks_dropped_low_rms),
        "chunks_dropped_no_speech_after_vad": max(0, chunks_dropped_no_speech_after_vad),
        "opus_corrupted_total": max(0, opus_corrupted_total),
        "avg_corruption_ratio": max(0.0, avg_corruption_ratio),
    }


def _should_drop_no_speech_after_vad(
    *,
    text_len: int,
    min_chars: int,
    duration_sec: float,
    total_frames: int,
    non_silent_frames: int,
    corruption_ratio: float,
    max_corruption_ratio: float,
) -> bool:
    if text_len >= min_chars:
        return False
    if duration_sec < MIN_WAV_SECONDS:
        return False
    if total_frames <= 0 or non_silent_frames <= 0:
        return False
    if corruption_ratio > max_corruption_ratio:
        return False
    return True


def _pcm_rms(data: bytes) -> float:
    if not data:
        return 0.0
    sample_count = len(data) // 2
    if sample_count == 0:
        return 0.0
    total = 0
    for i in range(0, len(data) - 1, 2):
        sample = int.from_bytes(data[i : i + 2], byteorder="little", signed=True)
        total += sample * sample
    return (total / sample_count) ** 0.5


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
    repeated_text_cache: dict[int, dict[str, list[float]]] = {}
    user_rate: dict[int, list[float]] = {}
    breaker_failures = 0
    breaker_until: Optional[float] = None
    leave_task: Optional[asyncio.Task[None]] = None
    current_voice_channel_id: Optional[int] = None
    current_guild_id: Optional[int] = None
    legacy_warned: set[str] = set()
    join_locks: dict[int, asyncio.Lock] = {}
    voice_conn_states: dict[int, _VoiceConnectionState] = {}
    first_frame_logged: set[int] = set()
    audio_buffers_by_user: dict[int, bytearray] = {}
    audio_buffers_by_ssrc: dict[int, bytearray] = {}
    chunk_stats_by_user: dict[int, _ChunkStats] = {}
    chunk_stats_by_ssrc: dict[int, _ChunkStats] = {}
    pcm_format_logged_chunks: set[str] = set()
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
    opus_last_summary_ts = 0.0
    opus_error_type_counts: dict[str, int] = {}
    opus_payload_size_min: Optional[int] = None
    opus_payload_size_max: Optional[int] = None
    opus_payload_size_total = 0
    opus_payload_size_count = 0
    decode_errors_by_user: dict[int, int] = {}
    decode_errors_by_ssrc: dict[int, int] = {}
    chunk_corruption_ratio_total = 0.0
    chunk_corruption_ratio_count = 0
    total_chunks_ok = 0
    total_chunks_discarded_high_corruption = 0
    total_chunks_discarded_silent = 0
    stt_success_count = 0
    stt_hallucinated_chunks = 0
    stt_rejected_boilerplate = 0
    chunks_dropped_low_speech = 0
    chunks_dropped_low_rms = 0
    chunks_dropped_no_speech_after_vad = 0
    chunks_sent_to_stt = 0
    chunks_saved_to_db = 0
    consecutive_discarded_chunks = 0
    max_consecutive_discarded_chunks = 0
    voice_receive_adapter = VoiceReceiveAdapter()
    setup_invocation_count = 0
    decode_error_window: deque[float] = deque()
    last_pcm_frame_ts = 0.0
    decode_storm_recovery_count = 0
    decode_storm_recovery_in_progress = False
    decode_storm_recovery_task: Optional[asyncio.Task[None]] = None
    voice_runtime_blocked = False
    voice_runtime_blocked_reasons: tuple[str, ...] = ()
    voice_runtime_blocked_signature: Optional[tuple[str, str, str, tuple[str, ...]]] = None
    voice_runtime_blocked_skip_logged = False
    logged_runtime_incompatibilities: set[tuple[str, str, str, tuple[str, ...]]] = set()
    configured_max_corruption_ratio = _get_configured_max_corruption_ratio()
    logger.info(
        "Voice ingest quality config %s=%s",
        VOICE_INGEST_MAX_CORRUPTION_RATIO_ENV,
        configured_max_corruption_ratio,
    )

    def _clear_voice_runtime_buffers(*, keep_counters: bool = False) -> None:
        nonlocal opus_corrupted_count, opus_last_summary_ts, opus_payload_size_min, opus_payload_size_max, opus_payload_size_total, opus_payload_size_count
        audio_buffers_by_user.clear()
        audio_buffers_by_ssrc.clear()
        chunk_stats_by_user.clear()
        chunk_stats_by_ssrc.clear()
        audio_buffer_start_by_user.clear()
        audio_buffer_start_by_ssrc.clear()
        if not keep_counters:
            opus_corrupted_count = 0
            opus_last_summary_ts = 0.0
            opus_error_type_counts.clear()
            decode_errors_by_user.clear()
            decode_errors_by_ssrc.clear()
            opus_payload_size_min = None
            opus_payload_size_max = None
            opus_payload_size_total = 0
            opus_payload_size_count = 0
        decode_error_window.clear()

    def _runtime_incompatibility_signature(report: Any) -> tuple[str, str, str, tuple[str, ...]]:
        return (
            str(report.discord_version),
            str(report.voice_recv_version),
            str(report.davey_version),
            tuple(str(reason) for reason in report.reasons),
        )

    def _mark_runtime_incompatible(*, report: Any, guild_id: Optional[int], channel_id: Optional[int], reason: str) -> None:
        nonlocal voice_runtime_blocked, voice_runtime_blocked_reasons, voice_runtime_blocked_signature, voice_runtime_blocked_skip_logged
        signature = _runtime_incompatibility_signature(report)
        voice_runtime_blocked = True
        voice_runtime_blocked_reasons = signature[3]
        voice_runtime_blocked_signature = signature
        if signature in logged_runtime_incompatibilities:
            return
        logged_runtime_incompatibilities.add(signature)
        voice_runtime_blocked_skip_logged = False
        logger.error(
            "Voice ingest runtime stack incompatible guild=%s channel=%s reason=%s discord.py=%s voice_recv=%s davey=%s details=%s",
            guild_id,
            channel_id,
            reason,
            report.discord_version,
            report.voice_recv_version,
            report.davey_version,
            report.reasons,
        )

    def _runtime_blocked_for_join(*, guild_id: Optional[int], channel_id: Optional[int], reason: str) -> bool:
        nonlocal voice_runtime_blocked_skip_logged
        if not voice_runtime_blocked:
            return False
        if not voice_runtime_blocked_skip_logged:
            voice_runtime_blocked_skip_logged = True
            logger.debug(
                "Voice ingest join skipped due to blocked runtime incompatibility guild=%s channel=%s reason=%s details=%s",
                guild_id,
                channel_id,
                reason,
                list(voice_runtime_blocked_reasons),
            )
        return True

    def _spec_available(*, guild_id: Optional[int] = None, channel_id: Optional[int] = None, reason: str = "runtime") -> bool:
        if _runtime_blocked_for_join(guild_id=guild_id, channel_id=channel_id, reason=reason):
            return False
        report = voice_receive_adapter.get_voice_stack_report()
        if report.compatible:
            return True
        _mark_runtime_incompatible(report=report, guild_id=guild_id, channel_id=channel_id, reason=reason)
        return False


    def _state_for(guild_id: int) -> _VoiceConnectionState:
        state = voice_conn_states.get(guild_id)
        if state is None:
            state = _VoiceConnectionState(guild_id=guild_id)
            voice_conn_states[guild_id] = state
        return state

    def _set_voice_state(guild_id: int, *, state: VoiceConnStateValue, reason: str, channel_id: Optional[int] = None, listener_attached: Optional[bool] = None) -> _VoiceConnectionState:
        current = _state_for(guild_id)
        current.state = state
        current.reason = reason
        if channel_id is not None:
            current.channel_id = channel_id
        if listener_attached is not None:
            current.listener_attached = listener_attached
        logger.info(
            "Voice ingest state updated guild=%s state=%s channel=%s reason=%s listener_attached=%s",
            guild_id,
            current.state,
            current.channel_id,
            reason,
            current.listener_attached,
        )
        return current

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
        report = voice_receive_adapter.get_voice_stack_report()
        level = logging.INFO if report.compatible else logging.ERROR
        logger.log(
            level,
            "Voice stack: discord.py=%s, voice_recv=%s, davey=%s compatible=%s reasons=%s policy_voice_recv=%s policy_davey_min=%s",
            report.discord_version,
            report.voice_recv_version,
            report.davey_version,
            report.compatible,
            report.reasons,
            voice_receive_adapter.VOICE_RECV_SUPPORTED_SPECIFIER,
            voice_receive_adapter._fmt_minimum(voice_receive_adapter.MIN_DAVEY_VERSION),
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
        logger.warning("Opus decode error ignored (count=%s%s)", count, suffix)

    def _emit_periodic_opus_summary_if_needed() -> None:
        nonlocal opus_last_summary_ts
        now_ts = time.time()
        if not _should_emit_periodic_summary(now_ts, opus_last_summary_ts):
            return
        opus_last_summary_ts = now_ts
        avg_payload_size = _safe_average(opus_payload_size_total, opus_payload_size_count)
        top_error_types = sorted(opus_error_type_counts.items(), key=lambda item: item[1], reverse=True)[:3]
        top_users = sorted(decode_errors_by_user.items(), key=lambda item: item[1], reverse=True)[:3]
        top_ssrc = sorted(decode_errors_by_ssrc.items(), key=lambda item: item[1], reverse=True)[:3]
        logger.info(
            "Voice ingest periodic summary session=%s guild=%s channel=%s total_decode_errors=%s corrupted_stream_count=%s invalid_argument_count=%s avg_corruption_ratio=%.3f chunks_ok=%s chunks_discarded=%s consecutive_discarded=%s max_consecutive_discarded=%s error_types=%s payload_size_avg=%.1f payload_size_min=%s payload_size_max=%s top_users=%s top_ssrc=%s",
            active_session_id,
            current_guild_id,
            current_voice_channel_id,
            opus_corrupted_count,
            _count_error_matches(opus_error_type_counts, "corrupted stream"),
            _count_error_matches(opus_error_type_counts, "invalid argument"),
            _safe_average(chunk_corruption_ratio_total, chunk_corruption_ratio_count),
            total_chunks_ok,
            dropped_chunks,
            consecutive_discarded_chunks,
            max_consecutive_discarded_chunks,
            top_error_types,
            avg_payload_size,
            opus_payload_size_min,
            opus_payload_size_max,
            top_users,
            top_ssrc,
        )

    def _increment_opus_corrupted(error: Optional[Exception] = None) -> None:
        nonlocal opus_corrupted_count
        if error is not None and not _is_known_corrupted_opus_error(error):
            logger.exception("Unexpected OpusError while decoding voice frame")
            return
        opus_corrupted_count += 1

    def _log_opus_decode_failure(
        source: str,
        *,
        error: Exception,
        payload_size: Optional[int] = None,
        user_id: Optional[int] = None,
        ssrc: Optional[int] = None,
    ) -> None:
        nonlocal opus_payload_size_min, opus_payload_size_max, opus_payload_size_total, opus_payload_size_count
        message = str(error).lower().strip() or type(error).__name__.lower()
        opus_error_type_counts[message] = opus_error_type_counts.get(message, 0) + 1
        if payload_size is not None and payload_size >= 0:
            opus_payload_size_total += payload_size
            opus_payload_size_count += 1
            if opus_payload_size_min is None or payload_size < opus_payload_size_min:
                opus_payload_size_min = payload_size
            if opus_payload_size_max is None or payload_size > opus_payload_size_max:
                opus_payload_size_max = payload_size
        if user_id is not None:
            decode_errors_by_user[user_id] = decode_errors_by_user.get(user_id, 0) + 1
        if ssrc is not None:
            decode_errors_by_ssrc[ssrc] = decode_errors_by_ssrc.get(ssrc, 0) + 1

        count = opus_corrupted_count
        if _should_log_corruption_event(count):
            logger.warning(
                "Voice ingest Opus decode failure source=%s count=%s guild=%s channel=%s session=%s user=%s ssrc=%s payload_size=%s error=%r",
                source,
                count,
                current_guild_id,
                current_voice_channel_id,
                active_session_id,
                user_id,
                ssrc,
                payload_size,
                error,
            )
        else:
            _emit_periodic_opus_summary_if_needed()

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
        nonlocal opus_corrupted_count, opus_last_summary_ts, opus_payload_size_min, opus_payload_size_max, opus_payload_size_total, opus_payload_size_count
        nonlocal chunk_corruption_ratio_total, chunk_corruption_ratio_count, total_chunks_ok, total_chunks_discarded_high_corruption, total_chunks_discarded_silent, stt_success_count
        nonlocal stt_hallucinated_chunks, stt_rejected_boilerplate, chunks_dropped_low_speech, chunks_dropped_low_rms, chunks_dropped_no_speech_after_vad, chunks_sent_to_stt, chunks_saved_to_db
        nonlocal consecutive_discarded_chunks, max_consecutive_discarded_chunks
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
            opus_corrupted_count = 0
            opus_last_summary_ts = 0.0
            opus_error_type_counts.clear()
            decode_errors_by_user.clear()
            decode_errors_by_ssrc.clear()
            opus_payload_size_min = None
            opus_payload_size_max = None
            opus_payload_size_total = 0
            opus_payload_size_count = 0
            chunk_corruption_ratio_total = 0.0
            chunk_corruption_ratio_count = 0
            total_chunks_ok = 0
            total_chunks_discarded_high_corruption = 0
            total_chunks_discarded_silent = 0
            stt_success_count = 0
            stt_hallucinated_chunks = 0
            stt_rejected_boilerplate = 0
            chunks_dropped_low_speech = 0
            chunks_dropped_low_rms = 0
            chunks_dropped_no_speech_after_vad = 0
            chunks_sent_to_stt = 0
            chunks_saved_to_db = 0
            consecutive_discarded_chunks = 0
            max_consecutive_discarded_chunks = 0
            decode_storm_recovery_count = 0
            decode_storm_recovery_in_progress = False
            last_pcm_frame_ts = 0.0
            _clear_voice_runtime_buffers(keep_counters=False)
            return existing_session_id
        processed_chunks = 0
        dropped_chunks = 0
        stt_enqueued_chunks = 0
        stt_empty_chunks = 0
        opus_corrupted_count = 0
        opus_last_summary_ts = 0.0
        opus_error_type_counts.clear()
        decode_errors_by_user.clear()
        decode_errors_by_ssrc.clear()
        opus_payload_size_min = None
        opus_payload_size_max = None
        opus_payload_size_total = 0
        opus_payload_size_count = 0
        chunk_corruption_ratio_total = 0.0
        chunk_corruption_ratio_count = 0
        total_chunks_ok = 0
        total_chunks_discarded_high_corruption = 0
        total_chunks_discarded_silent = 0
        stt_success_count = 0
        stt_hallucinated_chunks = 0
        stt_rejected_boilerplate = 0
        chunks_dropped_low_speech = 0
        chunks_dropped_low_rms = 0
        chunks_dropped_no_speech_after_vad = 0
        chunks_sent_to_stt = 0
        chunks_saved_to_db = 0
        consecutive_discarded_chunks = 0
        max_consecutive_discarded_chunks = 0
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
            "Voice ingest session summary voice_session_id=%s chunks_processed=%s chunks_dropped=%s chunks_enqueued=%s opus_corrupted_total=%s corrupted_stream_count=%s invalid_argument_count=%s total_chunks_ok=%s total_chunks_discarded_high_corruption=%s total_chunks_discarded_silent=%s stt_success_count=%s stt_empty_count=%s avg_corruption_ratio=%.3f decode_errors_by_user=%s decode_errors_by_ssrc=%s consecutive_discarded=%s max_consecutive_discarded=%s",
            active_session_id,
            processed_chunks,
            dropped_chunks,
            stt_enqueued_chunks,
            opus_corrupted_count,
            _count_error_matches(opus_error_type_counts, "corrupted stream"),
            _count_error_matches(opus_error_type_counts, "invalid argument"),
            total_chunks_ok,
            total_chunks_discarded_high_corruption,
            total_chunks_discarded_silent,
            stt_success_count,
            stt_empty_chunks,
            _safe_average(chunk_corruption_ratio_total, chunk_corruption_ratio_count),
            sorted(decode_errors_by_user.items(), key=lambda item: item[1], reverse=True)[:5],
            sorted(decode_errors_by_ssrc.items(), key=lambda item: item[1], reverse=True)[:5],
            consecutive_discarded_chunks,
            max_consecutive_discarded_chunks,
        )
        summary = _build_session_summary(
            chunks_processed=processed_chunks,
            chunks_dropped=dropped_chunks,
            chunks_enqueued=stt_enqueued_chunks,
            chunks_sent_to_stt=chunks_sent_to_stt,
            chunks_saved_to_db=chunks_saved_to_db,
            stt_success_count=stt_success_count,
            stt_empty_count=stt_empty_chunks,
            stt_hallucinated_chunks=stt_hallucinated_chunks,
            stt_rejected_boilerplate=stt_rejected_boilerplate,
            chunks_dropped_high_corruption=total_chunks_discarded_high_corruption,
            chunks_dropped_low_speech=chunks_dropped_low_speech,
            chunks_dropped_low_rms=chunks_dropped_low_rms,
            chunks_dropped_no_speech_after_vad=chunks_dropped_no_speech_after_vad,
            opus_corrupted_total=opus_corrupted_count,
            avg_corruption_ratio=_safe_average(chunk_corruption_ratio_total, chunk_corruption_ratio_count),
        )
        logger.info(
            "Voice ingest session stt metrics voice_session_id=%s chunks_processed=%s chunks_dropped=%s chunks_enqueued=%s chunks_sent_to_stt=%s chunks_saved_to_db=%s stt_success_count=%s stt_empty_count=%s stt_hallucinated_chunks=%s stt_rejected_boilerplate=%s chunks_dropped_high_corruption=%s chunks_dropped_low_speech=%s chunks_dropped_low_rms=%s chunks_dropped_no_speech_after_vad=%s opus_corrupted_total=%s avg_corruption_ratio=%.3f",
            active_session_id,
            summary["chunks_processed"],
            summary["chunks_dropped"],
            summary["chunks_enqueued"],
            summary["chunks_sent_to_stt"],
            summary["chunks_saved_to_db"],
            summary["stt_success_count"],
            summary["stt_empty_count"],
            summary["stt_hallucinated_chunks"],
            summary["stt_rejected_boilerplate"],
            summary["chunks_dropped_high_corruption"],
            summary["chunks_dropped_low_speech"],
            summary["chunks_dropped_low_rms"],
            summary["chunks_dropped_no_speech_after_vad"],
            summary["opus_corrupted_total"],
            summary["avg_corruption_ratio"],
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

    async def ensure_voice_connected(guild: discord.Guild, channel: discord.VoiceChannel, *, reason: str) -> None:
        nonlocal voice_client
        lock = join_locks.setdefault(guild.id, asyncio.Lock())
        async with lock:
            conn_state = _state_for(guild.id)
            logger.info(
                "Voice ingest connect requested guild=%s channel=%s reason=%s state=%s",
                guild.id,
                channel.id,
                reason,
                conn_state.state,
            )
            if conn_state.state in {"connecting", "reconnecting"}:
                logger.info(
                    "Voice ingest join skipped: already connecting guild=%s channel=%s reason=%s state=%s",
                    guild.id,
                    channel.id,
                    reason,
                    conn_state.state,
                )
                return
            existing = guild.voice_client
            if existing and _safe_is_connected(existing) and existing.channel and existing.channel.id == channel.id:
                voice_client = existing
                attached = voice_receive_adapter.listener_attached(existing)
                _set_voice_state(guild.id, state="connected", reason=f"existing:{reason}", channel_id=channel.id, listener_attached=attached)
                if attached:
                    logger.info(
                        "Voice ingest listen skipped: already attached guild=%s channel=%s reason=%s state=%s",
                        guild.id,
                        channel.id,
                        reason,
                        "connected",
                    )
                    logger.info(
                        "Voice ingest join skipped: already connected same channel guild=%s channel=%s reason=%s state=%s",
                        guild.id,
                        channel.id,
                        reason,
                        "connected",
                    )
                    return
                from discord.ext import voice_recv  # type: ignore

                attached_now = voice_receive_adapter.attach_listener(
                    voice_client=existing,
                    voice_recv_module=voice_recv,
                    on_pcm_frame=_on_voice_data,
                    on_decode_error=_on_decode_error,
                )
                _set_voice_state(guild.id, state="connected", reason=f"attach_existing:{reason}", channel_id=channel.id, listener_attached=attached_now)
                logger.info("Voice ingest listen attached guild=%s channel=%s reason=%s state=%s sink=%s", guild.id, channel.id, reason, "connected", voice_receive_adapter.sink_debug_info())
                logger.info("Voice ingest join skipped: already connected same channel guild=%s channel=%s reason=%s state=%s", guild.id, channel.id, reason, "connected")
                return
            if existing and not _safe_is_connected(existing):
                logger.warning(
                    "Voice ingest found stale voice client before join guild=%s channel=%s reason=%s state=%s; cleaning up",
                    guild.id,
                    channel.id,
                    reason,
                    conn_state.state,
                )
                await _safe_disconnect(existing, guild_id=guild.id, channel_id=channel.id, reason="stale_before_join")
                voice_client = None
            if not _spec_available(guild_id=guild.id, channel_id=channel.id, reason=reason):
                _set_voice_state(guild.id, state="failed_runtime_incompatible", reason=f"voice_stack_incompatible:{reason}", channel_id=channel.id, listener_attached=False)
                return
            _set_voice_state(guild.id, state="connecting", reason=reason, channel_id=channel.id, listener_attached=False)
            try:
                logger.info("Voice ingest connect start guild=%s channel=%s reason=%s state=%s", guild.id, channel.id, reason, "connecting")
                await _start_session(guild.id, channel.id)
                voice_client = await voice_receive_adapter.connect_and_listen(
                    channel=channel,
                    on_pcm_frame=_on_voice_data,
                    on_decode_error=_on_decode_error,
                )
                ready = await _wait_until_voice_ready(voice_client, guild_id=guild.id, channel_id=channel.id)
                if not ready:
                    _set_voice_state(guild.id, state="failed", reason=f"connect_wait_timeout:{reason}", channel_id=channel.id, listener_attached=False)
                    await _safe_disconnect(voice_client, guild_id=guild.id, channel_id=channel.id, reason="connect_wait_timeout")
                    voice_client = None
                    await _end_session()
                    raise discord.ClientException("Voice client not ready after connect")
                _set_voice_state(guild.id, state="connected", reason=reason, channel_id=channel.id, listener_attached=True)
                logger.info("Voice ingest connect done guild=%s channel=%s reason=%s state=%s sink=%s", guild.id, channel.id, reason, "connected", voice_receive_adapter.sink_debug_info())
            except Exception as exc:
                _set_voice_state(guild.id, state="failed", reason=f"join_exception:{reason}", channel_id=channel.id, listener_attached=False)
                logger.exception(
                    "Voice ingest connect failure guild=%s channel=%s reason=%s state=%s error=%s connected=%s",
                    guild.id,
                    channel.id,
                    reason,
                    "failed",
                    type(exc).__name__,
                    _safe_is_connected(voice_client),
                )
                await _safe_disconnect(voice_client, guild_id=guild.id, channel_id=channel.id, reason="join_exception")
                voice_client = None
                if active_session_id is not None:
                    await _end_session()
                raise

    async def _join_voice_channel(guild: discord.Guild, channel: discord.VoiceChannel) -> None:
        await ensure_voice_connected(guild, channel, reason="legacy_join")

    async def _leave_voice_channel(*, reason: str = "manual") -> None:
        nonlocal voice_client
        target_guild_id = getattr(getattr(voice_client, "guild", None), "id", current_guild_id)
        target_channel_id = getattr(getattr(voice_client, "channel", None), "id", current_voice_channel_id)
        if target_guild_id is not None:
            _set_voice_state(target_guild_id, state="disconnecting", reason=reason, channel_id=target_channel_id, listener_attached=False)
        logger.info(
            "Voice ingest disconnect requested guild=%s channel=%s reason=%s state=%s",
            target_guild_id,
            target_channel_id,
            reason,
            "disconnecting",
        )
        await voice_receive_adapter.disconnect()
        voice_client = None
        await _end_session()
        if target_guild_id is not None:
            _set_voice_state(target_guild_id, state="idle", reason=reason, channel_id=target_channel_id, listener_attached=False)
        logger.info(
            "Voice ingest disconnect completed guild=%s channel=%s reason=%s state=%s",
            target_guild_id,
            target_channel_id,
            reason,
            "idle",
        )

    def _set_nonlocal_counter(counter_name: str) -> None:
        nonlocal stt_enqueued_chunks, chunks_sent_to_stt, total_chunks_ok
        if counter_name == "stt_enqueued_chunks":
            stt_enqueued_chunks += 1
        elif counter_name == "chunks_sent_to_stt":
            chunks_sent_to_stt += 1
        elif counter_name == "total_chunks_ok":
            total_chunks_ok += 1

    async def _schedule_leave_if_empty(channel: discord.VoiceChannel) -> None:
        nonlocal leave_task
        if leave_task and not leave_task.done():
            return

        async def _delayed_leave() -> None:
            await asyncio.sleep(30)
            non_bot_members = [m for m in channel.members if not m.bot]
            if non_bot_members:
                return
            await _leave_voice_channel(reason="empty_channel")

        leave_task = asyncio.create_task(_delayed_leave())
        def _log_leave_result(task_future: Any) -> None:
            try:
                task_future.result()
            except Exception:
                logger.exception("Voice ingest delayed leave failed")
        leave_task.add_done_callback(_log_leave_result)

    def _decode_storm_detected(now_ts: float) -> bool:
        while decode_error_window and now_ts - decode_error_window[0] > DECODE_STORM_WINDOW_SEC:
            decode_error_window.popleft()
        return _is_decode_corruption_storm(
            error_count_in_window=len(decode_error_window),
            window_sec=DECODE_STORM_WINDOW_SEC,
            threshold=DECODE_STORM_ERROR_THRESHOLD,
            processed_chunks=processed_chunks,
            last_pcm_frame_ts=last_pcm_frame_ts,
            now_ts=now_ts,
            no_pcm_sec=DECODE_STORM_NO_PCM_SEC,
        )

    async def _recover_from_decode_storm(*, trigger: DecodeErrorContext) -> None:
        nonlocal decode_storm_recovery_count, decode_storm_recovery_in_progress, voice_client
        nonlocal decode_storm_recovery_task
        if voice_runtime_blocked:
            if current_guild_id is not None:
                _set_voice_state(current_guild_id, state="failed_runtime_incompatible", reason="voice_stack_incompatible:decode_storm_recovery", channel_id=current_voice_channel_id, listener_attached=False)
            logger.debug("Voice ingest decode storm recovery skipped due to blocked runtime incompatibility")
            return
        if decode_storm_recovery_in_progress:
            return
        if decode_storm_recovery_count >= MAX_DECODE_STORM_RECOVERIES:
            logger.error(
                "Voice ingest decode storm recovery exhausted session=%s guild=%s channel=%s errors_in_window=%s recoveries=%s",
                active_session_id,
                current_guild_id,
                current_voice_channel_id,
                len(decode_error_window),
                decode_storm_recovery_count,
            )
            if current_guild_id is not None:
                _set_voice_state(current_guild_id, state="failed", reason="failed_decode_storm_recovery_exhausted", channel_id=current_voice_channel_id, listener_attached=False)
            return
        decode_storm_recovery_in_progress = True
        decode_storm_recovery_count += 1
        try:
            guild_id = current_guild_id
            channel_id = current_voice_channel_id
            if guild_id is None or channel_id is None:
                return
            guild = bot.get_guild(guild_id)
            channel = guild.get_channel(channel_id) if guild is not None and hasattr(guild, "get_channel") else None
            logger.error(
                "Voice ingest decode storm detected session=%s guild=%s channel=%s errors_in_window=%s source=%s user=%s ssrc=%s payload_size=%s recovery_attempt=%s",
                active_session_id,
                guild_id,
                channel_id,
                len(decode_error_window),
                trigger.source,
                trigger.user_id,
                trigger.ssrc,
                trigger.payload_size,
                decode_storm_recovery_count,
            )
            if channel is None:
                _set_voice_state(guild_id, state="failed", reason="failed_decode_storm_channel_missing", channel_id=channel_id, listener_attached=False)
                return
            _set_voice_state(guild_id, state="reconnecting", reason="decode_storm", channel_id=channel_id, listener_attached=False)
            await _safe_disconnect(voice_client, guild_id=guild_id, channel_id=channel_id, reason="decode_storm")
            voice_client = None
            _clear_voice_runtime_buffers(keep_counters=False)
            await asyncio.sleep(DECODE_STORM_RECONNECT_BACKOFF_SEC)
            await ensure_voice_connected(guild, channel, reason="decode_storm_recovery")
        except Exception:
            if current_guild_id is not None:
                _set_voice_state(current_guild_id, state="failed", reason="failed_decode_storm_reconnect_failed", channel_id=current_voice_channel_id, listener_attached=False)
            logger.exception("Voice ingest decode storm recovery failed")
        finally:
            decode_storm_recovery_in_progress = False
            decode_storm_recovery_task = None

    def _on_decode_error(error: Exception, context: DecodeErrorContext) -> None:
        nonlocal opus_corrupted_count
        counters = voice_receive_adapter.counters
        source = context.source
        message = str(error).lower()
        if "cryptoerror" in message or "decoding packet data" in message:
            logger.error(
                "Voice ingest crypto decode error source=%s state=%s reason=%s crypto_decode_errors=%s session=%s guild=%s channel=%s user=%s ssrc=%s payload_size=%s",
                source,
                _state_for(current_guild_id).state if current_guild_id is not None else "idle",
                _state_for(current_guild_id).reason if current_guild_id is not None else "n/a",
                counters.crypto_decode_errors,
                active_session_id,
                current_guild_id,
                current_voice_channel_id,
                context.user_id,
                context.ssrc,
                context.payload_size,
            )
            return
        _increment_opus_corrupted(error)
        _log_opus_decode_failure(source, error=error, payload_size=context.payload_size, user_id=context.user_id, ssrc=context.ssrc)
        logger.warning(
            "Voice ingest opus decode error source=%s opus_corrupted_total=%s session=%s guild=%s channel=%s user=%s ssrc=%s payload_size=%s packet_type=%s decoder_instance_id=%s context_session=%s context_guild=%s context_channel=%s",
            source,
            counters.opus_corrupted_total,
            active_session_id,
            current_guild_id,
            current_voice_channel_id,
            context.user_id,
            context.ssrc,
            context.payload_size,
            context.packet_type,
            context.decoder_instance_id,
            context.session_id,
            context.guild_id,
            context.channel_id,
        )
        now_ts = time.time()
        decode_error_window.append(now_ts)
        if _decode_storm_detected(now_ts):
            if decode_storm_recovery_task is None or decode_storm_recovery_task.done():
                decode_storm_recovery_task = asyncio.create_task(_recover_from_decode_storm(trigger=context))
            else:
                logger.debug("Voice ingest decode storm recovery already scheduled task_id=%s", id(decode_storm_recovery_task))

    def _on_voice_data(user: Optional[discord.User], data: Any) -> None:
        nonlocal processed_chunks, dropped_chunks, stt_enqueued_chunks, last_pcm_frame_ts
        nonlocal chunk_corruption_ratio_total, chunk_corruption_ratio_count
        nonlocal total_chunks_ok, total_chunks_discarded_high_corruption, total_chunks_discarded_silent
        nonlocal consecutive_discarded_chunks, max_consecutive_discarded_chunks
        nonlocal chunks_dropped_low_speech, chunks_dropped_low_rms, chunks_dropped_no_speech_after_vad
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
            sink_wants_opus = voice_receive_adapter.sink_wants_opus()
            if sink_wants_opus:
                _throttled_log(
                    "voice_ingest.boundary.opus_pcm_mismatch",
                    logging.ERROR,
                    "Voice ingest boundary mismatch: sink advertises opus frames but PCM-like payload reached on_voice_data",
                    every_sec=10,
                )
            now = time.time()
            last_pcm_frame_ts = now
            ssrc = getattr(data, "ssrc", None)
            if user is None:
                if ssrc is not None:
                    ssrc_id = int(ssrc)
                    buffer = audio_buffers_by_ssrc.setdefault(ssrc_id, bytearray())
                    stats = chunk_stats_by_ssrc.setdefault(ssrc_id, _ChunkStats(corruption_start_counter=opus_corrupted_count))
                    buffer.extend(pcm_bytes)
                    stats.total_frames += 1
                    stats.pcm_bytes += len(pcm_bytes)
                    frame_rms = _pcm_rms(pcm_bytes)
                    if _is_silent(pcm_bytes):
                        stats.silent_frames += 1
                    else:
                        stats.non_silent_frames += 1
                    stats.total_rms += frame_rms
                    if stats.total_frames == 1:
                        stats.rms_min = frame_rms
                        stats.rms_max = frame_rms
                    else:
                        stats.rms_min = min(stats.rms_min, frame_rms)
                        stats.rms_max = max(stats.rms_max, frame_rms)
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
                    user_stats.non_silent_frames += ssrc_stats.non_silent_frames
                    user_stats.pcm_bytes += ssrc_stats.pcm_bytes
                    user_stats.total_rms += ssrc_stats.total_rms
                    if user_stats.rms_min == 0.0:
                        user_stats.rms_min = ssrc_stats.rms_min
                    elif ssrc_stats.rms_min > 0.0:
                        user_stats.rms_min = min(user_stats.rms_min, ssrc_stats.rms_min)
                    user_stats.rms_max = max(user_stats.rms_max, ssrc_stats.rms_max)
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
            frame_rms = _pcm_rms(pcm_bytes)
            if _is_silent(pcm_bytes):
                user_stats.silent_frames += 1
            else:
                user_stats.non_silent_frames += 1
            user_stats.total_rms += frame_rms
            if user_stats.total_frames == 1:
                user_stats.rms_min = frame_rms
                user_stats.rms_max = frame_rms
            else:
                user_stats.rms_min = min(user_stats.rms_min, frame_rms)
                user_stats.rms_max = max(user_stats.rms_max, frame_rms)
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
            avg_rms = _safe_average(chunk_stats.total_rms, chunk_stats.total_frames)
            enqueue_allowed, drop_reason = _evaluate_chunk_quality(
                pcm_bytes=len(chunk_data),
                duration_sec=chunk_duration_sec,
                total_frames=chunk_stats.total_frames,
                corrupted_frames=chunk_stats.corrupted_frames,
                non_silent_frames=chunk_stats.non_silent_frames,
                avg_rms=avg_rms,
                rms_min=chunk_stats.rms_min,
                rms_max=chunk_stats.rms_max,
                max_corruption_ratio=configured_max_corruption_ratio,
            )
            if _is_silent(chunk_data):
                enqueue_allowed = False
                drop_reason = "silent_chunk"

            processed_chunks += 1
            chunk_corruption_ratio_total += corruption_ratio
            chunk_corruption_ratio_count += 1
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
                consecutive_discarded_chunks += 1
                if consecutive_discarded_chunks > max_consecutive_discarded_chunks:
                    max_consecutive_discarded_chunks = consecutive_discarded_chunks
                if drop_reason == "silent_chunk":
                    total_chunks_discarded_silent += 1
                elif drop_reason == "high_corruption":
                    total_chunks_discarded_high_corruption += 1
                elif drop_reason in {"low_speech", "likely_noise_only"}:
                    chunks_dropped_low_speech += 1
                elif drop_reason == "low_rms":
                    chunks_dropped_low_rms += 1
                if drop_reason == "high_corruption":
                    logger.info("Voice ingest chunk drop reason=high_corruption job_status=%s user_id=%s", "discarded", user.id)
                elif drop_reason in {"low_speech", "likely_noise_only"}:
                    logger.info("Voice ingest chunk drop reason=low_speech job_status=%s user_id=%s", "discarded", user.id)
                elif drop_reason == "low_rms":
                    logger.info("Voice ingest chunk drop reason=low_rms job_status=%s user_id=%s", "discarded", user.id)
                if corruption_ratio >= CRITICAL_CORRUPTION_RATIO:
                    logger.warning(
                        "Voice ingest high corruption ratio user_id=%s frames_total=%s frames_corrupted=%s ratio=%.2f",
                        user.id,
                        chunk_stats.total_frames,
                        chunk_stats.corrupted_frames,
                        corruption_ratio,
                    )
                _emit_periodic_opus_summary_if_needed()
                return
            consecutive_discarded_chunks = 0
            _emit_periodic_opus_summary_if_needed()
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
                non_silent_frames=chunk_stats.non_silent_frames,
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
            _safe_increment("stt_enqueued_chunks", lambda: _set_nonlocal_counter("stt_enqueued_chunks"))
            _safe_increment("chunks_sent_to_stt", lambda: _set_nonlocal_counter("chunks_sent_to_stt"))
            _safe_increment("total_chunks_ok", lambda: _set_nonlocal_counter("total_chunks_ok"))
            wants_opus = voice_receive_adapter.sink_wants_opus()
            if job_id not in pcm_format_logged_chunks:
                pcm_format_logged_chunks.add(job_id)
                logger.info(
                    "Voice ingest pcm format job_id=%s bytes=%s frames_total=%s sample_rate=%s channels=%s sample_width=%s sink_wants_opus=%s sink=%s",
                    job_id,
                    len(chunk_data),
                    chunk_stats.total_frames,
                    PCM_SAMPLE_RATE,
                    PCM_CHANNELS,
                    PCM_SAMPLE_WIDTH_BYTES,
                    wants_opus,
                    voice_receive_adapter.sink_debug_info(),
                )
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
        silence_rms = _get_env_float("VOICE_INGEST_FRAME_SILENCE_RMS", DEFAULT_FRAME_SILENCE_RMS, minimum=1.0, maximum=2000.0)
        return _pcm_rms(data) < silence_rms

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

    def _set_worker_counter(counter_name: str) -> None:
        nonlocal stt_empty_chunks, stt_success_count, stt_hallucinated_chunks, stt_rejected_boilerplate, chunks_saved_to_db
        if counter_name == "stt_empty_chunks":
            stt_empty_chunks += 1
        elif counter_name == "stt_success_count":
            stt_success_count += 1
        elif counter_name == "stt_hallucinated_chunks":
            stt_hallucinated_chunks += 1
        elif counter_name == "stt_rejected_boilerplate":
            stt_rejected_boilerplate += 1
        elif counter_name == "chunks_saved_to_db":
            chunks_saved_to_db += 1

    async def _worker() -> None:
        nonlocal breaker_failures, breaker_until, stt_empty_chunks, stt_success_count, stt_hallucinated_chunks, stt_rejected_boilerplate, chunks_saved_to_db, chunks_dropped_no_speech_after_vad
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
                normalized = await _normalize_audio(job.audio_path, ffmpeg_timeout, chunk_duration_sec=job.chunk_duration_sec)
                if normalized is None:
                    logger.error("Voice ingest normalization failed; dropping chunk job_id=%s.", job.job_id)
                    continue
                wav_path, duration, raw_duration = normalized
                if duration is not None and duration < MIN_WAV_SECONDS:
                    logger.info("Voice ingest wav too short; dropping job_id=%s duration=%.2fs", job.job_id, duration)
                    continue
                async with semaphore:
                    duration_label = f"{duration:.2f}s" if duration is not None else "unknown"
                    logger.info(
                        "Voice ingest STT starting job_id=%s duration=%s raw_duration=%.2fs chunk_duration=%.2fs frames_total=%s frames_corrupted=%s",
                        job.job_id,
                        duration_label,
                        raw_duration,
                        job.chunk_duration_sec,
                        job.total_frames,
                        job.corrupted_frames,
                    )
                    transcript = await asyncio.wait_for(stt_local.transcribe(wav_path), timeout=timeout_sec)
                    logger.info("Voice ingest STT done job_id=%s chars=%s", job.job_id, len(transcript.text))
                text = transcript.text.strip()
                text_len = len(text)
                corruption_ratio = _chunk_corruption_ratio(job.total_frames, job.corrupted_frames)
                if _should_drop_no_speech_after_vad(
                    text_len=text_len,
                    min_chars=min_chars,
                    duration_sec=duration or job.chunk_duration_sec,
                    total_frames=job.total_frames,
                    non_silent_frames=job.non_silent_frames,
                    corruption_ratio=corruption_ratio,
                    max_corruption_ratio=configured_max_corruption_ratio,
                ):
                    chunks_dropped_no_speech_after_vad += 1
                    _safe_increment("stt_empty_chunks", lambda: _set_worker_counter("stt_empty_chunks"))
                    logger.info(
                        "Voice ingest STT dropped job_id=%s reason=no_speech_after_vad chars=%s duration=%.2fs frames_total=%s frames_non_silent=%s frames_corrupted=%s corruption_ratio=%.2f",
                        job.job_id,
                        text_len,
                        duration or job.chunk_duration_sec,
                        job.total_frames,
                        job.non_silent_frames,
                        job.corrupted_frames,
                        corruption_ratio,
                    )
                    continue
                if text_len < min_chars:
                    _safe_increment("stt_empty_chunks", lambda: _set_worker_counter("stt_empty_chunks"))
                    logger.info(
                        "Voice ingest STT empty/short job_id=%s chars=%s duration=%.2fs frames_total=%s frames_corrupted=%s corruption_ratio=%.2f",
                        job.job_id,
                        text_len,
                        job.chunk_duration_sec,
                        job.total_frames,
                        job.corrupted_frames,
                        corruption_ratio,
                    )
                    continue
                normalized_text = _normalize_text(text)
                text = " ".join(text.split())
                cached = last_text_cache.get(job.user_id)
                if cached and cached[0] == normalized_text and (time.time() - cached[1]) < 30:
                    continue
                if os.getenv("VOICE_INGEST_REJECT_HALLUCINATION_TEXTS", "true").lower() in {"1", "true", "yes", "y"}:
                    if _is_known_boilerplate_text(text):
                        _safe_increment("stt_hallucinated_chunks", lambda: _set_worker_counter("stt_hallucinated_chunks"))
                        _safe_increment("stt_rejected_boilerplate", lambda: _set_worker_counter("stt_rejected_boilerplate"))
                        logger.info(
                            "Voice ingest STT rejected job_id=%s user_id=%s reason=boilerplate_hallucination text=%r",
                            job.job_id,
                            job.user_id,
                            text,
                        )
                        continue
                    hallucinated, hallucination_reason = _is_likely_hallucinated_text(text)
                    if hallucinated:
                        _safe_increment("stt_hallucinated_chunks", lambda: _set_worker_counter("stt_hallucinated_chunks"))
                        if hallucination_reason == "boilerplate":
                            _safe_increment("stt_rejected_boilerplate", lambda: _set_worker_counter("stt_rejected_boilerplate"))
                        logger.info(
                            "Voice ingest STT rejected as likely hallucination job_id=%s user_id=%s reason=%s text=%r",
                            job.job_id,
                            job.user_id,
                            hallucination_reason,
                            text,
                        )
                        continue
                dedup_window_sec = int(os.getenv("VOICE_INGEST_DUPLICATE_WINDOW_SEC", "120"))
                dedup_max_repeats = int(os.getenv("VOICE_INGEST_DUPLICATE_MAX_REPEATS", "3"))
                if _should_reject_repeated_text(
                    cache=repeated_text_cache,
                    user_id=job.user_id,
                    normalized_text=normalized_text,
                    now_ts=time.time(),
                    window_sec=dedup_window_sec,
                    max_repeats=dedup_max_repeats,
                ):
                    _safe_increment("stt_hallucinated_chunks", lambda: _set_worker_counter("stt_hallucinated_chunks"))
                    logger.info(
                        "Voice ingest duplicate_transcript_rejected job_id=%s user_id=%s reason=duplicate_burst text=%r",
                        job.job_id,
                        job.user_id,
                        text,
                    )
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
                _safe_increment("stt_success_count", lambda: _set_worker_counter("stt_success_count"))
                _safe_increment("chunks_saved_to_db", lambda: _set_worker_counter("chunks_saved_to_db"))
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

    async def _normalize_audio(
        path: str, timeout_sec: int, *, chunk_duration_sec: float
    ) -> Optional[tuple[str, Optional[float], float]]:
        try:
            tmp_dir = os.path.join(tempfile.gettempdir(), "voice_ingest")
            os.makedirs(tmp_dir, exist_ok=True)
            wav_path = os.path.join(tmp_dir, f"{uuid4()}.wav")
            raw_size = os.path.getsize(path)
            raw_duration = _pcm_duration_seconds(raw_size)
            result = await asyncio.to_thread(
                subprocess.run,
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "s16le",
                    "-ar",
                    str(PCM_SAMPLE_RATE),
                    "-ac",
                    str(PCM_CHANNELS),
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
            duration = _wav_duration(wav_path)
            if duration is not None:
                mismatch = _duration_mismatch_warning(chunk_duration_sec, raw_duration, duration)
                if mismatch is not None:
                    logger.warning("Voice ingest %s", mismatch)
            logger.info(
                "Voice ingest normalized audio with ffmpeg: %s -> %s raw_duration=%.2fs chunk_duration=%.2fs wav_duration=%s",
                path,
                wav_path,
                raw_duration,
                chunk_duration_sec,
                f"{duration:.2f}s" if duration is not None else "unknown",
            )
            return wav_path, duration, raw_duration
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
                    if _safe_is_connected(voice_client):
                        logger.info("Voice ingest privacy enabled; leaving channel %s", channel.id)
                        await _leave_voice_channel(reason="privacy_enabled")
                else:
                    enabled = await _enabled()
                    auto_join = await _auto_join()
                    if enabled and auto_join:
                        non_bot_members = [m for m in channel.members if not m.bot]
                        if non_bot_members and (not _safe_is_connected(voice_client)):
                            if _runtime_blocked_for_join(guild_id=channel.guild.id, channel_id=channel.id, reason="privacy_auto_join"):
                                logger.debug("Voice ingest privacy auto-join skipped due to runtime block channel=%s", channel.id)
                            else:
                                logger.info("Voice ingest privacy off; auto-joining channel %s", channel.id)
                                await ensure_voice_connected(channel.guild, channel, reason="privacy_auto_join")
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
            if not _safe_is_connected(voice_client):
                if _runtime_blocked_for_join(guild_id=member.guild.id, channel_id=voice_channel.id, reason="voice_state_auto_join"):
                    return
                await ensure_voice_connected(member.guild, voice_channel, reason="voice_state_auto_join")
        if _safe_is_connected(voice_client):
            if not non_bot_members:
                await _schedule_leave_if_empty(voice_channel)

    async def _handle_join_command(channel: discord.VoiceChannel) -> None:
        if not await _enabled():
            return
        if await _privacy_mode():
            return
        await ensure_voice_connected(channel.guild, channel, reason="command_join")

    async def _handle_leave_command() -> None:
        await _leave_voice_channel(reason="command_leave")

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
    startup_initialized = False

    async def handle_ready() -> None:
        nonlocal worker_task
        nonlocal controller_registered
        nonlocal enforcer_task
        nonlocal startup_initialized
        nonlocal setup_invocation_count

        setup_invocation_count += 1
        worker_running = worker_task is not None and not worker_task.done()
        enforcer_running = enforcer_task is not None and not enforcer_task.done()
        logger.info(
            "Voice ingest on_ready invoked count=%s startup_initialized=%s worker_task_id=%s worker_running=%s enforcer_task_id=%s enforcer_running=%s listeners_on_ready=%s listeners_voice_state=%s listeners_message=%s",
            setup_invocation_count,
            startup_initialized,
            id(worker_task) if worker_task is not None else None,
            worker_running,
            id(enforcer_task) if enforcer_task is not None else None,
            enforcer_running,
            len(getattr(bot, "_listeners", {}).get("on_ready", [])),
            len(getattr(bot, "_listeners", {}).get("on_voice_state_update", [])),
            len(getattr(bot, "_listeners", {}).get("on_message", [])),
        )
        if startup_initialized:
            logger.info(
                "Voice ingest startup already initialized; skipping duplicate on_ready init worker_task_id=%s enforcer_task_id=%s",
                id(worker_task) if worker_task is not None else None,
                id(enforcer_task) if enforcer_task is not None else None,
            )
            return

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
        if worker_task is None or worker_task.done():
            worker_task = asyncio.create_task(_worker())

            def _log_worker_result(task_future: Any) -> None:
                try:
                    task_future.result()
                except Exception:
                    logger.exception("Voice ingest worker task failed")

            worker_task.add_done_callback(_log_worker_result)
            logger.info("Voice ingest worker task started task_id=%s", id(worker_task))
        else:
            logger.info("Voice ingest worker task already running task_id=%s", id(worker_task))
        if enforcer_task is None or enforcer_task.done():
            enforcer_task = asyncio.create_task(_enforce_privacy())

            def _log_enforcer_result(task_future: Any) -> None:
                try:
                    task_future.result()
                except Exception:
                    logger.exception("Voice ingest privacy enforcer task failed")

            enforcer_task.add_done_callback(_log_enforcer_result)
            logger.info("Voice ingest privacy enforcer task started task_id=%s", id(enforcer_task))
        else:
            logger.info("Voice ingest privacy enforcer task already running task_id=%s", id(enforcer_task))
        if not controller_registered:
            registry.register("voice_ingest", VoiceIngestController(_handle_join_command, _handle_leave_command))
            controller_registered = True
            logger.info("Voice ingest controller registered")
        else:
            logger.info("Voice ingest controller already registered")
        startup_initialized = True

    bot.add_listener(handle_ready, "on_ready")
    bot.add_listener(_handle_voice_state, "on_voice_state_update")
    bot.add_listener(_handle_text_message, "on_message")
