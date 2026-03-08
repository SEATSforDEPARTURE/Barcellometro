from __future__ import annotations

import importlib
import inspect
import logging
import time
from functools import wraps
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
    packet_type: Optional[str] = None
    decoder_instance_id: Optional[int] = None
    packet_origin: Optional[str] = None
    payload_preview_hex: Optional[str] = None
    payload_looks_like_rtp: Optional[bool] = None


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
    )
    _FALLBACK_HOOK_POINT = ("discord.ext.voice_recv.router", "PacketRouter", "_do_run")

    def __init__(self) -> None:
        self.counters = DecodeErrorCounters()
        self._last_summary_log_ts = 0.0
        self._summary_log_interval_sec = 15.0
        self._installed_hooks = 0
        self._introspected = False
        self._patched_sources: list[str] = []
        self._last_stage_trace_ts: dict[str, float] = {}
        self._stage_trace_interval_sec = 2.0
        self._detailed_log_limit = 6
        self._detailed_log_count = 0

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

    @staticmethod
    def _extract_trace_payload(source: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        candidate = VendorVoiceReceive._extract_payload_candidate(source, args, kwargs)
        if isinstance(candidate, (bytes, bytearray)):
            return candidate
        for attr in ("decrypted_data", "payload", "data"):
            maybe = getattr(candidate, attr, None)
            if isinstance(maybe, (bytes, bytearray)):
                return maybe
        return None

    def _trace_decode_stage(self, *, source: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        now = time.monotonic()
        last = self._last_stage_trace_ts.get(source, 0.0)
        if now - last < self._stage_trace_interval_sec:
            return
        self._last_stage_trace_ts[source] = now
        payload = self._extract_trace_payload(source, args, kwargs)
        payload_size: Optional[int] = None
        packet_type: Optional[str] = None
        payload_preview_hex: Optional[str] = None
        payload_looks_like_rtp: Optional[bool] = None
        if isinstance(payload, (bytes, bytearray)):
            payload_size = len(payload)
            packet_type = type(payload).__name__
            payload_preview_hex = self._payload_preview(payload)
            payload_looks_like_rtp = self._looks_like_rtp(payload)
        logger.debug(
            "Voice recv decode stage source=%s decoder_instance_id=%s packet_id=%s packet_type=%s payload_size=%s payload_looks_like_rtp=%s payload_preview_hex=%s",
            source,
            id(args[0]) if args else None,
            id(args[1]) if len(args) > 1 else None,
            packet_type,
            payload_size,
            payload_looks_like_rtp,
            payload_preview_hex,
        )

    def _guard(self, *, on_decode_error: DecodeErrorCallback, source: str, return_value: Any = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            if getattr(fn, "_barcello_vendor_decode_guard", False):
                return fn

            @wraps(fn)
            def _wrapped(*args: Any, **kwargs: Any) -> Any:
                args, kwargs = self._normalize_decoder_input(source=source, args=args, kwargs=kwargs)
                self._trace_decode_stage(source=source, args=args, kwargs=kwargs)
                if source == "Decoder.decode":
                    payload = self._extract_payload_candidate(source, args, kwargs)
                    if isinstance(payload, (bytes, bytearray)) and self._looks_like_rtp(payload):
                        logger.warning(
                            "Voice recv observed RTP-like payload at Decoder.decode boundary decoder_instance_id=%s payload_size=%s",
                            id(args[0]) if args else None,
                            len(payload),
                        )
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    if not self._is_decode_error(exc):
                        raise
                    self._register_decode_error(exc)
                    self._log_decode_boundary(source=source, args=args, kwargs=kwargs, exc=exc)
                    on_decode_error(exc, self._extract_decode_error_context(source=source, args=args, kwargs=kwargs))
                    self._emit_decode_summary_if_needed(source=source)
                    return return_value

            setattr(_wrapped, "_barcello_vendor_decode_guard", True)
            return _wrapped

        return _decorator

    @staticmethod
    def _extract_payload_bytes(candidate: Any) -> Optional[bytes | bytearray]:
        if isinstance(candidate, (bytes, bytearray)):
            return candidate
        for attr in ("decrypted_data", "payload", "data"):
            value = getattr(candidate, attr, None)
            if isinstance(value, (bytes, bytearray)):
                return value
        return None

    def _log_decode_boundary(self, *, source: str, args: tuple[Any, ...], kwargs: dict[str, Any], exc: BaseException) -> None:
        if self._detailed_log_count >= self._detailed_log_limit:
            return
        payload = self._extract_payload_candidate(source, args, kwargs)
        payload_bytes = self._extract_payload_bytes(payload)
        stack_frames = inspect.stack(context=0)[2:6]
        stack = " > ".join(f"{frame.function}@{frame.lineno}" for frame in stack_frames)
        logger.warning(
            "Voice recv decode boundary source=%s error=%s arg_type=%s payload_len=%s payload_preview_hex=%s payload_looks_like_rtp=%s hook=%s stack=%s",
            source,
            type(exc).__name__,
            type(payload).__name__ if payload is not None else None,
            len(payload_bytes) if payload_bytes is not None else None,
            self._payload_preview(payload_bytes) if payload_bytes is not None else None,
            self._looks_like_rtp(payload_bytes) if payload_bytes is not None else None,
            source,
            stack,
        )
        self._detailed_log_count += 1

    def _normalize_decoder_input(self, *, source: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
        if source not in {"PacketDecoder.pop_data", "PacketDecoder._process_packet", "PacketDecoder._decode_packet"}:
            return args, kwargs
        payload = self._extract_payload_candidate(source, args, kwargs)
        payload_bytes = self._extract_payload_bytes(payload)
        if not isinstance(payload_bytes, (bytes, bytearray)):
            return args, kwargs
        if not self._looks_like_rtp(payload_bytes):
            return args, kwargs
        opus_payload = self._extract_opus_from_rtp(payload_bytes)
        if not opus_payload:
            return args, kwargs
        if isinstance(payload, (bytes, bytearray)):
            new_args = list(args)
            new_kwargs = dict(kwargs)
            if len(new_args) >= 2:
                new_args[1] = opus_payload
            elif "packet" in new_kwargs:
                new_kwargs["packet"] = opus_payload
            elif "data" in new_kwargs:
                new_kwargs["data"] = opus_payload
            else:
                return args, kwargs
            logger.warning(
                "Voice recv normalized RTP packet before decoder source=%s payload_len=%s opus_len=%s",
                source,
                len(payload_bytes),
                len(opus_payload),
            )
            return tuple(new_args), new_kwargs

        for attr in ("decrypted_data", "payload", "data"):
            value = getattr(payload, attr, None)
            if isinstance(value, (bytes, bytearray)) and self._looks_like_rtp(value):
                try:
                    setattr(payload, attr, opus_payload)
                    logger.warning(
                        "Voice recv normalized RTP field before decoder source=%s field=%s payload_len=%s opus_len=%s",
                        source,
                        attr,
                        len(value),
                        len(opus_payload),
                    )
                except Exception:
                    return args, kwargs
                break
        return args, kwargs

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        try:
            return int(value) if value is not None else None
        except Exception:
            return None

    @staticmethod
    def _payload_preview(payload: bytes | bytearray, *, max_len: int = 8) -> str:
        return bytes(payload[:max_len]).hex()

    @staticmethod
    def _looks_like_rtp(payload: bytes | bytearray) -> bool:
        if len(payload) < 12:
            return False
        first = payload[0]
        second = payload[1]
        version = (first >> 6) & 0b11
        if version != 2:
            return False
        csrc_count = first & 0x0F
        has_extension = bool(first & 0x10)
        padding = bool(first & 0x20)
        payload_type = second & 0x7F
        if payload_type < 96 or payload_type > 127:
            return False
        offset = 12 + (csrc_count * 4)
        if len(payload) < offset:
            return False
        if has_extension:
            if len(payload) < offset + 4:
                return False
            ext_len_words = int.from_bytes(payload[offset + 2 : offset + 4], byteorder="big")
            offset += 4 + (ext_len_words * 4)
            if len(payload) < offset:
                return False
        if padding:
            pad_len = payload[-1]
            if pad_len <= 0 or pad_len > len(payload) - offset:
                return False
        return True

    @staticmethod
    def _extract_opus_from_rtp(payload: bytes | bytearray) -> Optional[bytes]:
        if not VendorVoiceReceive._looks_like_rtp(payload):
            return None
        first = payload[0]
        csrc_count = first & 0x0F
        has_extension = bool(first & 0x10)
        padding = bool(first & 0x20)
        offset = 12 + (csrc_count * 4)
        if has_extension:
            ext_len_words = int.from_bytes(payload[offset + 2 : offset + 4], byteorder="big")
            offset += 4 + (ext_len_words * 4)
        end = len(payload)
        if padding:
            end -= payload[-1]
        if offset >= end:
            return None
        return bytes(payload[offset:end])

    @staticmethod
    def _packet_origin_for_source(source: str) -> Optional[str]:
        if source == "Decoder.decode":
            return "decoder.decode.payload"
        if source in {"PacketDecoder.pop_data", "PacketDecoder._decode_packet", "PacketDecoder._process_packet"}:
            return f"packet_decoder.{source.split('.', 1)[1]}"
        if source == "sink.write":
            return "sink.write.data"
        if source == "PacketRouter._do_run":
            return "packet_router.run"
        return None

    @staticmethod
    def _extract_payload_candidate(source: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        if source == "Decoder.decode":
            if len(args) >= 2:
                return args[1]
            return kwargs.get("packet") or kwargs.get("data")
        if source in {"PacketDecoder.pop_data", "PacketDecoder._decode_packet", "PacketDecoder._process_packet"}:
            if len(args) >= 2:
                return args[1]
            return kwargs.get("packet") or kwargs.get("data")
        if source == "sink.write":
            if len(args) >= 2:
                return args[1]
            return kwargs.get("data")
        return None

    @staticmethod
    def _extract_candidate_context_value(candidate: Any, attr: str) -> Any:
        current = candidate
        for _ in range(3):
            if current is None:
                return None
            value = getattr(current, attr, None)
            if value is not None:
                return value
            current = getattr(current, "packet", None) or getattr(current, "data", None) or getattr(current, "voice_client", None)
        return None

    def _extract_decode_error_context(self, *, source: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> DecodeErrorContext:
        user_id: Optional[int] = None
        ssrc: Optional[int] = None
        payload_size: Optional[int] = None
        session_id: Optional[str] = None
        guild_id: Optional[int] = None
        channel_id: Optional[int] = None
        packet_type: Optional[str] = None
        decoder_instance_id: Optional[int] = None
        packet_origin = self._packet_origin_for_source(source)
        payload_preview_hex: Optional[str] = None
        payload_looks_like_rtp: Optional[bool] = None

        if args:
            decoder_instance_id = id(args[0])

        payload_candidate = self._extract_payload_candidate(source, args, kwargs)
        if isinstance(payload_candidate, (bytes, bytearray)):
            payload_size = len(payload_candidate)
            packet_type = type(payload_candidate).__name__
            payload_preview_hex = self._payload_preview(payload_candidate)
            payload_looks_like_rtp = self._looks_like_rtp(payload_candidate)
        else:
            candidate_payload = getattr(payload_candidate, "payload", None)
            if isinstance(candidate_payload, (bytes, bytearray)):
                payload_size = len(candidate_payload)
                packet_type = type(candidate_payload).__name__
                payload_preview_hex = self._payload_preview(candidate_payload)
                payload_looks_like_rtp = self._looks_like_rtp(candidate_payload)

        candidates = list(args) + list(kwargs.values())
        first_candidate = candidates[0] if candidates else None
        for candidate in candidates:
            if candidate is None:
                continue
            if user_id is None:
                user_id = self._coerce_int(
                    getattr(candidate, "id", None)
                    or getattr(candidate, "user_id", None)
                    or self._extract_candidate_context_value(candidate, "user_id")
                )
            if ssrc is None:
                ssrc = self._coerce_int(getattr(candidate, "ssrc", None) or self._extract_candidate_context_value(candidate, "ssrc"))
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
                maybe_session = (
                    getattr(candidate, "session_id", None)
                    or self._extract_candidate_context_value(candidate, "session_id")
                )
                if maybe_session is not None:
                    session_id = str(maybe_session)
            if guild_id is None:
                guild = getattr(candidate, "guild", None) or self._extract_candidate_context_value(candidate, "guild")
                guild_id = self._coerce_int(
                    getattr(guild, "id", None)
                    or getattr(candidate, "guild_id", None)
                    or self._extract_candidate_context_value(candidate, "guild_id")
                )
            if channel_id is None:
                channel = getattr(candidate, "channel", None) or self._extract_candidate_context_value(candidate, "channel")
                channel_id = self._coerce_int(
                    getattr(channel, "id", None)
                    or getattr(candidate, "channel_id", None)
                    or self._extract_candidate_context_value(candidate, "channel_id")
                )
            if packet_type is None:
                if isinstance(candidate, (bytes, bytearray)):
                    packet_type = type(candidate).__name__
                else:
                    payload = getattr(candidate, "payload", None)
                    data = getattr(candidate, "data", None)
                    pcm = getattr(candidate, "pcm", None)
                    if isinstance(payload, (bytes, bytearray)):
                        packet_type = type(payload).__name__
                    elif isinstance(data, (bytes, bytearray)):
                        packet_type = type(data).__name__
                    elif isinstance(pcm, (bytes, bytearray)):
                        packet_type = type(pcm).__name__
                    elif candidate is not first_candidate:
                        packet_type = type(candidate).__name__

        return DecodeErrorContext(
            source=source,
            user_id=user_id,
            ssrc=ssrc,
            payload_size=payload_size,
            session_id=session_id,
            guild_id=guild_id,
            channel_id=channel_id,
            packet_type=packet_type,
            decoder_instance_id=decoder_instance_id,
            packet_origin=packet_origin,
            payload_preview_hex=payload_preview_hex,
            payload_looks_like_rtp=payload_looks_like_rtp,
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
