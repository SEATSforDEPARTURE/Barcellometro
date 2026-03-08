from __future__ import annotations

import importlib
import inspect
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import discord

logger = logging.getLogger(__name__)

DecodeErrorCallback = Callable[[Exception, str], None]


@dataclass
class DecodeErrorCounters:
    crypto_decode_errors: int = 0
    opus_corrupted_total: int = 0
    corrupted_stream_count: int = 0
    invalid_argument_count: int = 0


class VendorVoiceReceive:
    """Locally-controlled wrapper for voice receive/decode behavior."""

    _RUNTIME_MODULES = (
        "discord.ext.voice_recv.router",
        "discord.ext.voice_recv.reader",
        "discord.ext.voice_recv.opus",
    )
    _OPUS_ERROR_TOKENS = ("corrupted stream", "invalid argument", "buffer too small", "decode failed")
    _CRYPTO_ERROR_TOKENS = ("cryptoerror", "decoding packet data", "decrypt")
    _DECODE_HOOK_CANDIDATES = (
        ("discord.ext.voice_recv.router", "PacketDecoder", ("decode",)),
        ("discord.ext.voice_recv.router", "PacketRouter", ("_decode_packet", "decode")),
        ("discord.ext.voice_recv.reader", "AudioReader", ("_decode_packet", "decode")),
        ("discord.ext.voice_recv.opus", "OpusDecoder", ("decode",)),
        ("discord.ext.voice_recv.router", "PacketDecryptor", ("decrypt", "decode")),
    )

    def __init__(self) -> None:
        self.counters = DecodeErrorCounters()
        self._last_summary_log_ts = 0.0
        self._summary_log_interval_sec = 15.0
        self._installed_hooks = 0
        self._introspected = False
        self._patched_sources: list[str] = []

    def _classify_decode_error(self, exc: BaseException) -> Optional[str]:
        message = str(exc).lower()
        if any(token in message for token in self._CRYPTO_ERROR_TOKENS):
            return "crypto"
        if any(token in message for token in self._OPUS_ERROR_TOKENS):
            return "opus"
        return None

    def available(self) -> bool:
        return importlib.util.find_spec("discord.ext.voice_recv") is not None

    def _is_decode_error(self, exc: BaseException) -> bool:
        return self._classify_decode_error(exc) is not None

    def _register_decode_error(self, exc: BaseException) -> None:
        kind = self._classify_decode_error(exc)
        message = str(exc).lower()
        if kind == "crypto":
            self.counters.crypto_decode_errors += 1
            return
        if kind != "opus":
            return
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
            "Voice receive decode errors source=%s crypto_decode_errors=%s opus_corrupted_total=%s corrupted_stream_count=%s invalid_argument_count=%s",
            source,
            self.counters.crypto_decode_errors,
            self.counters.opus_corrupted_total,
            self.counters.corrupted_stream_count,
            self.counters.invalid_argument_count,
        )

    def _discover_runtime_hook_points(self) -> list[tuple[str, str, str]]:
        if self._introspected:
            return []
        discovered: dict[tuple[str, str], set[str]] = {}
        for module_name in self._RUNTIME_MODULES:
            try:
                module = importlib.import_module(module_name)
            except Exception:
                continue
            module_file = getattr(module, "__file__", "<unknown>")
            for class_name, cls in inspect.getmembers(module, inspect.isclass):
                methods = [
                    method_name
                    for method_name, member in inspect.getmembers(cls)
                    if callable(member) and not method_name.startswith("__")
                ]
                discovered[(module_name, class_name)] = set(methods)
                logger.info(
                    "voice_recv runtime discovered class=%s methods=%s module=%s file=%s",
                    class_name,
                    methods,
                    module_name,
                    module_file,
                )

        resolved: list[tuple[str, str, str]] = []
        for module_name, class_name, method_candidates in self._DECODE_HOOK_CANDIDATES:
            methods = discovered.get((module_name, class_name), set())
            for method_name in method_candidates:
                if method_name in methods:
                    resolved.append((module_name, class_name, method_name))
                    break
        self._introspected = True
        return resolved

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
        self._patched_sources = []
        for module_name, class_name, method_name in self._discover_runtime_hook_points():
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
            self._patched_sources.append(f"{class_name}.{method_name}")

        # last-resort safety net: still avoid thread death if decode error bubbles up.
        fallback_installed = False
        try:
            router_module = importlib.import_module("discord.ext.voice_recv.router")
            packet_router = getattr(router_module, "PacketRouter", None)
            do_run = getattr(packet_router, "_do_run", None) if packet_router is not None else None
            if do_run is not None:
                wrapped = self._guard(on_decode_error=on_decode_error, source="PacketRouter._do_run", return_value=None)(do_run)
                setattr(packet_router, "_do_run", wrapped)
                hooks += 1
                fallback_installed = True
                self._patched_sources.append("PacketRouter._do_run")
        except Exception:
            pass

        self._installed_hooks = hooks
        logger.info("Vendor voice receive decode guards installed hooks=%s patched=%s", hooks, self._patched_sources)
        if fallback_installed and hooks == 1:
            logger.warning("Vendor voice receive decode guards using PacketRouter._do_run fallback only")
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
