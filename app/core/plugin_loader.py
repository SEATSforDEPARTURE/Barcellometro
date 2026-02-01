from __future__ import annotations

import importlib
import logging
from typing import Iterable

from app.core.service_registry import ServiceRegistry

logger = logging.getLogger(__name__)


class PluginLoader:
    def __init__(self, registry: ServiceRegistry) -> None:
        self._registry = registry
        self._loaded: list[str] = []

    def load(self, module_paths: Iterable[str], *, strict: bool = True) -> None:
        for module_path in module_paths:
            try:
                module = importlib.import_module(module_path)
                if not hasattr(module, "setup"):
                    raise RuntimeError(f"Plugin {module_path} missing setup(registry).")
                module.setup(self._registry)
            except Exception:
                if strict:
                    raise
                logger.exception("Failed to load plugin %s", module_path)
                continue
            self._loaded.append(module_path)
            logger.info("Loaded plugin %s", module_path)

    @property
    def loaded(self) -> list[str]:
        return list(self._loaded)
