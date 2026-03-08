import asyncio
import builtins
import importlib.machinery
import sys
import types
from typing import Any

import discord

sys.modules.setdefault("aiosqlite", types.SimpleNamespace(IntegrityError=Exception))

from app.core.service_registry import ServiceRegistry
from app.plugins import voice_ingest


class _DummyTask:
    def add_done_callback(self, _cb: Any) -> None:
        return


class _FakeBot:
    def __init__(self) -> None:
        self.user = types.SimpleNamespace(id=999)
        self._listeners: dict[str, list[Any]] = {}
        self.loop: Any = None

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
    module.__version__ = "test"
    module.__spec__ = importlib.machinery.ModuleSpec("discord.ext.voice_recv", loader=None)

    class VoiceRecvClient:
        pass

    class AudioSink:
        pass

    class BasicSink:
        def __init__(self, cb: Any) -> None:
            self.cb = cb

        def write(self, user: Any, data: Any) -> None:
            self.cb(user, data)

    module.VoiceRecvClient = VoiceRecvClient
    module.AudioSink = AudioSink
    module.BasicSink = BasicSink

    router_module = types.ModuleType("discord.ext.voice_recv.router")
    router_module.__spec__ = importlib.machinery.ModuleSpec("discord.ext.voice_recv.router", loader=None)

    class PacketRouter:
        def _do_run(self) -> None:
            return

    router_module.PacketRouter = PacketRouter

    sys.modules["discord.ext.voice_recv"] = module
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

    async def _run_ready() -> None:
        bot.loop = asyncio.get_running_loop()
        await on_ready()

    asyncio.run(_run_ready())
    return registry.get("voice_ingest")


def test_join_does_not_listen_when_client_never_ready(monkeypatch: Any) -> None:
    _install_fake_voice_recv()
    monkeypatch.setenv("VOICE_INGEST_ENABLED", "true")
    monkeypatch.setattr(voice_ingest.asyncio, "create_task", lambda _coro: _DummyTask())

    registry, bot, db = _build_registry()
    controller = _bootstrap_controller(registry, bot)

    client = _FakeVoiceClient(connected=False)
    guild = types.SimpleNamespace(id=42, voice_client=None)
    channel = _FakeChannel(guild, 777, client)

    try:
        asyncio.run(controller.join(channel))
    except discord.ClientException:
        pass

    assert client.listen_calls == 1
    assert db.started == 1
    assert db.ended == 1


def test_join_cleanup_when_listen_not_connected_exception(monkeypatch: Any) -> None:
    _install_fake_voice_recv()
    monkeypatch.setenv("VOICE_INGEST_ENABLED", "true")
    monkeypatch.setattr(voice_ingest.asyncio, "create_task", lambda _coro: _DummyTask())

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
    assert client.disconnect_calls == 0
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
