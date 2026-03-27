from __future__ import annotations

from discord import app_commands

from app.services.embed_public_service_keys import EmbedTemplateSystem, list_public_embed_service_keys, resolve_public_embed_service_key

_MAX_AUTOCOMPLETE_CHOICES = 25


async def list_embed_template_services(
    ctx: object | None = None,
    *,
    system: EmbedTemplateSystem | None = None,
) -> list[str]:
    del ctx
    return list_public_embed_service_keys(system=system)


def resolve_embed_template_public_service(
    service_name: str | None,
    *,
    system: EmbedTemplateSystem | None = None,
) -> str | None:
    return resolve_public_embed_service_key(service_name, system=system)


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


async def build_embed_template_service_autocomplete_choices(
    ctx: object | None,
    current: str,
    *,
    system: EmbedTemplateSystem | None = None,
) -> list[app_commands.Choice[str]]:
    query = (current or "").strip().lower()
    services = await list_embed_template_services(ctx, system=system)

    filtered = [service_name for service_name in services if not query or query in service_name]
    if query:
        filtered.sort(key=lambda service_name: _autocomplete_sort_key(service_name, query))

    return [
        app_commands.Choice(name=service_name, value=service_name)
        for service_name in filtered[:_MAX_AUTOCOMPLETE_CHOICES]
    ]
