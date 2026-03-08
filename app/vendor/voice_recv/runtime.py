from __future__ import annotations

import importlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import discord

logger = logging.getLogger(__name__)

DecodeErrorCallback = Callable[[Exception, str], None]


@dataclass
class DecodeErrorCounters:
    opus_corrupted_total: int = 0
    corrupted_stream_count: int = 0
    invalid_argument_count: int = 0


class VendorVoiceReceive:
    """Locally-controlled wrapper for voice receive/decode behavior."""

    _DECODE_ERROR_TOKENS = ("corrupted stream", "invalid argument", "buffer too small", "decode failed")
    _DECODE_HOOK_POINTS = (
        ("discord.ext.voice_recv.router", "PacketDecoder", "decode"),
        ("discord.ext.voice_recv.router", "PacketRouter", "_decode_packet"),
        ("discord.ext.voice_recv.reader", "AudioReader", "_decode_packet"),
        ("discord.ext.voice_recv.opus", "OpusDecoder", "decode"),
    )

    def __init__(self) -> None:
        self.counters = DecodeErrorCounters()
        self._last_summary_log_ts = 0.0
        self._summary_log_interval_sec = 15.0
        self._installed_hooks = 0

    def available(self) -> bool:
        return importlib.util.find_spec("discord.ext.voice_recv") is not None

    def _is_decode_error(self, exc: BaseException) -> bool:
        message = str(exc).lower()
        return any(token in message for token in self._DECODE_ERROR_TOKENS)

    def _register_decode_error(self, exc: BaseException) -> None:
        message = str(exc).lower()
        self.counters.opus_corrupted_total += 1
        if "corrupted stream" in message:
            self.counters.corrupted_stream_count += 1
        if "invalid argument" in message:
            self.counters.invalid_argument_count += 1

    def _emit_decode_summary_if_needed(self, *, source: str) -> None:
        now = time.monotonic()
        if now - self._last_summary_log_ts < self._summary_log_interval_sec:
            return
        self._last_summary_log_ts = now
        logger.warning(
            "Voice receive decode errors source=%s opus_corrupted_total=%s corrupted_stream_count=%s invalid_argument_count=%s",
            source,
            self.counters.opus_corrupted_total,
            self.counters.corrupted_stream_count,
            self.counters.invalid_argument_count,
        )

    def _guard(self, *, on_decode_error: DecodeErrorCallback, source: str, return_value: Any = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            if getattr(fn, "_barcello_vendor_decode_guard", False):
                return fn

            def _wrapped(*args: Any, **kwargs: Any) -> Any:
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    if not self._is_decode_error(exc):
                        raise
                    self._register_decode_error(exc)
                    on_decode_error(exc, source)
                    self._emit_decode_summary_if_needed(source=source)
                    return return_value

            setattr(_wrapped, "_barcello_vendor_decode_guard", True)
            return _wrapped

        return _decorator

    def install_decode_guards(self, *, on_decode_error: DecodeErrorCallback) -> int:
        if self._installed_hooks > 0:
            return self._installed_hooks

        hooks = 0
        for module_name, class_name, method_name in self._DECODE_HOOK_POINTS:
            try:
                module = importlib.import_module(module_name)
            except Exception:
                continue
            cls = getattr(module, class_name, None)
            method = getattr(cls, method_name, None) if cls is not None else None
            if cls is None or method is None:
                continue
            wrapped = self._guard(on_decode_error=on_decode_error, source=f"{class_name}.{method_name}")(method)
            setattr(cls, method_name, wrapped)
            hooks += 1

        # last-resort safety net: still avoid thread death if decode error bubbles up.
        try:
            router_module = importlib.import_module("discord.ext.voice_recv.router")
            packet_router = getattr(router_module, "PacketRouter", None)
            do_run = getattr(packet_router, "_do_run", None) if packet_router is not None else None
            if do_run is not None:
                wrapped = self._guard(on_decode_error=on_decode_error, source="PacketRouter._do_run", return_value=None)(do_run)
                setattr(packet_router, "_do_run", wrapped)
                hooks += 1
        except Exception:
            pass

        self._installed_hooks = hooks
        logger.info("Vendor voice receive decode guards installed hooks=%s", hooks)
        return hooks

    def build_sink(
        self,
        *,
        voice_recv_module: Any,
        on_pcm_frame: Callable[[Optional[discord.User], Any], None],
        on_decode_error: DecodeErrorCallback,
    ) -> Any:
        outer = self

        class _SafeSink(voice_recv_module.AudioSink):
            def __init__(self, inner: Any) -> None:
                self._inner = inner

            def wants_opus(self) -> bool:
                wants = getattr(self._inner, "wants_opus", None)
                return bool(wants()) if callable(wants) else False

            def write(self, user: Optional[discord.User], data: Any) -> None:
                try:
                    self._inner.write(user, data)
                except Exception as exc:
                    if not outer._is_decode_error(exc):
                        raise
                    outer._register_decode_error(exc)
                    on_decode_error(exc, "sink.write")
                    outer._emit_decode_summary_if_needed(source="sink.write")

            def cleanup(self) -> None:
                cleanup = getattr(self._inner, "cleanup", None)
                if callable(cleanup):
                    cleanup()

        return _SafeSink(voice_recv_module.BasicSink(on_pcm_frame))
