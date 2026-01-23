from __future__ import annotations
from typing import Any

class ServiceRegistry:
    def __init__(self) -> None:
        self._services: dict[str, Any] = {}

    def register(self, name: str, service: Any) -> None:
        self._services[name] = service

    def get(self, name: str) -> Any | None:
        return self._services.get(name)

    def require(self, name: str) -> Any:
        svc = self.get(name)
        if svc is None:
            raise KeyError(f"Service '{name}' non registrato")
        return svc

    def has(self, name: str) -> bool:
        return name in self._services

    def list(self) -> list[str]:
        return sorted(self._services.keys())
