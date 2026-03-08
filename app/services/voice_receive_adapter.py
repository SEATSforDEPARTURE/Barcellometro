from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

import discord

from app.vendor.voice_recv import VendorVoiceReceive

logger = logging.getLogger(__name__)


@dataclass
class AdapterDecodeCounters:
    crypto_decode_errors: int = 0
    opus_corrupted_total: int = 0
    corrupted_stream_count: int = 0
    invalid_argument_count: int = 0


class VoiceReceiveAdapter:
    """Application-facing adapter exposing a stable receive API."""

    def __init__(self) -> None:
        self._vendor = VendorVoiceReceive()
        self._voice_client: Optional[discord.VoiceClient] = None
        self._sink: Any = None
        self._attached_client_id: Optional[int] = None
        self._decode_counters = AdapterDecodeCounters()

    def _classify_decode_error(self, exc: Exception) -> Optional[str]:
        message = str(exc).lower()
        if "cryptoerror" in message or "decoding packet data" in message or "decrypt" in message:
            return "crypto"
        if "corrupted stream" in message or "invalid argument" in message or "decode failed" in message:
            return "opus"
        return None

    def _build_decode_error_handler(self, on_decode_error: Callable[[Exception, str], None]) -> Callable[[Exception, str], None]:
        def _on_decode_error(exc: Exception, source: str) -> None:
            decode_type = self._classify_decode_error(exc)
            if decode_type == "crypto":
                logger.error("Voice receive adapter crypto decode failure source=%s error=%s", source, type(exc).__name__)
            elif decode_type == "opus":
                logger.warning("Voice receive adapter opus decode failure source=%s error=%s", source, type(exc).__name__)
            on_decode_error(exc, source)

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
        return self._vendor.available()

    async def connect_and_listen(
        self,
        *,
        channel: discord.VoiceChannel,
        on_pcm_frame: Callable[[Optional[discord.User], Any], None],
        on_decode_error: Callable[[Exception, str], None],
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
        on_decode_error: Callable[[Exception, str], None],
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
