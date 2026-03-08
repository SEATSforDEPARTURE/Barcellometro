import importlib.machinery
import sys
import types
from typing import Any

import asyncio

from app.services.voice_receive_adapter import VoiceReceiveAdapter


class DummyOpusError(Exception):
    pass


def _install_fake_voice_recv(*, listen_exc: Exception | None = None, router_exc: Exception | None = None) -> tuple[Any, Any]:
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

    class PacketRouter:
        def _do_run(self) -> None:
            if router_exc is not None:
                raise router_exc

    router_module.PacketRouter = PacketRouter

    sys.modules["discord.ext.voice_recv"] = module
    sys.modules["discord.ext.voice_recv.router"] = router_module

    class FakeVoiceClient:
        def __init__(self) -> None:
            self.sink = None

        def listen(self, sink: Any) -> None:
            if listen_exc is not None:
                raise listen_exc
            self.sink = sink

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
    frames: list[bytes] = []

    def on_frame(_user: Any, data: Any) -> None:
        frames.append(getattr(data, "pcm", b""))

    def on_decode_error(exc: Exception, source: str) -> None:
        errors.append(f"{source}:{exc}")

    channel = FakeChannel()
    client = asyncio.run(adapter.connect_and_listen(channel=channel, on_pcm_frame=on_frame, on_decode_error=on_decode_error))

    router = PacketRouter()
    assert router._do_run() is None
    assert client.sink is not None
    assert errors
    assert adapter.counters.opus_corrupted_total == 1
    assert adapter.counters.corrupted_stream_count == 1
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

    # corrupted frame is dropped: no replacement/synthetic PCM generated
    client.sink.write(None, BrokenData())
    assert frames == []
    assert errors
    assert adapter.counters.opus_corrupted_total == 1
    assert adapter.counters.corrupted_stream_count == 0
    assert adapter.counters.invalid_argument_count == 1
