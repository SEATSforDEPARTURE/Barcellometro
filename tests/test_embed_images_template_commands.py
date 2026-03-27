from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from tests._embed_test_utils import InteractionStub, find_command, register_embed_tree, section_payload


@pytest.fixture
def embed_module(import_fresh):
    return import_fresh("app.plugins.commands_modular.embed")


def test_images_template_service_resolves_legacy_aliases(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, "check_permission", AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, "send_standard_response", send_standard)
        bundle = register_embed_tree(embed_module)
        bundle.database.settings["embed_images.service_image.audio_notes"] = "https://example.com/legacy.png"

        show_command = find_command(bundle.images_group, "template_service_show")
        await show_command.callback(InteractionStub(show_command), "audio")
        assert section_payload(send_standard.await_args.kwargs) == (
            "Template",
            [("Image", "https://example.com/legacy.png"), ("Thumbnail", "(not set)")],
        )

        send_standard.reset_mock()
        set_command = find_command(bundle.images_group, "template_service_set")
        await set_command.callback(InteractionStub(set_command), "audio_notes", image="https://example.com/new.png")
        assert send_standard.await_args.kwargs["subtitle_args"] == ["audio"]
        assert "embed_images.service_image.audio" in bundle.database.settings

    asyncio.run(_run())
