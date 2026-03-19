from __future__ import annotations

import importlib
import sys
import types

import pytest


class _StubAsyncClient:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def get(self, *args, **kwargs):
        raise RuntimeError("httpx stub: network call not configured in this test")


class _StubSyncClient:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


class _StubWhisperModel:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


def _stub_module(name: str, **attrs: object) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


@pytest.fixture
def stub_optional_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "aiosqlite", _stub_module("aiosqlite", Row=dict, Connection=object, connect=object))
    monkeypatch.setitem(sys.modules, "openai", _stub_module("openai", AsyncOpenAI=object))
    monkeypatch.setitem(sys.modules, "httpx", _stub_module("httpx", AsyncClient=_StubAsyncClient, Client=_StubSyncClient))
    monkeypatch.setitem(sys.modules, "faster_whisper", _stub_module("faster_whisper", WhisperModel=_StubWhisperModel))
    argos_pkg = _stub_module("argostranslate")
    argos_translate = _stub_module("argostranslate.translate", translate=lambda text, from_code=None, to_code=None: text, get_installed_languages=lambda: [])
    setattr(argos_pkg, "translate", argos_translate)
    monkeypatch.setitem(sys.modules, "argostranslate", argos_pkg)
    monkeypatch.setitem(sys.modules, "argostranslate.translate", argos_translate)


@pytest.fixture
def import_fresh(monkeypatch: pytest.MonkeyPatch, stub_optional_dependencies: None):
    def _import(module_name: str):
        prefixes = {module_name, "app.plugins.commands_modular", "app.core.bot"}
        for loaded_name in list(sys.modules):
            if any(loaded_name == prefix or loaded_name.startswith(prefix + ".") for prefix in prefixes):
                monkeypatch.delitem(sys.modules, loaded_name, raising=False)
        return importlib.import_module(module_name)

    return _import
