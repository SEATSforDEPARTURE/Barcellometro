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


_EXPECTED_CANONICAL_PUBLIC_SERVICES = [
    "audio",
    "triggers",
    "greetings",
    "channelsummary",
    "serversummary",
    "dmchannelsummary",
    "dmserversummary",
    "campaigns",
    "qna",
    "inactivity",
    "embed",
    "commandguard",
    "database",
    "status",
    "ai",
    "users",
]


def test_embed_template_services_canonical_public_list_is_exact() -> None:
    async def _run() -> None:
        ctx = SimpleNamespace()
        services = await list_embed_template_services(ctx)
        assert services == _EXPECTED_CANONICAL_PUBLIC_SERVICES
        assert len(services) == len(set(services))

    asyncio.run(_run())


def test_embed_template_services_autocomplete_excludes_legacy_keys() -> None:
    async def _run() -> None:
        ctx = SimpleNamespace()
        full = await build_embed_template_service_autocomplete_choices(ctx, "")
        values = [choice.value for choice in full]
        assert len(values) <= 25
        assert values == _EXPECTED_CANONICAL_PUBLIC_SERVICES

        for legacy in ("attivita", "aura", "barcello", "campagne", "riassunto", "resoconto", "frasi"):
            assert legacy not in values

    asyncio.run(_run())


def test_author_template_service_set_autocomplete_includes_users_and_not_singular_user(embed_module) -> None:
    bundle = register_embed_tree(embed_module)
    set_command = find_command(bundle.author_group, "template_service_set")
    autocomplete = set_command._params["service"].autocomplete
    assert autocomplete is not None

    async def _run() -> None:
        choices = await autocomplete(SimpleNamespace(), "")
        values = [choice.value for choice in choices]
        assert "users" in values
        assert "user" not in values

    asyncio.run(_run())


def test_embed_template_service_resolver_maps_legacy_aliases_to_public_keys() -> None:
    assert resolve_embed_template_public_service("audio_notes") == "audio"
    assert resolve_embed_template_public_service("barcello") == "triggers"
    assert resolve_embed_template_public_service("frasi") == "triggers"
    assert resolve_embed_template_public_service("member_flow_notifications") == "greetings"
    assert resolve_embed_template_public_service("resoconto") == "channelsummary"
    assert resolve_embed_template_public_service("riassunto") == "dmchannelsummary"
    assert resolve_embed_template_public_service("attivita") == "dmserversummary"
    assert resolve_embed_template_public_service("aura") == "dmserversummary"
    assert resolve_embed_template_public_service("campagne_prompt") == "campaigns"
    assert resolve_embed_template_public_service("domanda") == "qna"
    assert resolve_embed_template_public_service("inattivi") == "inactivity"
    assert resolve_embed_template_public_service("utenti") == "users"
    assert resolve_embed_template_public_service("mod_users") == "users"
    assert resolve_embed_template_public_service("audio notes") == "audio"


def test_embed_template_service_supports_explicit_system_validation() -> None:
    assert resolve_embed_template_public_service("triggers", system="author") == "triggers"
    assert resolve_embed_template_public_service("triggers", system="footer") == "triggers"
    assert resolve_embed_template_public_service("triggers", system="description") == "triggers"


def test_embed_template_service_commands_use_same_source_with_system_specific_autocomplete(embed_module) -> None:
    bundle = register_embed_tree(embed_module)

    footer_commands = [
        (bundle.footer_group, "template_service_set"),
        (bundle.footer_group, "template_service_show"),
        (bundle.footer_group, "template_service_reset"),
    ]
    author_commands = [
        (bundle.author_group, "template_service_set"),
        (bundle.author_group, "template_service_show"),
        (bundle.author_group, "template_service_reset"),
    ]
    description_commands = [
        (bundle.description_group, "template_service_set"),
        (bundle.description_group, "template_service_show"),
        (bundle.description_group, "template_service_reset"),
    ]
    images_commands = [
        (bundle.images_group, "template_service_set"),
        (bundle.images_group, "template_service_show"),
        (bundle.images_group, "template_service_reset"),
    ]

    def _callbacks(command_paths):
        callbacks = []
        for group, command_name in command_paths:
            command = find_command(group, command_name)
            assert command._params["service"].autocomplete is not None
            callbacks.append(command._params["service"].autocomplete)
        return callbacks

    footer_callbacks = _callbacks(footer_commands)
    author_callbacks = _callbacks(author_commands)
    description_callbacks = _callbacks(description_commands)
    images_callbacks = _callbacks(images_commands)

    assert all(callback is footer_callbacks[0] for callback in footer_callbacks)
    assert all(callback is author_callbacks[0] for callback in author_callbacks)
    assert all(callback is description_callbacks[0] for callback in description_callbacks)
    assert all(callback is images_callbacks[0] for callback in images_callbacks)

    async def _run() -> None:
        ctx = SimpleNamespace()
        footer = await list_embed_template_services(ctx, system="footer")
        author = await list_embed_template_services(ctx, system="author")
        description = await list_embed_template_services(ctx, system="description")
        images = await list_embed_template_services(ctx, system="images")
        assert footer == author == description == images == _EXPECTED_CANONICAL_PUBLIC_SERVICES

    asyncio.run(_run())


def test_embed_template_service_resolver_returns_none_for_unknown_key() -> None:
    assert resolve_embed_template_public_service("unknown_service") is None
