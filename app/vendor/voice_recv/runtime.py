from __future__ import annotations

import importlib
import inspect
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import discord

logger = logging.getLogger(__name__)

@dataclass
class DecodeErrorContext:
    source: str
    user_id: Optional[int] = None
    ssrc: Optional[int] = None
    payload_size: Optional[int] = None
    session_id: Optional[str] = None
    guild_id: Optional[int] = None
    channel_id: Optional[int] = None


DecodeErrorCallback = Callable[[Exception, DecodeErrorContext], None]


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
    _DECODE_HOOK_POINTS = (
        ("discord.ext.voice_recv.opus", "PacketDecoder", "pop_data"),
        ("discord.ext.voice_recv.opus", "PacketDecoder", "_process_packet"),
        ("discord.ext.voice_recv.opus", "PacketDecoder", "_decode_packet"),
        ("discord.ext.voice_recv.opus", "Decoder", "decode"),
    )
    _FALLBACK_HOOK_POINT = ("discord.ext.voice_recv.router", "PacketRouter", "_do_run")

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

    def _discover_runtime_hook_points(self) -> tuple[list[tuple[str, str, str]], dict[str, str]]:
        if self._introspected:
            return [], {}
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
        unresolved: dict[str, str] = {}
        for module_name, class_name, method_name in self._DECODE_HOOK_POINTS:
            methods = discovered.get((module_name, class_name), set())
            target = f"{module_name}.{class_name}.{method_name}"
            if method_name in methods:
                resolved.append((module_name, class_name, method_name))
                continue
            if not methods:
                unresolved[target] = "class_not_found_or_no_callable_methods"
            else:
                unresolved[target] = f"method_not_found available={sorted(methods)}"
        self._introspected = True
        return resolved, unresolved

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
                    on_decode_error(exc, self._extract_decode_error_context(source=source, args=args, kwargs=kwargs))
                    self._emit_decode_summary_if_needed(source=source)
                    return return_value

            setattr(_wrapped, "_barcello_vendor_decode_guard", True)
            return _wrapped

        return _decorator

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        try:
            return int(value) if value is not None else None
        except Exception:
            return None

    def _extract_decode_error_context(self, *, source: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> DecodeErrorContext:
        user_id: Optional[int] = None
        ssrc: Optional[int] = None
        payload_size: Optional[int] = None
        session_id: Optional[str] = None
        guild_id: Optional[int] = None
        channel_id: Optional[int] = None

        candidates = list(args) + list(kwargs.values())
        for candidate in candidates:
            if candidate is None:
                continue
            if user_id is None:
                user_id = self._coerce_int(getattr(candidate, "id", None) or getattr(candidate, "user_id", None))
            if ssrc is None:
                ssrc = self._coerce_int(getattr(candidate, "ssrc", None))
            if payload_size is None:
                payload = getattr(candidate, "payload", None)
                if isinstance(payload, (bytes, bytearray)):
                    payload_size = len(payload)
                elif isinstance(candidate, (bytes, bytearray)):
                    payload_size = len(candidate)
                else:
                    data = getattr(candidate, "data", None)
                    if isinstance(data, (bytes, bytearray)):
                        payload_size = len(data)
            if session_id is None:
                maybe_session = getattr(candidate, "session_id", None)
                if maybe_session is not None:
                    session_id = str(maybe_session)
            if guild_id is None:
                guild = getattr(candidate, "guild", None)
                guild_id = self._coerce_int(getattr(guild, "id", None) or getattr(candidate, "guild_id", None))
            if channel_id is None:
                channel = getattr(candidate, "channel", None)
                channel_id = self._coerce_int(getattr(channel, "id", None) or getattr(candidate, "channel_id", None))

        return DecodeErrorContext(
            source=source,
            user_id=user_id,
            ssrc=ssrc,
            payload_size=payload_size,
            session_id=session_id,
            guild_id=guild_id,
            channel_id=channel_id,
        )

    def install_decode_guards(self, *, on_decode_error: DecodeErrorCallback) -> int:
        if self._installed_hooks > 0:
            return self._installed_hooks

        hooks = 0
        self._patched_sources = []
        resolved, unresolved = self._discover_runtime_hook_points()
        for module_name, class_name, method_name in resolved:
            try:
                module = importlib.import_module(module_name)
            except Exception:
                unresolved[f"{module_name}.{class_name}.{method_name}"] = "module_import_failed"
                continue
            cls = getattr(module, class_name, None)
            method = getattr(cls, method_name, None) if cls is not None else None
            if cls is None or method is None:
                unresolved[f"{module_name}.{class_name}.{method_name}"] = "class_or_method_missing_at_patch_time"
                continue
            if not callable(method):
                unresolved[f"{module_name}.{class_name}.{method_name}"] = "method_not_callable"
                continue
            wrapped = self._guard(on_decode_error=on_decode_error, source=f"{class_name}.{method_name}")(method)
            setattr(cls, method_name, wrapped)
            hooks += 1
            self._patched_sources.append(f"{class_name}.{method_name}")
            logger.info(
                "Installed decode guard target=%s.%s.%s",
                module_name,
                class_name,
                method_name,
            )

        # last-resort safety net: still avoid thread death if decode error bubbles up.
        fallback_installed = False
        try:
            module_name, class_name, method_name = self._FALLBACK_HOOK_POINT
            router_module = importlib.import_module(module_name)
            packet_router = getattr(router_module, class_name, None)
            do_run = getattr(packet_router, method_name, None) if packet_router is not None else None
            if do_run is not None:
                wrapped = self._guard(on_decode_error=on_decode_error, source="PacketRouter._do_run", return_value=None)(do_run)
                setattr(packet_router, method_name, wrapped)
                hooks += 1
                fallback_installed = True
                self._patched_sources.append("PacketRouter._do_run")
                logger.info("Installed decode guard target=%s.%s.%s", module_name, class_name, method_name)
            else:
                unresolved[f"{module_name}.{class_name}.{method_name}"] = "class_or_method_missing_at_patch_time"
        except Exception:
            unresolved["discord.ext.voice_recv.router.PacketRouter._do_run"] = "fallback_install_failed"

        self._installed_hooks = hooks
        logger.info("Vendor voice receive decode guards installed hooks=%s patched=%s", hooks, self._patched_sources)
        if fallback_installed and hooks == 1:
            logger.warning(
                "Vendor voice receive decode guards using PacketRouter._do_run fallback only unresolved=%s",
                unresolved,
            )
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
                    on_decode_error(exc, outer._extract_decode_error_context(source="sink.write", args=(user, data), kwargs={}))
                    outer._emit_decode_summary_if_needed(source="sink.write")

            def cleanup(self) -> None:
                cleanup = getattr(self._inner, "cleanup", None)
                if callable(cleanup):
                    cleanup()

        return _SafeSink(voice_recv_module.BasicSink(on_pcm_frame))
