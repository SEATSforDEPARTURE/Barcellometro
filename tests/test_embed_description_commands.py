from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from tests._embed_test_utils import InteractionStub, find_command, register_embed_tree, section_payload


@pytest.fixture
def embed_module(import_fresh):
    return import_fresh("app.plugins.commands_modular.embed")


def test_description_commands_registered(embed_module) -> None:
    bundle = register_embed_tree(embed_module)
    assert {command.name for command in bundle.description_group.commands} == {
        "on",
        "off",
        "status",
        "template_service_set",
        "template_service_show",
        "template_service_reset",
    }


def test_description_template_set_show_reset(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, "check_permission", AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, "send_standard_response", send_standard)
        bundle = register_embed_tree(embed_module)

        set_command = find_command(bundle.description_group, "template_service_set")
        await set_command.callback(
            InteractionStub(set_command),
            "audio",
            "{audio_intro} **{user_name}** — **{ordinal_today}**",
        )
        assert send_standard.await_args.kwargs["lines"] == [("result", "updated")]
        assert section_payload(send_standard.await_args.kwargs) == (
            "Template",
            [
                ("Template", "{audio_intro} **{user_name}** — **{ordinal_today}**"),
                ("Preview", "*Leggiamo cosa ci dice **Mario** — **secondo***"),
            ],
        )

        send_standard.reset_mock()
        show_command = find_command(bundle.description_group, "template_service_show")
        await show_command.callback(InteractionStub(show_command), "audio")
        show_kwargs = send_standard.await_args.kwargs
        assert section_payload(show_kwargs) == (
            "Template",
            [
                ("Template", "{audio_intro} **{user_name}** — **{ordinal_today}**"),
                ("Preview", "*Leggiamo cosa ci dice **Mario** — **secondo***"),
            ],
        )
        placeholders = dict(next(section for section in show_kwargs["sections"] if section.title == "PLACEHOLDERS").lines)
        assert "{user_name}" in placeholders
        assert "{audio_intro}" in placeholders
        assert "{service_label}" not in placeholders

        send_standard.reset_mock()
        reset_command = find_command(bundle.description_group, "template_service_reset")
        await reset_command.callback(InteractionStub(reset_command), "audio")
        assert send_standard.await_args.kwargs["lines"] == [("result", "reset")]

        send_standard.reset_mock()
        await show_command.callback(InteractionStub(show_command), "audio")
        fallback_kwargs = send_standard.await_args.kwargs
        assert section_payload(fallback_kwargs) == (
            "Template",
            [
                ("Template", "usa default del servizio"),
                ("Preview", "*Usa default del servizio*"),
            ],
        )
        fallback_placeholders = dict(next(section for section in fallback_kwargs["sections"] if section.title == "PLACEHOLDERS").lines)
        assert fallback_placeholders == placeholders

    asyncio.run(_run())


def test_description_on_off_status_and_runtime_gate(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, "check_permission", AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, "send_standard_response", send_standard)
        bundle = register_embed_tree(embed_module)

        on_command = find_command(bundle.description_group, "on")
        await on_command.callback(InteractionStub(on_command))
        assert send_standard.await_args.kwargs["lines"] == [("result", "enabled")]
        assert await bundle.ctx.description_template.is_enabled() is True

        set_command = find_command(bundle.description_group, "template_service_set")
        await set_command.callback(InteractionStub(set_command), "audio", "Template {audio_intro} {user_name}")

        off_command = find_command(bundle.description_group, "off")
        send_standard.reset_mock()
        await off_command.callback(InteractionStub(off_command))
        assert send_standard.await_args.kwargs["lines"] == [("result", "disabled")]
        assert await bundle.ctx.description_template.is_enabled() is False
        assert await bundle.ctx.description_template.get_template("audio") == "Template {audio_intro} {user_name}"

        runtime_render = await bundle.ctx.description_template.render(
            service="audio",
            context={"user_name": "Mario"},
            fallback="Fallback nativo",
        )
        assert runtime_render == "*Fallback nativo*"

        status_command = find_command(bundle.description_group, "status")
        send_standard.reset_mock()
        await status_command.callback(InteractionStub(status_command))
        assert ("enabled", "off") in send_standard.await_args.kwargs["lines"]
        sections = send_standard.await_args.kwargs["sections"]
        custom_section = next(section for section in sections if section.title == "Custom Templates")
        assert ("audio", "Template {audio_intro} {user_name}") in custom_section.lines
        default_section = next(section for section in sections if section.title == "Default Services")
        assert "triggers" in default_section.lines[0][1]
        assert "audio_notes" not in str(default_section.lines)
        assert "campaign_content_formatter" not in str(default_section.lines)
        placeholders = dict(next(section for section in sections if section.title == "PLACEHOLDERS").lines)
        assert "{user_name}" in placeholders
        assert "{audio_intro}" in placeholders
        assert "{service_label}" not in placeholders

    asyncio.run(_run())


def test_description_template_set_rejects_invalid_placeholder(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, "check_permission", AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, "send_standard_response", send_standard)
        bundle = register_embed_tree(embed_module)

        set_command = find_command(bundle.description_group, "template_service_set")
        await set_command.callback(InteractionStub(set_command), "audio", "Ciao {user_mention}")
        assert send_standard.await_args.kwargs["kind"] == "error"
        assert "Invalid placeholders" in send_standard.await_args.kwargs["lines"][0][1]

    asyncio.run(_run())


def test_description_template_service_legacy_alias_is_normalized_to_public_key(embed_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(embed_module, "check_permission", AsyncMock(return_value=True))
        send_standard = AsyncMock()
        monkeypatch.setattr(embed_module, "send_standard_response", send_standard)
        bundle = register_embed_tree(embed_module)

        set_command = find_command(bundle.description_group, "template_service_set")
        await set_command.callback(InteractionStub(set_command), "audio_notes", "{audio_intro} {user_name}")

        assert send_standard.await_args.kwargs["subtitle_args"] == ["audio"]
        assert "description_template:audio" in bundle.database.settings
        assert "description_template:audio_notes" not in bundle.database.settings

    asyncio.run(_run())
