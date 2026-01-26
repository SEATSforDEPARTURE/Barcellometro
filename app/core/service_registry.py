from __future__ import annotations

from typing import Any, Dict


class ServiceRegistry:
    def __init__(self) -> None:
        self._services: Dict[str, Any] = {}

    def register(self, name: str, service: Any) -> None:
        self._services[name] = service

    def get(self, name: str) -> Any:
        return self._services[name]

    def has(self, name: str) -> bool:
        return name in self._services

    def all(self) -> Dict[str, Any]:
        return dict(self._services)
