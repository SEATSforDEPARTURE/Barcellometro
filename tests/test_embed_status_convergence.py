from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from tests._embed_test_utils import InteractionStub, find_command, register_embed_tree


@pytest.fixture
def embed_module(import_fresh):
    return import_fresh("app.plugins.commands_modular.embed")


def test_embed_status_commands_share_public_service_source_and_custom_default_split(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, "check_permission", AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, "send_standard_response", send_standard)
        bundle = register_embed_tree(embed_module)

        await bundle.ctx.author.set_service_phrase("riassunto", "Author custom")
        await bundle.ctx.footer.set_service_phrase("riassunto", "Footer custom")
        await bundle.ctx.description_template.set_template("riassunto", "Template {user_name}")

        author_status = find_command(bundle.author_group, "status")
        footer_status = find_command(bundle.footer_group, "status")
        description_status = find_command(bundle.description_group, "status")

        await author_status.callback(InteractionStub(author_status))
        author_kwargs = send_standard.await_args.kwargs
        send_standard.reset_mock()

        await footer_status.callback(InteractionStub(footer_status))
        footer_kwargs = send_standard.await_args.kwargs
        send_standard.reset_mock()

        await description_status.callback(InteractionStub(description_status))
        description_kwargs = send_standard.await_args.kwargs

        for payload in (author_kwargs, footer_kwargs, description_kwargs):
            assert ("supported services", 9) in payload["lines"]
            assert ("services with custom template", 1) in payload["lines"]
            assert ("services using default", 8) in payload["lines"]
            section_titles = {section.title for section in payload["sections"]}
            assert section_titles == {"Custom Templates", "Default Services"}
            default_services_text = next(section for section in payload["sections"] if section.title == "Default Services").lines[0][1]
            assert "audio_notes" not in default_services_text
            assert "campagne_notizie" not in default_services_text
            assert "formatter" not in default_services_text
            assert "builder" not in default_services_text
            assert "renderer" not in default_services_text

    asyncio.run(_run())
