from __future__ import annotations

from collections.abc import Awaitable, Iterable
from typing import Any

from discord import app_commands

from app.services.footer import SUPPORTED_FOOTER_SERVICES

_DESCRIPTION_TEMPLATE_KEY_PREFIX = "description_template:"
_MAX_AUTOCOMPLETE_CHOICES = 25


def _clean_service_name(value: str | None) -> str | None:
    service_name = (value or "").strip().lower()
    if not service_name or service_name in {"unknown", "default", "fallback"}:
        return None
    return service_name


async def _maybe_extend_from_awaitable(values: set[str], source: Any) -> None:
    if source is None:
        return
    if isinstance(source, Awaitable):
        source = await source
    if isinstance(source, dict):
        iterable: Iterable[Any] = source.keys()
    elif isinstance(source, (list, tuple, set)):
        iterable = source
    else:
        return

    for item in iterable:
        normalized = _clean_service_name(str(item) if item is not None else None)
        if normalized:
            values.add(normalized)


async def list_embed_template_services(ctx: Any) -> list[str]:
    services: set[str] = {
        normalized
        for item in SUPPORTED_FOOTER_SERVICES
        if (normalized := _clean_service_name(item)) is not None
    }

    footer = getattr(ctx, "footer", None)
    author = getattr(ctx, "author", None)
    embed_images = getattr(ctx, "embed_images", None)
    database = getattr(ctx, "database", None)

    if footer is not None and hasattr(footer, "get_known_services"):
        await _maybe_extend_from_awaitable(services, footer.get_known_services())

    if author is not None and hasattr(author, "get_known_services"):
        await _maybe_extend_from_awaitable(services, author.get_known_services())

    if embed_images is not None and hasattr(embed_images, "get_service_images"):
        await _maybe_extend_from_awaitable(services, embed_images.get_service_images())

    if embed_images is not None and hasattr(embed_images, "get_service_thumbnails"):
        await _maybe_extend_from_awaitable(services, embed_images.get_service_thumbnails())

    if database is not None and hasattr(database, "fetchall"):
        rows = await database.fetchall(
            "SELECT key, value FROM settings WHERE key LIKE ? ORDER BY key",
            (f"{_DESCRIPTION_TEMPLATE_KEY_PREFIX}%",),
        )
        for row in rows:
            key = str(row.get("key", ""))
            service_key = key.removeprefix(_DESCRIPTION_TEMPLATE_KEY_PREFIX)
            normalized = _clean_service_name(service_key)
            if normalized:
                services.add(normalized)

    return sorted(services)


def _autocomplete_sort_key(service_name: str, query: str) -> tuple[int, int, str]:
    if not query:
        return (0, 0, service_name)
    if service_name == query:
        return (0, 0, service_name)
    if service_name.startswith(query):
        return (0, 1, service_name)
    if query in service_name:
        return (1, 0, service_name)
    return (2, 0, service_name)


async def build_embed_template_service_autocomplete_choices(ctx: Any, current: str) -> list[app_commands.Choice[str]]:
    query = (current or "").strip().lower()
    services = await list_embed_template_services(ctx)

    filtered = [service_name for service_name in services if not query or query in service_name]
    filtered.sort(key=lambda service_name: _autocomplete_sort_key(service_name, query))

    return [
        app_commands.Choice(name=service_name, value=service_name)
        for service_name in filtered[:_MAX_AUTOCOMPLETE_CHOICES]
    ]
