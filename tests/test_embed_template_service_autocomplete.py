from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.services.embed_template_service_catalog import (
    build_embed_template_service_autocomplete_choices,
    list_embed_template_services,
    resolve_embed_template_public_service,
)
from tests._embed_test_utils import find_command, register_embed_tree


@pytest.fixture
def embed_module(import_fresh):
    return import_fresh("app.plugins.commands_modular.embed")


def test_embed_template_services_source_of_truth_is_public_and_stable() -> None:
    async def _run() -> None:
        ctx = SimpleNamespace()
        services = await list_embed_template_services(ctx)
        assert services == [
            "audio",
            "aura",
            "riassunto",
            "resoconto",
            "attivita",
            "barcello",
            "campagne",
            "qna",
            "status",
        ]
        assert len(services) == len(set(services))
        assert "audio_notes" not in services
        assert "campaign_content_formatter" not in services
        assert "detail_embeds" not in services

    asyncio.run(_run())


def test_embed_template_services_autocomplete_only_shows_public_keys() -> None:
    async def _run() -> None:
        ctx = SimpleNamespace()
        filtered = await build_embed_template_service_autocomplete_choices(ctx, "au")
        assert filtered
        assert [choice.value for choice in filtered] == ["audio", "aura"]

        full = await build_embed_template_service_autocomplete_choices(ctx, "")
        values = [choice.value for choice in full]
        assert len(values) <= 25
        assert "audio" in values
        assert "audio_notes" not in values
        assert "campaign_content_views" not in values
        assert "detail_embeds" not in values
        assert len(values) == len(set(values))

    asyncio.run(_run())


def test_embed_template_service_resolver_maps_legacy_aliases_to_public_keys() -> None:
    assert resolve_embed_template_public_service("audio") == "audio"
    assert resolve_embed_template_public_service("audio_notes") == "audio"
    assert resolve_embed_template_public_service("campagne_prompt") == "campagne"
    assert resolve_embed_template_public_service("detail_embeds") is None


def test_embed_template_service_commands_share_same_autocomplete_binding(embed_module) -> None:
    bundle = register_embed_tree(embed_module)

    command_paths = [
        (bundle.author_group, "template_service_set"),
        (bundle.author_group, "template_service_show"),
        (bundle.author_group, "template_service_reset"),
        (bundle.footer_group, "template_service_set"),
        (bundle.footer_group, "template_service_show"),
        (bundle.footer_group, "template_service_reset"),
        (bundle.images_group, "template_service_set"),
        (bundle.images_group, "template_service_show"),
        (bundle.images_group, "template_service_reset"),
        (bundle.description_group, "template_service_set"),
        (bundle.description_group, "template_service_show"),
        (bundle.description_group, "template_service_reset"),
    ]

    callbacks = []
    for group, command_name in command_paths:
        command = find_command(group, command_name)
        assert command._params["service"].autocomplete is not None
        callbacks.append(command._params["service"].autocomplete)

    first_callback = callbacks[0]
    assert all(callback is first_callback for callback in callbacks)
