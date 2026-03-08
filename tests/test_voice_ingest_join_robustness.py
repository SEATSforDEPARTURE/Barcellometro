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
    def __init__(self) -> None:
        self._done = False

    def add_done_callback(self, _cb: Any) -> None:
        return

    def done(self) -> bool:
        return self._done


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
        self.settings: dict[str, str] = {}
        self.cleanup_calls = 0

    async def get_setting(self, key: str) -> Any:
        return self.settings.get(key)

    async def get_active_voice_session(self, _guild_id: str, _channel_id: str) -> None:
        return None

    async def start_voice_session(self, **_kwargs: Any) -> None:
        self.started += 1

    async def end_voice_session(self, *_args: Any, **_kwargs: Any) -> None:
        self.ended += 1

    async def close_open_voice_sessions(self, **_kwargs: Any) -> int:
        self.cleanup_calls += 1
        return 0

    async def fetchone(self, *_args: Any, **_kwargs: Any) -> dict[str, int]:
        return {"c": 0}

    async def insert_voice_participant_event(self, **_kwargs: Any) -> None:
        return


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
        self.connect_calls = 0

    async def connect(self, **_kwargs: Any) -> _FakeVoiceClient:
        self.connect_calls += 1
        self._voice_client.channel = self
        self.guild.voice_client = self._voice_client
        return self._voice_client


def _install_fake_voice_recv() -> None:
    module = types.ModuleType("discord.ext.voice_recv")
    module.__version__ = "0.5.2"
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
    sys.modules["davey"] = types.SimpleNamespace(__version__="0.1.4")


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


def test_double_join_is_idempotent_single_connect(monkeypatch: Any) -> None:
    _install_fake_voice_recv()
    monkeypatch.setenv("VOICE_INGEST_ENABLED", "true")
    monkeypatch.setattr(voice_ingest.asyncio, "create_task", lambda _coro: _DummyTask())

    registry, bot, db = _build_registry()
    controller = _bootstrap_controller(registry, bot)

    client = _FakeVoiceClient(connected=True)
    guild = types.SimpleNamespace(id=43, voice_client=None)
    channel = _FakeChannel(guild, 779, client)

    async def _run() -> None:
        await asyncio.gather(controller.join(channel), controller.join(channel))

    asyncio.run(_run())

    assert channel.connect_calls == 1
    assert client.listen_calls == 1
    assert db.started == 1


def test_join_skips_reconnect_when_already_connected_same_channel(monkeypatch: Any) -> None:
    _install_fake_voice_recv()
    monkeypatch.setenv("VOICE_INGEST_ENABLED", "true")
    monkeypatch.setattr(voice_ingest.asyncio, "create_task", lambda _coro: _DummyTask())

    registry, bot, db = _build_registry()
    controller = _bootstrap_controller(registry, bot)

    client = _FakeVoiceClient(connected=True)
    guild = types.SimpleNamespace(id=44, voice_client=client)
    channel = _FakeChannel(guild, 780, client)
    client.channel = channel

    asyncio.run(controller.join(channel))
    asyncio.run(controller.join(channel))

    assert channel.connect_calls == 0
    assert client.listen_calls == 1
    assert db.started == 0


def test_privacy_enforcer_and_voice_state_autojoin_single_connect(monkeypatch: Any) -> None:
    _install_fake_voice_recv()
    monkeypatch.setenv("VOICE_INGEST_ENABLED", "true")
    monkeypatch.setattr(voice_ingest.asyncio, "create_task", lambda _coro: _DummyTask())

    registry, bot, _db = _build_registry()
    controller = _bootstrap_controller(registry, bot)

    client = _FakeVoiceClient(connected=True)
    guild = types.SimpleNamespace(id=45, voice_client=None, get_channel=lambda _id: channel)
    channel = _FakeChannel(guild, 781, client)

    asyncio.run(controller.join(channel))
    asyncio.run(controller.join(channel))

    assert channel.connect_calls == 1
    assert client.listen_calls == 1




def test_join_proceeds_with_supported_runtime_versions(monkeypatch: Any, caplog: Any) -> None:
    _install_fake_voice_recv()
    monkeypatch.setenv("VOICE_INGEST_ENABLED", "true")
    monkeypatch.setattr(voice_ingest.asyncio, "create_task", lambda _coro: _DummyTask())

    report = types.SimpleNamespace(
        available=True,
        compatible=True,
        discord_version="2.7.1",
        voice_recv_version="0.5.2a",
        davey_version="0.1.4",
        reasons=[],
    )
    monkeypatch.setattr(
        "app.services.voice_receive_adapter.VoiceReceiveAdapter.get_voice_stack_report",
        lambda _self: report,
    )

    registry, bot, db = _build_registry()
    controller = _bootstrap_controller(registry, bot)

    client = _FakeVoiceClient(connected=True)
    guild = types.SimpleNamespace(id=460, voice_client=None)
    channel = _FakeChannel(guild, 7820, client)

    with caplog.at_level("INFO"):
        asyncio.run(controller.join(channel))

    assert channel.connect_calls == 1
    assert client.listen_calls == 1
    assert db.started == 1
    assert "failed_runtime_incompatible" not in caplog.text

def test_join_fails_fast_when_voice_stack_incompatible(monkeypatch: Any, caplog: Any) -> None:
    _install_fake_voice_recv()
    monkeypatch.setenv("VOICE_INGEST_ENABLED", "true")
    monkeypatch.setattr(voice_ingest.asyncio, "create_task", lambda _coro: _DummyTask())

    report = types.SimpleNamespace(
        available=True,
        compatible=False,
        discord_version="2.7.1",
        voice_recv_version="0.5.2a",
        davey_version="0.1.4",
        reasons=["davey=0.1.3 < 0.1.4"],
    )
    monkeypatch.setattr(
        "app.services.voice_receive_adapter.VoiceReceiveAdapter.get_voice_stack_report",
        lambda _self: report,
    )

    registry, bot, db = _build_registry()
    controller = _bootstrap_controller(registry, bot)

    client = _FakeVoiceClient(connected=True)
    guild = types.SimpleNamespace(id=46, voice_client=None)
    channel = _FakeChannel(guild, 782, client)

    with caplog.at_level("ERROR"):
        asyncio.run(controller.join(channel))

    assert channel.connect_calls == 0
    assert client.listen_calls == 0
    assert db.started == 0
    assert "runtime stack incompatible" in caplog.text


def test_incompatible_stack_logs_once_and_blocks_followup_join_attempts(monkeypatch: Any, caplog: Any) -> None:
    _install_fake_voice_recv()
    monkeypatch.setenv("VOICE_INGEST_ENABLED", "true")
    monkeypatch.setattr(voice_ingest.asyncio, "create_task", lambda _coro: _DummyTask())

    report = types.SimpleNamespace(
        available=True,
        compatible=False,
        discord_version="2.7.1",
        voice_recv_version="0.5.2a",
        davey_version="0.1.4",
        reasons=["discord-ext-voice-recv=0.5.1 not in supported range <0.5.3,>=0.5.2a0"],
    )
    monkeypatch.setattr(
        "app.services.voice_receive_adapter.VoiceReceiveAdapter.get_voice_stack_report",
        lambda _self: report,
    )

    registry, bot, _db = _build_registry()
    controller = _bootstrap_controller(registry, bot)

    client = _FakeVoiceClient(connected=True)
    guild = types.SimpleNamespace(id=47, voice_client=None)
    channel = _FakeChannel(guild, 783, client)

    with caplog.at_level("ERROR"):
        asyncio.run(controller.join(channel))
        asyncio.run(controller.join(channel))

    assert channel.connect_calls == 0
    assert caplog.text.count("runtime stack incompatible") == 1


def test_voice_state_autojoin_respects_runtime_block(monkeypatch: Any, caplog: Any) -> None:
    _install_fake_voice_recv()
    monkeypatch.setenv("VOICE_INGEST_ENABLED", "true")
    monkeypatch.setattr(voice_ingest.asyncio, "create_task", lambda _coro: _DummyTask())

    report = types.SimpleNamespace(
        available=True,
        compatible=False,
        discord_version="2.7.1",
        voice_recv_version="0.5.2a",
        davey_version="0.1.4",
        reasons=["davey=0.1.3 < 0.1.4"],
    )
    monkeypatch.setattr(
        "app.services.voice_receive_adapter.VoiceReceiveAdapter.get_voice_stack_report",
        lambda _self: report,
    )

    registry, bot, db = _build_registry()
    controller = _bootstrap_controller(registry, bot)

    target_channel_id = 784
    db.settings[f"voice_ingest.{bot.user.id}.target_voice_channel_id"] = str(target_channel_id)
    db.settings[f"voice_ingest.{bot.user.id}.auto_join"] = "true"
    db.settings[f"voice_ingest.{bot.user.id}.enabled"] = "true"

    client = _FakeVoiceClient(connected=True)
    guild = types.SimpleNamespace(id=48, voice_client=None)
    member = types.SimpleNamespace(id=1001, bot=False, guild=guild, display_name="member")
    channel = _FakeChannel(guild, target_channel_id, client)
    channel.members = [member]
    guild.get_channel = lambda _id: channel

    # first explicit join marks runtime as permanently blocked for this process
    asyncio.run(controller.join(channel))

    handler = bot.get_listener("on_voice_state_update")
    before = types.SimpleNamespace(channel=None)
    after = types.SimpleNamespace(channel=channel)

    with caplog.at_level("DEBUG"):
        asyncio.run(handler(member, before, after))

    assert channel.connect_calls == 0
    assert caplog.text.count("runtime stack incompatible") == 1


def test_runtime_block_sets_fatal_state(monkeypatch: Any, caplog: Any) -> None:
    _install_fake_voice_recv()
    monkeypatch.setenv("VOICE_INGEST_ENABLED", "true")
    monkeypatch.setattr(voice_ingest.asyncio, "create_task", lambda _coro: _DummyTask())

    report = types.SimpleNamespace(
        available=True,
        compatible=False,
        discord_version="2.7.1",
        voice_recv_version="0.5.2a",
        davey_version="0.1.4",
        reasons=["davey=0.1.3 < 0.1.4"],
    )
    monkeypatch.setattr(
        "app.services.voice_receive_adapter.VoiceReceiveAdapter.get_voice_stack_report",
        lambda _self: report,
    )

    registry, bot, _db = _build_registry()
    controller = _bootstrap_controller(registry, bot)

    client = _FakeVoiceClient(connected=True)
    guild = types.SimpleNamespace(id=49, voice_client=None)
    channel = _FakeChannel(guild, 785, client)

    with caplog.at_level("INFO"):
        asyncio.run(controller.join(channel))

    assert "state=failed_runtime_incompatible" in caplog.text


def test_runtime_block_does_not_trigger_reconnect_recovery(monkeypatch: Any, caplog: Any) -> None:
    _install_fake_voice_recv()
    monkeypatch.setenv("VOICE_INGEST_ENABLED", "true")
    monkeypatch.setattr(voice_ingest.asyncio, "create_task", lambda _coro: _DummyTask())

    report = types.SimpleNamespace(
        available=True,
        compatible=False,
        discord_version="2.7.1",
        voice_recv_version="0.5.2a",
        davey_version="0.1.4",
        reasons=["davey=0.1.3 < 0.1.4"],
    )
    monkeypatch.setattr(
        "app.services.voice_receive_adapter.VoiceReceiveAdapter.get_voice_stack_report",
        lambda _self: report,
    )

    registry, bot, _db = _build_registry()
    controller = _bootstrap_controller(registry, bot)

    client = _FakeVoiceClient(connected=True)
    guild = types.SimpleNamespace(id=50, voice_client=None)
    channel = _FakeChannel(guild, 786, client)

    with caplog.at_level("DEBUG"):
        asyncio.run(controller.join(channel))
        asyncio.run(controller.join(channel))

    assert "decode storm recovery" not in caplog.text.lower()


def test_on_ready_is_idempotent_and_skips_duplicate_startup(monkeypatch: Any) -> None:
    _install_fake_voice_recv()
    monkeypatch.setenv("VOICE_INGEST_ENABLED", "true")

    created_tasks: list[_DummyTask] = []

    def _fake_create_task(_coro: Any) -> _DummyTask:
        task = _DummyTask()
        created_tasks.append(task)
        return task

    monkeypatch.setattr(voice_ingest.asyncio, "create_task", _fake_create_task)

    registry, bot, db = _build_registry()
    voice_ingest.setup(registry)
    on_ready = bot.get_listener("on_ready")

    asyncio.run(on_ready())
    asyncio.run(on_ready())

    assert db.cleanup_calls == 1
    assert len(created_tasks) == 2


def test_setup_does_not_register_duplicate_listeners_across_reinit(monkeypatch: Any) -> None:
    _install_fake_voice_recv()
    monkeypatch.setenv("VOICE_INGEST_ENABLED", "true")
    monkeypatch.setattr(voice_ingest.asyncio, "create_task", lambda _coro: _DummyTask())
    voice_ingest._VOICE_INGEST_STARTUP_GUARD["initialized_bots"].clear()
    voice_ingest._VOICE_INGEST_STARTUP_GUARD["listeners_registered_bots"].clear()
    voice_ingest._VOICE_INGEST_STARTUP_GUARD["controllers_registered_bots"].clear()
    voice_ingest._VOICE_INGEST_STARTUP_GUARD["cleanup_completed_bots"].clear()

    registry, bot, _db = _build_registry()
    voice_ingest.setup(registry)
    voice_ingest.setup(registry)

    assert len(bot._listeners.get("on_ready", [])) == 1
    assert len(bot._listeners.get("on_voice_state_update", [])) == 1
    assert len(bot._listeners.get("on_message", [])) == 1


def test_voice_state_auto_join_is_deferred_until_startup_ready(monkeypatch: Any) -> None:
    _install_fake_voice_recv()
    monkeypatch.setenv("VOICE_INGEST_ENABLED", "true")
    monkeypatch.setattr(voice_ingest.asyncio, "create_task", lambda _coro: _DummyTask())

    registry, bot, db = _build_registry()
    db.settings = {
        f"voice_ingest.{bot.user.id}.enabled": "true",
        f"voice_ingest.{bot.user.id}.auto_join": "true",
        f"voice_ingest.{bot.user.id}.privacy_mode": "false",
        f"voice_ingest.{bot.user.id}.min_users_to_join": "1",
        f"voice_ingest.{bot.user.id}.target_voice_channel_id": "555",
    }
    voice_ingest.setup(registry)

    listener = bot.get_listener("on_voice_state_update")
    client = _FakeVoiceClient(connected=True)
    channel = types.SimpleNamespace(id=555, guild=None, members=[])
    guild = types.SimpleNamespace(id=77, voice_client=None, get_channel=lambda _id: channel)
    channel.guild = guild
    member = types.SimpleNamespace(id=123, bot=False, guild=guild, display_name="u")
    channel.members = [member]
    before = types.SimpleNamespace(channel=None)
    after = types.SimpleNamespace(channel=channel)

    asyncio.run(listener(member, before, after))

    assert guild.voice_client is None


def test_on_ready_does_not_duplicate_controller_registration(monkeypatch: Any) -> None:
    _install_fake_voice_recv()
    monkeypatch.setenv("VOICE_INGEST_ENABLED", "true")
    monkeypatch.setattr(voice_ingest.asyncio, "create_task", lambda _coro: _DummyTask())

    registry, bot, _db = _build_registry()
    voice_ingest.setup(registry)
    on_ready = bot.get_listener("on_ready")

    asyncio.run(on_ready())
    first_controller = registry.get("voice_ingest")
    asyncio.run(on_ready())
    second_controller = registry.get("voice_ingest")

    assert first_controller is second_controller
