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
        assert section_payload(send_standard.await_args.kwargs) == (
            "Template",
            [
                ("Template", "{audio_intro} **{user_name}** — **{ordinal_today}**"),
                ("Preview", "*Leggiamo cosa ci dice **Mario** — **secondo***"),
            ],
        )

        send_standard.reset_mock()
        reset_command = find_command(bundle.description_group, "template_service_reset")
        await reset_command.callback(InteractionStub(reset_command), "audio")
        assert send_standard.await_args.kwargs["lines"] == [("result", "reset")]

        send_standard.reset_mock()
        await show_command.callback(InteractionStub(show_command), "audio")
        assert section_payload(send_standard.await_args.kwargs) == (
            "Template",
            [
                ("Template", "usa default del servizio"),
                ("Preview", "*Usa default del servizio*"),
            ],
        )

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
