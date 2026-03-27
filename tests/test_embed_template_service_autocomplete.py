from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.services.embed_template_service_catalog import (
    build_embed_template_service_autocomplete_choices,
    list_embed_template_services,
)
from app.services.footer import SUPPORTED_FOOTER_SERVICES
from tests._embed_test_utils import find_command, register_embed_tree


@pytest.fixture
def embed_module(import_fresh):
    return import_fresh("app.plugins.commands_modular.embed")


def test_embed_template_services_source_of_truth_is_centralized_and_sorted() -> None:
    async def _run() -> None:
        async def _known_footer_services() -> list[str]:
            return ["riassunto", "custom_service", "Custom_Service", "unknown"]

        async def _known_author_services() -> list[str]:
            return ["aura", "custom_service", "fallback"]

        async def _service_images() -> dict[str, str]:
            return {"image_only": "https://example.com/image.png"}

        async def _service_thumbnails() -> dict[str, str]:
            return {"thumb_only": "https://example.com/thumb.png"}

        async def _fetchall(_query: str, _params: tuple[str, ...]):
            return [
                {"key": "description_template:desc_only", "value": "tpl"},
                {"key": "description_template:CUSTOM_SERVICE", "value": "tpl"},
            ]

        ctx = SimpleNamespace(
            footer=SimpleNamespace(get_known_services=_known_footer_services),
            author=SimpleNamespace(get_known_services=_known_author_services),
            embed_images=SimpleNamespace(
                get_service_images=_service_images,
                get_service_thumbnails=_service_thumbnails,
            ),
            database=SimpleNamespace(fetchall=_fetchall),
        )

        services = await list_embed_template_services(ctx)

        assert services == sorted(services)
        assert len(services) == len(set(services))
        assert "custom_service" in services
        assert "image_only" in services
        assert "thumb_only" in services
        assert "desc_only" in services
        assert "unknown" not in services
        assert "fallback" not in services
        for expected in ("riassunto", "aura", "status"):
            assert expected in services

    asyncio.run(_run())


def test_embed_template_services_autocomplete_filters_and_limits() -> None:
    async def _run() -> None:
        dynamic_services = [f"service_{idx:02d}" for idx in range(40)]

        async def _known_footer_services() -> list[str]:
            return list(SUPPORTED_FOOTER_SERVICES) + dynamic_services

        ctx = SimpleNamespace(
            footer=SimpleNamespace(get_known_services=_known_footer_services),
            author=None,
            embed_images=None,
            database=None,
        )

        filtered = await build_embed_template_service_autocomplete_choices(ctx, "service_1")
        assert filtered
        assert all("service_1" in choice.value for choice in filtered)
        assert len(filtered) <= 25

        full = await build_embed_template_service_autocomplete_choices(ctx, "")
        assert len(full) == 25
        assert [choice.value for choice in full] == sorted(choice.value for choice in full)

    asyncio.run(_run())


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
