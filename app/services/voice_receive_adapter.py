from __future__ import annotations

import importlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import discord

logger = logging.getLogger(__name__)


@dataclass
class DecodeErrorCounters:
    opus_corrupted_total: int = 0
    corrupted_stream_count: int = 0
    invalid_argument_count: int = 0


class VoiceReceiveAdapter:
    """Stable wrapper around discord-ext-voice-recv receive internals."""

    def __init__(self) -> None:
        self._counters = DecodeErrorCounters()
        self._last_error_log_ts = 0.0
        self._log_interval_sec = 15.0
        self._router_guard_installed = False
        self._voice_recv: Any = None

    @property
    def counters(self) -> DecodeErrorCounters:
        return self._counters

    def available(self) -> bool:
        return importlib.util.find_spec("discord.ext.voice_recv") is not None

    def _is_decode_error(self, exc: BaseException) -> bool:
        message = str(exc).lower()
        return any(token in message for token in ("corrupted stream", "invalid argument", "buffer too small", "decode failed"))

    def _register_decode_error(self, exc: BaseException) -> None:
        message = str(exc).lower()
        self._counters.opus_corrupted_total += 1
        if "corrupted stream" in message:
            self._counters.corrupted_stream_count += 1
        if "invalid argument" in message:
            self._counters.invalid_argument_count += 1

    def _log_decode_error_summary(self, *, source: str) -> None:
        now = time.monotonic()
        if now - self._last_error_log_ts < self._log_interval_sec:
            return
        self._last_error_log_ts = now
        logger.warning(
            "Voice receive decode errors source=%s opus_corrupted_total=%s corrupted_stream_count=%s invalid_argument_count=%s",
            source,
            self._counters.opus_corrupted_total,
            self._counters.corrupted_stream_count,
            self._counters.invalid_argument_count,
        )

    def _install_router_guard(self, on_decode_error: Callable[[Exception, str], None]) -> None:
        if self._router_guard_installed:
            return
        try:
            from discord.ext.voice_recv import router as vr_router  # type: ignore
        except Exception:
            logger.warning("Voice receive adapter: router module unavailable; guard skipped", exc_info=True)
            return

        packet_router = getattr(vr_router, "PacketRouter", None)
        original = getattr(packet_router, "_do_run", None) if packet_router is not None else None
        if packet_router is None or original is None:
            logger.warning("Voice receive adapter: PacketRouter._do_run unavailable; guard skipped")
            return
        if getattr(original, "_barcello_adapter_guard", False):
            self._router_guard_installed = True
            return

        def _wrapped(router_self: Any, *args: Any, **kwargs: Any) -> Any:
            try:
                return original(router_self, *args, **kwargs)
            except Exception as exc:
                if not self._is_decode_error(exc):
                    raise
                self._register_decode_error(exc)
                on_decode_error(exc, "packet_router")
                self._log_decode_error_summary(source="packet_router")
                return None

        setattr(_wrapped, "_barcello_adapter_guard", True)
        setattr(packet_router, "_do_run", _wrapped)
        self._router_guard_installed = True
        logger.info("Voice receive adapter initialized PacketRouter decode guard")

    async def connect_and_listen(
        self,
        *,
        channel: discord.VoiceChannel,
        on_pcm_frame: Callable[[Optional[discord.User], Any], None],
        on_decode_error: Callable[[Exception, str], None],
    ) -> discord.VoiceClient:
        from discord.ext import voice_recv  # type: ignore

        self._voice_recv = voice_recv
        self._install_router_guard(on_decode_error)

        voice_client = await channel.connect(cls=voice_recv.VoiceRecvClient)

        class _SafeSink(voice_recv.AudioSink):
            def __init__(self, inner: Any) -> None:
                self._inner = inner

            def wants_opus(self) -> bool:
                wants = getattr(self._inner, "wants_opus", None)
                return bool(wants()) if callable(wants) else False

            def write(self, user: Optional[discord.User], data: Any) -> None:
                try:
                    self._inner.write(user, data)
                except Exception as exc:
                    if not self_outer._is_decode_error(exc):
                        raise
                    self_outer._register_decode_error(exc)
                    on_decode_error(exc, "sink.write")
                    self_outer._log_decode_error_summary(source="sink.write")

            def cleanup(self) -> None:
                cleanup = getattr(self._inner, "cleanup", None)
                if callable(cleanup):
                    cleanup()

        self_outer = self
        sink = _SafeSink(voice_recv.BasicSink(on_pcm_frame))
        voice_client.listen(sink)
        logger.info("Voice receive adapter connected guild=%s channel=%s", channel.guild.id, channel.id)
        return voice_client
