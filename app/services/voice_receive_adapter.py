from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

import discord
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

from app.vendor.voice_recv import DecodeErrorContext, VendorVoiceReceive

logger = logging.getLogger(__name__)


@dataclass
class AdapterDecodeCounters:
    crypto_decode_errors: int = 0
    opus_corrupted_total: int = 0
    corrupted_stream_count: int = 0
    invalid_argument_count: int = 0


@dataclass
class VoiceStackCompatibilityReport:
    available: bool
    compatible: bool
    discord_version: str
    voice_recv_version: str
    davey_version: str
    reasons: list[str]


class VoiceReceiveAdapter:
    """Application-facing adapter exposing a stable receive API."""

    MIN_DISCORD_VERSION = (2, 7, 0)
    MIN_DAVEY_VERSION = (0, 1, 4)
    VOICE_RECV_SUPPORTED_SPECIFIER = SpecifierSet(">=0.5.2a0,<0.5.3", prereleases=True)
    VOICE_RECV_SUPPORTED_RUNTIME_ALIASES = {"0.5.2a"}

    def __init__(self) -> None:
        self._vendor = VendorVoiceReceive()
        self._voice_client: Optional[discord.VoiceClient] = None
        self._sink: Any = None
        self._attached_client_id: Optional[int] = None
        self._decode_counters = AdapterDecodeCounters()

    @staticmethod
    def _version_lt(version: str, minimum: tuple[int, int, int]) -> tuple[bool, Optional[str]]:
        minimum_str = VoiceReceiveAdapter._fmt_minimum(minimum)
        try:
            parsed = Version(version)
        except InvalidVersion:
            return True, f"unparseable version '{version}'"
        minimum_version = Version(minimum_str)
        if parsed < minimum_version:
            return True, f"{version} < {minimum_str}"
        return False, None

    @classmethod
    def _voice_recv_incompatible(cls, version: str) -> tuple[bool, Optional[str]]:
        if version in cls.VOICE_RECV_SUPPORTED_RUNTIME_ALIASES:
            return False, None
        try:
            parsed = Version(version)
        except InvalidVersion:
            return True, f"unparseable version '{version}'"
        if parsed not in cls.VOICE_RECV_SUPPORTED_SPECIFIER:
            return True, f"{version} not in supported range {cls.VOICE_RECV_SUPPORTED_SPECIFIER}"
        return False, None

    @staticmethod
    def _fmt_minimum(minimum: tuple[int, int, int]) -> str:
        return ".".join(str(v) for v in minimum)

    def get_voice_stack_report(self) -> VoiceStackCompatibilityReport:
        reasons: list[str] = []
        discord_version = getattr(discord, "__version__", "unknown")
        voice_recv_version = "missing"
        davey_version = "missing"

        discord_incompatible, discord_detail = self._version_lt(discord_version, self.MIN_DISCORD_VERSION)
        if discord_incompatible:
            reasons.append(f"discord.py={discord_detail}")

        voice_recv_available = False
        try:
            voice_recv = importlib.import_module("discord.ext.voice_recv")
            voice_recv_version = getattr(voice_recv, "__version__", "unknown")
            voice_recv_available = True
            voice_recv_incompatible, voice_recv_detail = self._voice_recv_incompatible(voice_recv_version)
            if voice_recv_incompatible:
                reasons.append(f"discord-ext-voice-recv={voice_recv_detail}")
        except Exception:
            reasons.append("discord.ext.voice_recv module missing")

        try:
            davey = importlib.import_module("davey")
            davey_version = getattr(davey, "__version__", "unknown")
            davey_incompatible, davey_detail = self._version_lt(davey_version, self.MIN_DAVEY_VERSION)
            if davey_incompatible:
                reasons.append(f"davey={davey_detail}")
        except Exception:
            reasons.append("davey module missing")

        compatible = len(reasons) == 0
        available = voice_recv_available
        return VoiceStackCompatibilityReport(
            available=available,
            compatible=compatible,
            discord_version=discord_version,
            voice_recv_version=voice_recv_version,
            davey_version=davey_version,
            reasons=reasons,
        )

    def _classify_decode_error(self, exc: Exception) -> Optional[str]:
        message = str(exc).lower()
        if "cryptoerror" in message or "decoding packet data" in message or "decrypt" in message:
            return "crypto"
        if "corrupted stream" in message or "invalid argument" in message or "decode failed" in message:
            return "opus"
        return None

    def _build_decode_error_handler(
        self,
        on_decode_error: Callable[[Exception, DecodeErrorContext], None],
    ) -> Callable[[Exception, DecodeErrorContext], None]:
        def _on_decode_error(exc: Exception, context: DecodeErrorContext) -> None:
            decode_type = self._classify_decode_error(exc)
            if decode_type == "crypto":
                logger.error(
                    "Voice receive adapter crypto decode failure source=%s root_cause_source=%s event_id=%s error=%s user=%s ssrc=%s payload_size=%s",
                    context.source,
                    context.root_cause_source,
                    context.event_id,
                    type(exc).__name__,
                    context.user_id,
                    context.ssrc,
                    context.payload_size,
                )
            elif decode_type == "opus":
                logger.warning(
                    "Voice receive adapter opus decode failure source=%s root_cause_source=%s event_id=%s error=%s user=%s ssrc=%s payload_size=%s packet_origin=%s packet_type=%s payload_preview_hex=%s payload_looks_like_rtp=%s decoder_instance_id=%s context_session=%s context_guild=%s context_channel=%s",
                    context.source,
                    context.root_cause_source,
                    context.event_id,
                    type(exc).__name__,
                    context.user_id,
                    context.ssrc,
                    context.payload_size,
                    context.packet_origin,
                    context.packet_type,
                    context.payload_preview_hex,
                    context.payload_looks_like_rtp,
                    context.decoder_instance_id,
                    context.session_id,
                    context.guild_id,
                    context.channel_id,
                )
            on_decode_error(exc, context)

        return _on_decode_error

    @property
    def counters(self) -> AdapterDecodeCounters:
        vendor = self._vendor.counters
        self._decode_counters.crypto_decode_errors = vendor.crypto_decode_errors
        self._decode_counters.opus_corrupted_total = vendor.opus_corrupted_total
        self._decode_counters.corrupted_stream_count = vendor.corrupted_stream_count
        self._decode_counters.invalid_argument_count = vendor.invalid_argument_count
        return self._decode_counters

    def listener_attached(self, voice_client: Optional[discord.VoiceClient]) -> bool:
        if voice_client is None:
            return False
        return self._attached_client_id == id(voice_client)

    def available(self) -> bool:
        report = self.get_voice_stack_report()
        return report.available and report.compatible

    def sink_wants_opus(self) -> Optional[bool]:
        sink = self._sink
        if sink is None:
            return None
        wants_opus = getattr(sink, "wants_opus", None)
        if not callable(wants_opus):
            return None
        try:
            return bool(wants_opus())
        except Exception:
            return None

    def sink_debug_info(self) -> dict[str, Any]:
        sink = self._sink
        info: dict[str, Any] = {
            "attached_client_id": self._attached_client_id,
            "sink_present": sink is not None,
            "sink_type": type(sink).__name__ if sink is not None else None,
            "sink_wants_opus": self.sink_wants_opus(),
            "vendor_hooks": self._vendor._installed_hooks,
            "vendor_patched_sources": list(self._vendor._patched_sources),
        }
        inner = getattr(sink, "_inner", None) if sink is not None else None
        if inner is not None:
            info["inner_sink_type"] = type(inner).__name__
        return info

    async def connect_and_listen(
        self,
        *,
        channel: discord.VoiceChannel,
        on_pcm_frame: Callable[[Optional[discord.User], Any], None],
        on_decode_error: Callable[[Exception, DecodeErrorContext], None],
    ) -> discord.VoiceClient:
        from discord.ext import voice_recv  # type: ignore

        _on_decode_error = self._build_decode_error_handler(on_decode_error)

        self._vendor.install_decode_guards(on_decode_error=_on_decode_error)
        sink = self._vendor.build_sink(
            voice_recv_module=voice_recv,
            on_pcm_frame=on_pcm_frame,
            on_decode_error=_on_decode_error,
        )

        voice_client = await channel.connect(cls=voice_recv.VoiceRecvClient)
        voice_client.listen(sink)
        self._voice_client = voice_client
        self._sink = sink
        self._attached_client_id = id(voice_client)

        logger.info(
            "Voice receive adapter connected guild=%s channel=%s sink=%s",
            channel.guild.id,
            channel.id,
            self.sink_debug_info(),
        )
        return voice_client

    def attach_listener(
        self,
        *,
        voice_client: discord.VoiceClient,
        voice_recv_module: Any,
        on_pcm_frame: Callable[[Optional[discord.User], Any], None],
        on_decode_error: Callable[[Exception, DecodeErrorContext], None],
    ) -> bool:
        if self.listener_attached(voice_client):
            return False

        _on_decode_error = self._build_decode_error_handler(on_decode_error)

        self._vendor.install_decode_guards(on_decode_error=_on_decode_error)
        sink = self._vendor.build_sink(
            voice_recv_module=voice_recv_module,
            on_pcm_frame=on_pcm_frame,
            on_decode_error=_on_decode_error,
        )
        voice_client.listen(sink)
        self._voice_client = voice_client
        self._sink = sink
        self._attached_client_id = id(voice_client)
        logger.info(
            "Voice receive adapter listener attached client_id=%s sink=%s",
            self._attached_client_id,
            self.sink_debug_info(),
        )
        return True

    async def disconnect(self) -> None:
        if self._voice_client is None:
            return
        try:
            if self._voice_client.is_connected():
                await self._voice_client.disconnect(force=True)
        finally:
            self._voice_client = None
            self._sink = None
            self._attached_client_id = None
            logger.info("Voice receive adapter disconnected")
