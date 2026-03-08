from __future__ import annotations

import logging
from typing import Any, Callable, Optional

import discord

from app.vendor.voice_recv import DecodeErrorCounters, VendorVoiceReceive

logger = logging.getLogger(__name__)


class VoiceReceiveAdapter:
    """Application-facing adapter exposing a stable receive API."""

    def __init__(self) -> None:
        self._vendor = VendorVoiceReceive()
        self._voice_client: Optional[discord.VoiceClient] = None

    @property
    def counters(self) -> DecodeErrorCounters:
        return self._vendor.counters

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

        self._vendor.install_decode_guards(on_decode_error=on_decode_error)
        sink = self._vendor.build_sink(
            voice_recv_module=voice_recv,
            on_pcm_frame=on_pcm_frame,
            on_decode_error=on_decode_error,
        )

        voice_client = await channel.connect(cls=voice_recv.VoiceRecvClient)
        voice_client.listen(sink)
        self._voice_client = voice_client

        logger.info("Voice receive adapter connected guild=%s channel=%s", channel.guild.id, channel.id)
        return voice_client

    async def disconnect(self) -> None:
        if self._voice_client is None:
            return
        try:
            if self._voice_client.is_connected():
                await self._voice_client.disconnect(force=True)
        finally:
            self._voice_client = None
            logger.info("Voice receive adapter disconnected")
