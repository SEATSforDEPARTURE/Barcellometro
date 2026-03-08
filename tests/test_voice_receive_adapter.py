import importlib.machinery
import inspect
import sys
import types
from typing import Any

import asyncio

from app.services.voice_receive_adapter import VoiceReceiveAdapter
from app.vendor.voice_recv import DecodeErrorContext


class DummyOpusError(Exception):
    pass


def _install_fake_voice_recv(*, router_exc: Exception | None = None) -> tuple[Any, Any, Any, Any]:
    module = types.ModuleType("discord.ext.voice_recv")
    module.__version__ = "0.5.2"
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

    reader_module = types.ModuleType("discord.ext.voice_recv.reader")
    reader_module.__spec__ = importlib.machinery.ModuleSpec("discord.ext.voice_recv.reader", loader=None)

    class AudioReader:
        def _decode_packet(self, _packet: Any) -> bytes:
            if router_exc is not None:
                raise router_exc
            return b"ok"

    reader_module.AudioReader = AudioReader


    opus_module = types.ModuleType("discord.ext.voice_recv.opus")
    opus_module.__spec__ = importlib.machinery.ModuleSpec("discord.ext.voice_recv.opus", loader=None)

    class PacketDecoder:
        def pop_data(self, _packet: Any) -> bytes:
            if router_exc is not None:
                raise router_exc
            return b"ok"

        def _process_packet(self, _packet: Any) -> bytes:
            if router_exc is not None:
                raise router_exc
            return b"ok"

        def _decode_packet(self, _packet: Any) -> bytes:
            if router_exc is not None:
                raise router_exc
            return b"ok"

    class Decoder:
        def decode(self, _packet: Any) -> bytes:
            if router_exc is not None:
                raise router_exc
            return b"ok"

    opus_module.PacketDecoder = PacketDecoder
    opus_module.Decoder = Decoder

    sys.modules["discord.ext.voice_recv"] = module
    sys.modules["discord.ext.voice_recv.router"] = router_module
    sys.modules["discord.ext.voice_recv.reader"] = reader_module
    sys.modules["discord.ext.voice_recv.opus"] = opus_module
    sys.modules["davey"] = types.SimpleNamespace(__version__="0.1.4")

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

    return FakeChannel, PacketRouter, PacketDecoder, Decoder


def test_corrupted_stream_does_not_kill_router_loop() -> None:
    FakeChannel, PacketRouter, _PacketDecoder, _Decoder = _install_fake_voice_recv(router_exc=DummyOpusError("corrupted stream"))
    adapter = VoiceReceiveAdapter()
    errors: list[str] = []

    def on_decode_error(exc: Exception, context: DecodeErrorContext) -> None:
        errors.append(f"{context.source}:{exc}")

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
    FakeChannel, _PacketRouter, _PacketDecoder, _Decoder = _install_fake_voice_recv()
    adapter = VoiceReceiveAdapter()
    frames: list[bytes] = []
    errors: list[str] = []

    class BrokenData:
        pass

    def on_frame(_user: Any, _data: Any) -> None:
        raise DummyOpusError("invalid argument")

    def on_decode_error(exc: Exception, context: DecodeErrorContext) -> None:
        errors.append(f"{context.source}:{exc}")

    channel = FakeChannel()
    client = asyncio.run(adapter.connect_and_listen(channel=channel, on_pcm_frame=on_frame, on_decode_error=on_decode_error))

    client.sink.write(None, BrokenData())
    assert frames == []
    assert errors
    assert adapter.counters.opus_corrupted_total == 1
    assert adapter.counters.corrupted_stream_count == 0
    assert adapter.counters.invalid_argument_count == 1


def test_valid_frame_reaches_plugin_callback_and_disconnect() -> None:
    FakeChannel, _PacketRouter, _PacketDecoder, _Decoder = _install_fake_voice_recv()
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


def test_listener_attach_is_idempotent() -> None:
    FakeChannel, _PacketRouter, _PacketDecoder, _Decoder = _install_fake_voice_recv()
    adapter = VoiceReceiveAdapter()
    channel = FakeChannel()
    client = asyncio.run(adapter.connect_and_listen(channel=channel, on_pcm_frame=lambda *_a: None, on_decode_error=lambda *_a: None))

    voice_recv_module = sys.modules["discord.ext.voice_recv"]
    attached = adapter.attach_listener(
        voice_client=client,
        voice_recv_module=voice_recv_module,
        on_pcm_frame=lambda *_a: None,
        on_decode_error=lambda *_a: None,
    )

    assert attached is False


def test_crypto_and_opus_errors_are_tracked_separately() -> None:
    FakeChannel, _PacketRouter, _PacketDecoder, _Decoder = _install_fake_voice_recv()
    adapter = VoiceReceiveAdapter()

    channel = FakeChannel()
    client = asyncio.run(adapter.connect_and_listen(channel=channel, on_pcm_frame=lambda *_a: None, on_decode_error=lambda *_a: None))

    class BrokenData:
        pass

    def on_frame(_user: Any, _data: Any) -> None:
        raise DummyOpusError("corrupted stream")

    voice_recv_module = sys.modules["discord.ext.voice_recv"]
    adapter.attach_listener(
        voice_client=types.SimpleNamespace(listen=lambda sink: client.listen(sink), is_connected=lambda: True),
        voice_recv_module=voice_recv_module,
        on_pcm_frame=on_frame,
        on_decode_error=lambda *_a: None,
    )
    client.sink.write(None, BrokenData())

    adapter._vendor._register_decode_error(Exception("CryptoError decoding packet data"))
    counters = adapter.counters
    assert counters.crypto_decode_errors >= 1
    assert counters.opus_corrupted_total >= 1


def test_runtime_introspection_and_hook_installation_finds_multiple_methods() -> None:
    _install_fake_voice_recv()
    adapter = VoiceReceiveAdapter()

    hooks = adapter._vendor.install_decode_guards(on_decode_error=lambda *_a: None)

    assert hooks == 4


def test_do_run_is_fallback_only_when_packet_level_hooks_exist() -> None:
    _install_fake_voice_recv()
    adapter = VoiceReceiveAdapter()

    adapter._vendor.install_decode_guards(on_decode_error=lambda *_a: None)

    patched = adapter._vendor._patched_sources
    assert "PacketRouter._do_run" in patched
    assert "PacketDecoder.pop_data" in patched
    assert "PacketDecoder._process_packet" in patched
    assert "PacketDecoder._decode_packet" in patched
    assert "Decoder.decode" not in patched


def test_packet_level_decode_error_is_handled_without_fallback() -> None:
    FakeChannel, _PacketRouter, PacketDecoder, _Decoder = _install_fake_voice_recv(router_exc=DummyOpusError("corrupted stream"))
    adapter = VoiceReceiveAdapter()
    errors: list[str] = []

    def on_decode_error(exc: Exception, context: DecodeErrorContext) -> None:
        errors.append(f"{context.source}:{exc}")

    channel = FakeChannel()
    asyncio.run(adapter.connect_and_listen(channel=channel, on_pcm_frame=lambda *_a: None, on_decode_error=on_decode_error))

    packet_decoder = PacketDecoder()
    assert packet_decoder.pop_data(b"x") is None

    assert any(error.startswith("PacketDecoder.pop_data:") for error in errors)


def test_crypto_and_opus_errors_are_classified_in_vendor_counters() -> None:
    _install_fake_voice_recv()
    adapter = VoiceReceiveAdapter()

    vendor = adapter._vendor
    vendor._register_decode_error(Exception("CryptoError decoding packet data"))
    vendor._register_decode_error(Exception("OpusError('corrupted stream')"))

    counters = adapter.counters
    assert counters.crypto_decode_errors == 1
    assert counters.opus_corrupted_total == 1
    assert counters.corrupted_stream_count == 1


def test_stack_report_accepts_supported_prerelease_and_davey_floor(monkeypatch: Any) -> None:
    _install_fake_voice_recv()
    adapter = VoiceReceiveAdapter()

    import discord
    monkeypatch.setattr(discord, "__version__", "2.7.1")
    sys.modules["discord.ext.voice_recv"].__version__ = "0.5.2a"
    sys.modules["davey"] = types.SimpleNamespace(__version__="0.1.4")

    report = adapter.get_voice_stack_report()

    assert report.available is True
    assert report.compatible is True
    assert report.reasons == []


def test_decode_context_extracts_payload_user_and_ssrc() -> None:
    _install_fake_voice_recv()
    adapter = VoiceReceiveAdapter()

    class BrokenPacket:
        def __init__(self) -> None:
            self.user_id = 44
            self.ssrc = 55
            self.payload = b"xyz"

    context = adapter._vendor._extract_decode_error_context(source="test.pop_data", args=(BrokenPacket(),), kwargs={})

    assert context.user_id == 44
    assert context.ssrc == 55
    assert context.payload_size == 3


def test_voice_recv_runtime_alias_is_supported() -> None:
    incompatible, detail = VoiceReceiveAdapter._voice_recv_incompatible("0.5.2a")

    assert incompatible is False
    assert detail is None


def test_voice_recv_really_lower_version_is_rejected() -> None:
    incompatible, detail = VoiceReceiveAdapter._voice_recv_incompatible("0.5.1")

    assert incompatible is True
    assert detail == "0.5.1 not in supported range <0.5.3,>=0.5.2a0"


def test_sink_boundary_reports_pcm_expected_by_default() -> None:
    FakeChannel, _PacketRouter, _PacketDecoder, _Decoder = _install_fake_voice_recv()
    adapter = VoiceReceiveAdapter()

    channel = FakeChannel()
    asyncio.run(adapter.connect_and_listen(channel=channel, on_pcm_frame=lambda *_a: None, on_decode_error=lambda *_a: None))

    assert adapter.sink_wants_opus() is False
    info = adapter.sink_debug_info()
    assert info["sink_present"] is True
    assert info["sink_wants_opus"] is False


def test_decode_error_context_includes_packet_type_and_decoder_id() -> None:
    FakeChannel, _PacketRouter, PacketDecoder, _Decoder = _install_fake_voice_recv(router_exc=DummyOpusError("corrupted stream"))
    adapter = VoiceReceiveAdapter()
    contexts: list[DecodeErrorContext] = []

    def on_decode_error(_exc: Exception, context: DecodeErrorContext) -> None:
        contexts.append(context)

    channel = FakeChannel()
    asyncio.run(adapter.connect_and_listen(channel=channel, on_pcm_frame=lambda *_a: None, on_decode_error=on_decode_error))

    decoder = PacketDecoder()
    decoder.pop_data(b"packet")

    assert contexts
    context = contexts[-1]
    assert context.packet_type in {"bytes", "bytearray"}
    assert context.decoder_instance_id is not None


def test_decode_guard_preserves_decode_call_arguments_and_binding() -> None:
    _install_fake_voice_recv()
    adapter = VoiceReceiveAdapter()
    adapter._vendor.install_decode_guards(on_decode_error=lambda *_a: None)

    PacketDecoder = sys.modules["discord.ext.voice_recv.opus"].PacketDecoder

    calls: list[tuple[int, bytes]] = []
    original = PacketDecoder.pop_data

    def traced(self: Any, packet: bytes) -> bytes:
        calls.append((id(self), packet))
        return original(self, packet)

    PacketDecoder.pop_data = traced
    adapter._vendor.install_decode_guards(on_decode_error=lambda *_a: None)

    decoder = PacketDecoder()
    payload = b"\x90\xab\x01\x02"
    out = decoder.pop_data(payload)

    assert out == b"ok"
    assert calls == [(id(decoder), payload)]


def test_decode_context_detects_rtp_like_payload_at_decoder_boundary() -> None:
    _install_fake_voice_recv()
    adapter = VoiceReceiveAdapter()

    # 0x80 starts RTP version-2 header in the first two bits.
    payload = bytes.fromhex("807800010000000100000002") + b"payload"
    context = adapter._vendor._extract_decode_error_context(source="Decoder.decode", args=(object(), payload), kwargs={})

    assert context.packet_origin == "decoder.decode.payload"
    assert context.payload_size == len(payload)
    assert context.payload_preview_hex == payload[:8].hex()
    assert context.payload_looks_like_rtp is True


def test_packet_decoder_guard_does_not_mutate_packet_argument() -> None:
    _install_fake_voice_recv()
    adapter = VoiceReceiveAdapter()
    adapter._vendor.install_decode_guards(on_decode_error=lambda *_a: None)

    PacketDecoder = sys.modules["discord.ext.voice_recv.opus"].PacketDecoder
    packet_decoder = PacketDecoder()
    payload = bytearray(b"abc")
    before = bytes(payload)

    assert packet_decoder.pop_data(payload) == b"ok"
    assert bytes(payload) == before


def test_decode_guard_preserves_decoder_signature_metadata() -> None:
    _install_fake_voice_recv()
    PacketDecoder = sys.modules["discord.ext.voice_recv.opus"].PacketDecoder
    original_sig = inspect.signature(PacketDecoder.pop_data)

    adapter = VoiceReceiveAdapter()
    adapter._vendor.install_decode_guards(on_decode_error=lambda *_a: None)

    wrapped_sig = inspect.signature(PacketDecoder.pop_data)
    assert wrapped_sig == original_sig



def test_packet_decoder_guard_strips_rtp_header_before_decode() -> None:
    _install_fake_voice_recv()
    adapter = VoiceReceiveAdapter()

    PacketDecoder = sys.modules["discord.ext.voice_recv.opus"].PacketDecoder

    seen_payloads: list[bytes] = []
    original_decode = PacketDecoder.pop_data

    def traced(self: Any, packet: bytes) -> bytes:
        seen_payloads.append(packet)
        return original_decode(self, packet)

    PacketDecoder.pop_data = traced
    adapter._vendor.install_decode_guards(on_decode_error=lambda *_a: None)

    decoder = PacketDecoder()
    opus_payload = bytes.fromhex("f8fffe006f707573")
    rtp_header = bytes.fromhex("807812340000000100000002")
    rtp_packet = rtp_header + opus_payload

    assert decoder.pop_data(rtp_packet) == b"ok"
    assert seen_payloads == [opus_payload]


def test_decoder_decode_is_not_monkeypatched() -> None:
    _install_fake_voice_recv()
    Decoder = sys.modules["discord.ext.voice_recv.opus"].Decoder
    original_decode = Decoder.decode

    adapter = VoiceReceiveAdapter()
    adapter._vendor.install_decode_guards(on_decode_error=lambda *_a: None)

    assert Decoder.decode is original_decode


def test_rtp_payload_is_detected_upstream_at_packet_decoder_stage() -> None:
    _install_fake_voice_recv()
    adapter = VoiceReceiveAdapter()

    payload = bytes.fromhex("807812340000000100000002") + b"abc"
    context = adapter._vendor._extract_decode_error_context(source="PacketDecoder._process_packet", args=(object(), payload), kwargs={})

    assert context.packet_origin == "packet_decoder._process_packet"
    assert context.payload_looks_like_rtp is True


def test_decode_context_propagates_nested_session_guild_channel() -> None:
    _install_fake_voice_recv()
    adapter = VoiceReceiveAdapter()

    packet = types.SimpleNamespace(
        session_id="sess-1",
        guild=types.SimpleNamespace(id=10),
        channel=types.SimpleNamespace(id=20),
        ssrc=30,
        user_id=40,
        payload=b"abc",
    )
    wrapped = types.SimpleNamespace(packet=packet)

    context = adapter._vendor._extract_decode_error_context(
        source="PacketDecoder._process_packet",
        args=(object(), wrapped),
        kwargs={},
    )

    assert context.session_id == "sess-1"
    assert context.guild_id == 10
    assert context.channel_id == 20
    assert context.ssrc == 30
    assert context.user_id == 40
