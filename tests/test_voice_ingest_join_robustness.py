import asyncio
import builtins
import importlib.machinery
import sys
import types
from typing import Any

import discord

from app.core.service_registry import ServiceRegistry
from app.plugins import voice_ingest


class _DummyTask:
    def add_done_callback(self, _cb: Any) -> None:
        return


class _FakeBot:
    def __init__(self) -> None:
        self.user = types.SimpleNamespace(id=999)
        self._listeners: dict[str, list[Any]] = {}

    def add_listener(self, cb: Any, name: str) -> None:
        self._listeners.setdefault(name, []).append(cb)

    def get_listener(self, name: str) -> Any:
        return self._listeners[name][0]

    def get_channel(self, _channel_id: int) -> None:
        return None


class _FakeDatabase:
    def __init__(self) -> None:
        self.started = 0
        self.ended = 0

    async def get_setting(self, _key: str) -> None:
        return None

    async def get_active_voice_session(self, _guild_id: str, _channel_id: str) -> None:
        return None

    async def start_voice_session(self, **_kwargs: Any) -> None:
        self.started += 1

    async def end_voice_session(self, *_args: Any, **_kwargs: Any) -> None:
        self.ended += 1

    async def close_open_voice_sessions(self, **_kwargs: Any) -> int:
        return 0

    async def fetchone(self, *_args: Any, **_kwargs: Any) -> dict[str, int]:
        return {"c": 0}


class _FakeIngest:
    async def emit(self, _event: Any) -> None:
        return


class _FakeStt:
    async def transcribe(self, _path: str) -> Any:
        return types.SimpleNamespace(text="")


class _FakeVoiceClient:
    def __init__(self, *, connected: bool, listen_exc: Exception | None = None) -> None:
        self._connected = connected
        self.channel = None
        self.listen_calls = 0
        self.disconnect_calls = 0
        self.listen_exc = listen_exc

    def is_connected(self) -> bool:
        return self._connected

    def listen(self, _sink: Any) -> None:
        self.listen_calls += 1
        if self.listen_exc is not None:
            raise self.listen_exc

    async def disconnect(self, *, force: bool) -> None:
        assert force is True
        self.disconnect_calls += 1
        self._connected = False


class _FakeChannel:
    def __init__(self, guild: Any, channel_id: int, voice_client: _FakeVoiceClient) -> None:
        self.guild = guild
        self.id = channel_id
        self._voice_client = voice_client

    async def connect(self, **_kwargs: Any) -> _FakeVoiceClient:
        self._voice_client.channel = self
        return self._voice_client


def _install_fake_voice_recv() -> None:
    module = types.ModuleType("discord.ext.voice_recv")
    opus_module = types.ModuleType("discord.ext.voice_recv.opus")
    router_module = types.ModuleType("discord.ext.voice_recv.router")

    class VoiceRecvClient:
        pass

    class AudioSink:
        pass

    class BasicSink:
        def __init__(self, cb: Any) -> None:
            self.cb = cb

    class OpusDecoder:
        def pop_data(self) -> bytes:
            return b"ok"

        def _decode_packet(self, _packet: Any) -> bytes:
            return b"ok"

    class PacketRouter:
        def _do_run(self) -> None:
            return

    module.VoiceRecvClient = VoiceRecvClient
    module.AudioSink = AudioSink
    module.BasicSink = BasicSink
    module.opus = opus_module
    module.router = router_module
    module.__version__ = "test"
    module.__spec__ = importlib.machinery.ModuleSpec("discord.ext.voice_recv", loader=None)
    opus_module.OpusDecoder = OpusDecoder
    router_module.PacketRouter = PacketRouter
    opus_module.__spec__ = importlib.machinery.ModuleSpec("discord.ext.voice_recv.opus", loader=None)
    router_module.__spec__ = importlib.machinery.ModuleSpec("discord.ext.voice_recv.router", loader=None)
    sys.modules["discord.ext.voice_recv"] = module
    sys.modules["discord.ext.voice_recv.opus"] = opus_module
    sys.modules["discord.ext.voice_recv.router"] = router_module


def _build_registry() -> tuple[ServiceRegistry, _FakeBot, _FakeDatabase]:
    registry = ServiceRegistry()
    bot = _FakeBot()
    db = _FakeDatabase()
    registry.register("bot", bot)
    registry.register("database", db)
    registry.register("ingest", _FakeIngest())
    registry.register("stt.local", _FakeStt())
    registry.register("config", types.SimpleNamespace(guild_id=0))
    return registry, bot, db


def _bootstrap_controller(registry: ServiceRegistry, bot: _FakeBot) -> Any:
    voice_ingest.setup(registry)
    on_ready = bot.get_listener("on_ready")
    asyncio.run(on_ready())
    return registry.get("voice_ingest")


def test_join_does_not_listen_when_client_never_ready(monkeypatch: Any) -> None:
    _install_fake_voice_recv()
    monkeypatch.setenv("VOICE_INGEST_ENABLED", "true")
    monkeypatch.setattr(voice_ingest.asyncio, "create_task", lambda _coro: _DummyTask())
    monkeypatch.setattr(voice_ingest.importlib.util, "find_spec", lambda name: object() if name == "discord.ext.voice_recv" else None)

    registry, bot, db = _build_registry()
    controller = _bootstrap_controller(registry, bot)

    client = _FakeVoiceClient(connected=False)
    guild = types.SimpleNamespace(id=42, voice_client=None)
    channel = _FakeChannel(guild, 777, client)

    try:
        asyncio.run(controller.join(channel))
    except discord.ClientException:
        pass

    assert client.listen_calls == 0
    assert db.started == 0
    assert db.ended == 0


def test_join_cleanup_when_listen_not_connected_exception(monkeypatch: Any) -> None:
    _install_fake_voice_recv()
    monkeypatch.setenv("VOICE_INGEST_ENABLED", "true")
    monkeypatch.setattr(voice_ingest.asyncio, "create_task", lambda _coro: _DummyTask())
    monkeypatch.setattr(voice_ingest.importlib.util, "find_spec", lambda name: object() if name == "discord.ext.voice_recv" else None)

    registry, bot, db = _build_registry()
    controller = _bootstrap_controller(registry, bot)

    client = _FakeVoiceClient(connected=True, listen_exc=discord.ClientException("Not connected to voice."))
    guild = types.SimpleNamespace(id=99, voice_client=None)
    channel = _FakeChannel(guild, 888, client)

    try:
        asyncio.run(controller.join(channel))
    except discord.ClientException:
        pass

    assert client.listen_calls == 1
    assert client.disconnect_calls == 1
    assert db.started == 1
    assert db.ended == 1


def test_voice_stack_logging_does_not_crash_if_optional_modules_missing(monkeypatch: Any) -> None:
    monkeypatch.setattr(voice_ingest.asyncio, "create_task", lambda _coro: _DummyTask())

    original_import = builtins.__import__

    def _fake_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        if name == "davey":
            raise ImportError("davey missing")
        if name == "discord.ext" and fromlist and "voice_recv" in fromlist:
            raise ImportError("voice_recv missing")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    registry, bot, _db = _build_registry()
    voice_ingest.setup(registry)
    on_ready = bot.get_listener("on_ready")
    asyncio.run(on_ready())
    assert registry.has("voice_ingest") is True


def test_opus_guards_protect_pop_data_and_router_do_run(monkeypatch: Any, caplog: Any) -> None:
    _install_fake_voice_recv()
    monkeypatch.setenv("VOICE_INGEST_ENABLED", "true")
    monkeypatch.setattr(voice_ingest.asyncio, "create_task", lambda _coro: _DummyTask())
    monkeypatch.setattr(voice_ingest.importlib.util, "find_spec", lambda name: object() if name == "discord.ext.voice_recv" else None)

    class DummyOpusError(Exception):
        pass

    fake_discord_opus = types.ModuleType("discord.opus")
    fake_discord_opus.OpusError = DummyOpusError
    monkeypatch.setitem(sys.modules, "discord.opus", fake_discord_opus)

    from discord.ext.voice_recv import opus as vr_opus  # type: ignore
    from discord.ext.voice_recv import router as vr_router  # type: ignore

    def _broken_pop_data(self: Any) -> bytes:
        raise DummyOpusError("corrupted stream")

    def _broken_do_run(self: Any) -> None:
        raise DummyOpusError("invalid argument")

    monkeypatch.setattr(vr_opus.OpusDecoder, "pop_data", _broken_pop_data)
    monkeypatch.setattr(vr_router.PacketRouter, "_do_run", _broken_do_run)

    registry, bot, _db = _build_registry()
    controller = _bootstrap_controller(registry, bot)

    client = _FakeVoiceClient(connected=True)
    guild = types.SimpleNamespace(id=77, voice_client=None)
    channel = _FakeChannel(guild, 987, client)

    with caplog.at_level("INFO"):
        asyncio.run(controller.join(channel))

    decoder = vr_opus.OpusDecoder()
    assert decoder.pop_data() is None
    router = vr_router.PacketRouter()
    assert router._do_run() is None
    assert "Installed OpusError guard on voice_recv.OpusDecoder.pop_data module=discord.ext.voice_recv.opus" in caplog.text
    assert "Installed OpusError guard on voice_recv.PacketRouter._do_run module=discord.ext.voice_recv.router" in caplog.text
    assert "original_id=" in caplog.text
    assert "wrapped_id=" in caplog.text
    assert "Opus decode failure source=voice_recv.OpusDecoder.pop_data" in caplog.text


def test_opus_guard_logs_import_failure_instead_of_silent_skip(monkeypatch: Any, caplog: Any) -> None:
    monkeypatch.setenv("VOICE_INGEST_ENABLED", "true")
    monkeypatch.setattr(voice_ingest.asyncio, "create_task", lambda _coro: _DummyTask())
    monkeypatch.setattr(voice_ingest.importlib.util, "find_spec", lambda name: object() if name == "discord.ext.voice_recv" else None)

    original_import_module = voice_ingest.importlib.import_module

    def _fake_import_module(name: str) -> Any:
        if name == "discord.ext.voice_recv.opus":
            raise ImportError("opus module missing")
        return original_import_module(name)

    monkeypatch.setattr(voice_ingest.importlib, "import_module", _fake_import_module)

    registry, bot, _db = _build_registry()
    controller = _bootstrap_controller(registry, bot)

    client = _FakeVoiceClient(connected=True)
    guild = types.SimpleNamespace(id=71, voice_client=None)
    channel = _FakeChannel(guild, 700, client)

    with caplog.at_level("WARNING"):
        asyncio.run(controller.join(channel))

    assert "Unable to install OpusError guard: import failed module=discord.ext.voice_recv.opus" in caplog.text


def test_live_guard_patches_runtime_objects(monkeypatch: Any, caplog: Any) -> None:
    _install_fake_voice_recv()
    monkeypatch.setenv("VOICE_INGEST_ENABLED", "true")
    monkeypatch.setattr(voice_ingest.asyncio, "create_task", lambda _coro: _DummyTask())
    monkeypatch.setattr(voice_ingest.importlib.util, "find_spec", lambda name: object() if name == "discord.ext.voice_recv" else None)

    class DummyOpusError(Exception):
        pass

    fake_discord_opus = types.ModuleType("discord.opus")
    fake_discord_opus.OpusError = DummyOpusError
    monkeypatch.setitem(sys.modules, "discord.opus", fake_discord_opus)

    class _LiveDecoder:
        def pop_data(self) -> bytes:
            raise DummyOpusError("corrupted stream")

    class _RuntimeReceiver:
        def __init__(self) -> None:
            self.decoder = _LiveDecoder()

    class _VoiceClientWithRuntime(_FakeVoiceClient):
        def __init__(self) -> None:
            super().__init__(connected=True)
            self.receiver = _RuntimeReceiver()

    registry, bot, _db = _build_registry()
    controller = _bootstrap_controller(registry, bot)

    client = _VoiceClientWithRuntime()
    guild = types.SimpleNamespace(id=88, voice_client=None)
    channel = _FakeChannel(guild, 900, client)

    with caplog.at_level("INFO"):
        asyncio.run(controller.join(channel))

    # no fake PCM fallback: corrupted frame is dropped as None
    assert client.receiver.decoder.pop_data() is None
    assert "Installed OpusError guard on live live._LiveDecoder.pop_data" in caplog.text
