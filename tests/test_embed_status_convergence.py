from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.services.embed_public_service_keys import list_public_embed_service_keys
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
        public_services = list_public_embed_service_keys()
        assert "triggers" in public_services
        assert "audio_notes" not in public_services
        assert "campagne_notizie" not in public_services
        assert len(public_services) == 15

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
            assert ("supported services", len(public_services)) in payload["lines"]
            assert ("services with custom template", 1) in payload["lines"]
            assert ("services using default", len(public_services) - 1) in payload["lines"]
            section_titles = {section.title for section in payload["sections"]}
            assert section_titles == {"Custom Templates", "Default Services", "PLACEHOLDERS"}
            custom_templates = next(section for section in payload["sections"] if section.title == "Custom Templates").lines
            assert any(service_name == "dmchannelsummary" for service_name, _ in custom_templates)
            default_services_text = next(section for section in payload["sections"] if section.title == "Default Services").lines[0][1]
            assert "triggers" in default_services_text
            assert "campaigns" in default_services_text
            assert "audio_notes" not in default_services_text
            assert "campagne_notizie" not in default_services_text
            assert "formatter" not in default_services_text
            assert "builder" not in default_services_text
            assert "renderer" not in default_services_text
            placeholders_section = next(section for section in payload["sections"] if section.title == "PLACEHOLDERS")
            assert placeholders_section.lines

        description_placeholders = dict(next(section for section in description_kwargs["sections"] if section.title == "PLACEHOLDERS").lines)
        assert "{user_name}" in description_placeholders
        assert "{audio_intro}" in description_placeholders
        assert "{service_label}" not in description_placeholders

        author_placeholders = dict(next(section for section in author_kwargs["sections"] if section.title == "PLACEHOLDERS").lines)
        assert "{service_name}" in author_placeholders
        assert "{service_label}" in author_placeholders
        assert "{user_name}" not in author_placeholders

        footer_placeholders = dict(next(section for section in footer_kwargs["sections"] if section.title == "PLACEHOLDERS").lines)
        assert "{service_name}" in footer_placeholders
        assert "{bot_version}" in footer_placeholders
        assert "{audio_intro}" not in footer_placeholders

    asyncio.run(_run())


def test_embed_status_maps_legacy_custom_services_to_public_canonical_keys(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, "check_permission", AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, "send_standard_response", send_standard)
        bundle = register_embed_tree(embed_module)

        await bundle.ctx.footer.set_service_phrase("campagne", "Campagne custom")
        await bundle.ctx.footer.set_service_phrase("barcello", "Trigger custom")

        footer_status = find_command(bundle.footer_group, "status")
        await footer_status.callback(InteractionStub(footer_status))
        footer_custom_lines = next(section for section in send_standard.await_args.kwargs["sections"] if section.title == "Custom Templates").lines

        assert ("campaigns", "phrase") in footer_custom_lines
        assert ("triggers", "phrase") in footer_custom_lines
        assert not any(service in {"campagne", "barcello", "frasi"} for service, _ in footer_custom_lines)

    asyncio.run(_run())


def test_template_service_show_uses_same_placeholder_source_as_status(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, "check_permission", AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, "send_standard_response", send_standard)
        bundle = register_embed_tree(embed_module)

        author_status = find_command(bundle.author_group, "status")
        author_show = find_command(bundle.author_group, "template_service_show")
        footer_status = find_command(bundle.footer_group, "status")
        footer_show = find_command(bundle.footer_group, "template_service_show")
        description_status = find_command(bundle.description_group, "status")
        description_show = find_command(bundle.description_group, "template_service_show")

        await author_status.callback(InteractionStub(author_status))
        author_status_placeholders = next(section for section in send_standard.await_args.kwargs["sections"] if section.title == "PLACEHOLDERS").lines
        send_standard.reset_mock()
        await author_show.callback(InteractionStub(author_show), "audio")
        author_show_placeholders = next(section for section in send_standard.await_args.kwargs["sections"] if section.title == "PLACEHOLDERS").lines
        assert author_show_placeholders == author_status_placeholders

        send_standard.reset_mock()
        await footer_status.callback(InteractionStub(footer_status))
        footer_status_placeholders = next(section for section in send_standard.await_args.kwargs["sections"] if section.title == "PLACEHOLDERS").lines
        send_standard.reset_mock()
        await footer_show.callback(InteractionStub(footer_show), "audio")
        footer_show_placeholders = next(section for section in send_standard.await_args.kwargs["sections"] if section.title == "PLACEHOLDERS").lines
        assert footer_show_placeholders == footer_status_placeholders

        send_standard.reset_mock()
        await description_status.callback(InteractionStub(description_status))
        description_status_placeholders = next(section for section in send_standard.await_args.kwargs["sections"] if section.title == "PLACEHOLDERS").lines
        send_standard.reset_mock()
        await description_show.callback(InteractionStub(description_show), "audio")
        description_show_placeholders = next(section for section in send_standard.await_args.kwargs["sections"] if section.title == "PLACEHOLDERS").lines
        assert description_show_placeholders == description_status_placeholders

    asyncio.run(_run())
