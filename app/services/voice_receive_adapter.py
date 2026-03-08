from __future__ import annotations

import importlib
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

import discord

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
    MIN_VOICE_RECV_VERSION = (0, 5, 2)
    MIN_DAVEY_VERSION = (0, 2, 0)

    def __init__(self) -> None:
        self._vendor = VendorVoiceReceive()
        self._voice_client: Optional[discord.VoiceClient] = None
        self._sink: Any = None
        self._attached_client_id: Optional[int] = None
        self._decode_counters = AdapterDecodeCounters()

    @staticmethod
    def _parse_version_parts(version: str) -> tuple[int, int, int]:
        if not version:
            return (0, 0, 0)
        parts = re.findall(r"\d+", version)
        if not parts:
            return (0, 0, 0)
        numbers = [int(p) for p in parts[:3]]
        while len(numbers) < 3:
            numbers.append(0)
        return tuple(numbers)  # type: ignore[return-value]

    @staticmethod
    def _is_prerelease(version: str) -> bool:
        return bool(re.search(r"[a-zA-Z]", version or ""))

    @staticmethod
    def _version_lt(version: str, minimum: tuple[int, int, int]) -> bool:
        parsed = VoiceReceiveAdapter._parse_version_parts(version)
        if parsed < minimum:
            return True
        if parsed == minimum and VoiceReceiveAdapter._is_prerelease(version):
            return True
        return False

    @staticmethod
    def _fmt_minimum(minimum: tuple[int, int, int]) -> str:
        return ".".join(str(v) for v in minimum)

    def get_voice_stack_report(self) -> VoiceStackCompatibilityReport:
        reasons: list[str] = []
        discord_version = getattr(discord, "__version__", "unknown")
        voice_recv_version = "missing"
        davey_version = "missing"

        if self._version_lt(discord_version, self.MIN_DISCORD_VERSION):
            reasons.append(
                f"discord.py={discord_version} < {self._fmt_minimum(self.MIN_DISCORD_VERSION)}"
            )

        voice_recv_available = False
        try:
            voice_recv = importlib.import_module("discord.ext.voice_recv")
            voice_recv_version = getattr(voice_recv, "__version__", "unknown")
            voice_recv_available = True
            if self._version_lt(voice_recv_version, self.MIN_VOICE_RECV_VERSION):
                reasons.append(
                    f"discord-ext-voice-recv={voice_recv_version} < {self._fmt_minimum(self.MIN_VOICE_RECV_VERSION)}"
                )
        except Exception:
            reasons.append("discord.ext.voice_recv module missing")

        try:
            davey = importlib.import_module("davey")
            davey_version = getattr(davey, "__version__", "unknown")
            if self._version_lt(davey_version, self.MIN_DAVEY_VERSION):
                reasons.append(f"davey={davey_version} < {self._fmt_minimum(self.MIN_DAVEY_VERSION)}")
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
                    "Voice receive adapter crypto decode failure source=%s error=%s user=%s ssrc=%s payload_size=%s",
                    context.source,
                    type(exc).__name__,
                    context.user_id,
                    context.ssrc,
                    context.payload_size,
                )
            elif decode_type == "opus":
                logger.warning(
                    "Voice receive adapter opus decode failure source=%s error=%s user=%s ssrc=%s payload_size=%s",
                    context.source,
                    type(exc).__name__,
                    context.user_id,
                    context.ssrc,
                    context.payload_size,
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

        logger.info("Voice receive adapter connected guild=%s channel=%s", channel.guild.id, channel.id)
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
