from __future__ import annotations

import asyncio

from app.services.description_template_service import DescriptionTemplateService, InvalidDescriptionTemplateError


class _DbStub:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get_setting(self, key: str):
        return self.values.get(key)

    async def set_setting(self, key: str, value: str) -> None:
        self.values[key] = value

    async def delete_setting(self, key: str) -> None:
        self.values.pop(key, None)


def test_set_show_reset_roundtrip() -> None:
    async def _run() -> None:
        service = DescriptionTemplateService(_DbStub())
        template = "*{audio_intro} **{user_name}** — **{ordinal_today}***"
        stored = await service.set_template("audio", template)
        assert stored == template
        assert await service.get_template("audio") == template

        preview = await service.render_preview(
            service="audio",
            context={"user_name": "Mario", "ordinal_today": "secondo", "count_today": 2, "is_first_today": False},
            fallback="Fallback",
        )
        assert preview.startswith("*")
        assert "**Mario**" in preview

        await service.reset_template("audio")
        assert await service.get_template("audio") is None

    asyncio.run(_run())


def test_render_fallback_and_placeholder_validation() -> None:
    async def _run() -> None:
        service = DescriptionTemplateService(_DbStub())

        rendered = await service.render(service="riassunto", context={"user_name": "<@123>"}, fallback="Default text")
        assert rendered == "*Default text*"

        try:
            await service.set_template("audio", "Ciao {user_mention}")
            raise AssertionError("Expected InvalidDescriptionTemplateError")
        except InvalidDescriptionTemplateError as exc:
            assert "Invalid placeholders" in str(exc)
            assert "user_name" in str(exc)

    asyncio.run(_run())


def test_render_sanitizes_mentions_and_missing_placeholders() -> None:
    async def _run() -> None:
        service = DescriptionTemplateService(_DbStub())
        await service.set_template("audio", "{audio_intro} {user_name} {ordinal_today}")
        rendered = await service.render(
            service="audio",
            context={"user_name": "<@123>"},
            fallback="Fallback",
        )
        assert "<@" not in rendered
        assert "utente" in rendered
        assert rendered.startswith("*") and rendered.endswith("*")

    asyncio.run(_run())


def test_legacy_service_alias_reads_and_resets_on_public_key() -> None:
    async def _run() -> None:
        db = _DbStub()
        db.values["description_template:audio_notes"] = "Legacy {audio_intro} {user_name}"
        service = DescriptionTemplateService(db)

        assert await service.get_template("audio") == "Legacy {audio_intro} {user_name}"

        await service.set_template("audio_notes", "{audio_intro} {user_name}")
        assert "description_template:audio" in db.values
        assert "description_template:audio_notes" in db.values

        await service.reset_template("audio")
        assert "description_template:audio" not in db.values
        assert "description_template:audio_notes" not in db.values

    asyncio.run(_run())


def test_enabled_flag_persistence_and_runtime_behavior() -> None:
    async def _run() -> None:
        db = _DbStub()
        service = DescriptionTemplateService(db)
        await service.set_template("audio", "Custom {audio_intro} {user_name}")

        assert await service.is_enabled() is True
        await service.set_enabled(False)
        assert await service.is_enabled() is False
        assert db.values["description_template.enabled"] == "false"

        rendered_off = await service.render(service="audio", context={"user_name": "Mario"}, fallback="Native fallback")
        assert rendered_off == "*Native fallback*"

        await service.set_enabled(True)
        rendered_on = await service.render(service="audio", context={"user_name": "Mario"}, fallback="Native fallback")
        assert rendered_on == "*Custom Leggiamo cosa ci dice Mario*"

        rendered_no_custom = await service.render(service="qna", context={"user_name": "Mario"}, fallback="Qna fallback")
        assert rendered_no_custom == "*Qna fallback*"

    asyncio.run(_run())


def test_build_status_snapshot_uses_public_service_keys_only() -> None:
    async def _run() -> None:
        db = _DbStub()
        service = DescriptionTemplateService(db)
        db.values["description_template:audio_notes"] = "Legacy {audio_intro} {user_name}"
        db.values["description_template:campaign_content_formatter"] = "Hidden"

        snapshot = await service.build_status_snapshot()
        assert snapshot.enabled is True
        assert snapshot.total_services == 15
        assert snapshot.custom_templates == {"audio": "Legacy {audio_intro} {user_name}"}

    asyncio.run(_run())
