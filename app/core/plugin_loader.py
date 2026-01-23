from __future__ import annotations
import importlib
import logging
from types import ModuleType
from typing import Any

log = logging.getLogger("barcellometro.plugin_loader")

def load_plugin_module(name: str) -> ModuleType:
    return importlib.import_module(f"app.plugins.{name}")

def safe_call(obj: Any, fn_name: str, default=None):
    fn = getattr(obj, fn_name, None)
    if callable(fn):
        return fn()
    return default

def load_plugins(bot, registry, plugin_names: list[str]) -> dict[str, dict]:
    manifests: dict[str, dict] = {}
    for name in plugin_names:
        try:
            mod = load_plugin_module(name)
            setup = getattr(mod, "setup", None)
            if not callable(setup):
                log.warning("Plugin '%s' ignorato: manca setup(bot, registry)", name)
                continue

            setup(bot, registry)

            manifest = safe_call(mod, "get_manifest", default={"name": name})
            if not isinstance(manifest, dict):
                manifest = {"name": name}
            manifest.setdefault("name", name)
            manifests[name] = manifest
            log.info("Plugin caricato: %s", name)
        except Exception as e:
            log.exception("Errore caricando plugin '%s': %s", name, e)
            manifests[name] = {"name": name, "error": str(e), "loaded": False}
    return manifests
