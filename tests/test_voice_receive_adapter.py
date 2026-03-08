import importlib.machinery
import sys
import types
from typing import Any

import asyncio

from app.services.voice_receive_adapter import VoiceReceiveAdapter


class DummyOpusError(Exception):
    pass


def _install_fake_voice_recv(*, router_exc: Exception | None = None) -> tuple[Any, Any]:
    module = types.ModuleType("discord.ext.voice_recv")
    module.__version__ = "test"
    module.__spec__ = importlib.machinery.ModuleSpec("discord.ext.voice_recv", loader=None)

    class AudioSink:
        pass

    class BasicSink:
        def __init__(self, cb: Any) -> None:
            self.cb = cb

        def write(self, user: Any, data: Any) -> None:
            self.cb(user, data)

    class VoiceRecvClient:
        pass

    module.AudioSink = AudioSink
    module.BasicSink = BasicSink
    module.VoiceRecvClient = VoiceRecvClient

    router_module = types.ModuleType("discord.ext.voice_recv.router")
    router_module.__spec__ = importlib.machinery.ModuleSpec("discord.ext.voice_recv.router", loader=None)

    class PacketDecoder:
        def decode(self, _packet: Any) -> bytes:
            if router_exc is not None:
                raise router_exc
            return b"ok"

    class PacketRouter:
        def _do_run(self) -> None:
            if router_exc is not None:
                raise router_exc

    router_module.PacketDecoder = PacketDecoder
    router_module.PacketRouter = PacketRouter

    reader_module = types.ModuleType("discord.ext.voice_recv.reader")
    reader_module.__spec__ = importlib.machinery.ModuleSpec("discord.ext.voice_recv.reader", loader=None)

    class AudioReader:
        def _decode_packet(self, _packet: Any) -> bytes:
            if router_exc is not None:
                raise router_exc
            return b"ok"

    reader_module.AudioReader = AudioReader

    sys.modules["discord.ext.voice_recv"] = module
    sys.modules["discord.ext.voice_recv.router"] = router_module
    sys.modules["discord.ext.voice_recv.reader"] = reader_module

    class FakeVoiceClient:
        def __init__(self) -> None:
            self.sink = None
            self.disconnect_calls = 0
            self.connected = True

        def listen(self, sink: Any) -> None:
            self.sink = sink

        def is_connected(self) -> bool:
            return self.connected

        async def disconnect(self, *, force: bool) -> None:
            assert force is True
            self.connected = False
            self.disconnect_calls += 1

    class FakeChannel:
        def __init__(self) -> None:
            self.guild = types.SimpleNamespace(id=1)
            self.id = 2
            self.client = FakeVoiceClient()

        async def connect(self, **_kwargs: Any) -> Any:
            return self.client

    return FakeChannel, PacketRouter


def test_corrupted_stream_does_not_kill_router_loop() -> None:
    FakeChannel, PacketRouter = _install_fake_voice_recv(router_exc=DummyOpusError("corrupted stream"))
    adapter = VoiceReceiveAdapter()
    errors: list[str] = []

    def on_decode_error(exc: Exception, source: str) -> None:
        errors.append(f"{source}:{exc}")

    channel = FakeChannel()
    client = asyncio.run(adapter.connect_and_listen(channel=channel, on_pcm_frame=lambda *_a: None, on_decode_error=on_decode_error))

    router = PacketRouter()
    assert router._do_run() is None
    assert client.sink is not None
    assert errors
    assert adapter.counters.opus_corrupted_total >= 1
    assert adapter.counters.corrupted_stream_count >= 1
    assert adapter.counters.invalid_argument_count == 0


def test_invalid_argument_sink_error_is_dropped_without_fake_pcm() -> None:
    FakeChannel, _PacketRouter = _install_fake_voice_recv()
    adapter = VoiceReceiveAdapter()
    frames: list[bytes] = []
    errors: list[str] = []

    class BrokenData:
        pass

    def on_frame(_user: Any, _data: Any) -> None:
        raise DummyOpusError("invalid argument")

    def on_decode_error(exc: Exception, source: str) -> None:
        errors.append(f"{source}:{exc}")

    channel = FakeChannel()
    client = asyncio.run(adapter.connect_and_listen(channel=channel, on_pcm_frame=on_frame, on_decode_error=on_decode_error))

    client.sink.write(None, BrokenData())
    assert frames == []
    assert errors
    assert adapter.counters.opus_corrupted_total == 1
    assert adapter.counters.corrupted_stream_count == 0
    assert adapter.counters.invalid_argument_count == 1


def test_valid_frame_reaches_plugin_callback_and_disconnect() -> None:
    FakeChannel, _PacketRouter = _install_fake_voice_recv()
    adapter = VoiceReceiveAdapter()
    frames: list[bytes] = []

    class Packet:
        pcm = b"valid-pcm"

    channel = FakeChannel()
    client = asyncio.run(
        adapter.connect_and_listen(
            channel=channel,
            on_pcm_frame=lambda _user, data: frames.append(data.pcm),
            on_decode_error=lambda _exc, _source: None,
        )
    )

    client.sink.write(None, Packet())
    assert frames == [b"valid-pcm"]

    asyncio.run(adapter.disconnect())
    assert client.disconnect_calls == 1
