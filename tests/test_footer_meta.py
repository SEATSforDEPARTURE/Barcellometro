import asyncio
import sys
import types

import discord
import pytest

if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(Connection=object)

from app.services.footer import (
    FooterService,
    InvalidFooterThumbnailError,
    attach_footer_meta,
    attach_footer_meta_to_all,
    attach_minimal_footer,
    copy_footer_meta,
    get_footer_meta,
    normalize_footer_thumbnail,
)
from app.shared.discord.embed_limits import normalize_embeds_for_discord
from app.services.discord_embed_utils import extract_persistable_footer_context, hydrate_persisted_embed_with_footer
from app.shared.discord.embed_limits import _clone_embed_shell
from app.shared.discord.footer_pipeline import finalize_embeds


class _FakeDatabase:
    def __init__(self) -> None:
        self.settings: dict[str, str] = {}

    async def get_setting(self, key: str) -> str | None:
        return self.settings.get(key)

    async def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value

    async def delete_setting(self, key: str) -> None:
        self.settings.pop(key, None)

    async def execute(self, _query: str, _params: tuple[str, ...]) -> None:
        return None

    async def fetchall(self, query: str, params: tuple[str, ...]):
        prefix = str(params[0]).replace('%', '') if params else ''
        if 'FROM settings' not in query:
            return []
        return [
            {'key': key, 'value': value}
            for key, value in sorted(self.settings.items())
            if not prefix or key.startswith(prefix)
        ]


def _build_footer_service() -> tuple[FooterService, _FakeDatabase]:
    database = _FakeDatabase()
    return FooterService(database), database


def test_attach_footer_meta_non_crashing_with_discord_embed() -> None:
    embed = discord.Embed(title="test")
    attach_footer_meta(embed, service_name="barcello", used_local_processing=True)


def test_get_footer_meta_roundtrip() -> None:
    embed = discord.Embed(title="meta")
    attach_footer_meta(
        embed,
        service_name="barcello",
        contributors=["gpt-4o-mini", "gpt-4o-mini", " claude "],
        used_local_processing=True,
    )

    meta = get_footer_meta(embed)
    assert meta is not None
    assert meta.service_name == "barcello"
    assert meta.contributors == ["gpt-4o-mini", "claude"]
    assert meta.used_local_processing is True


def test_copy_footer_meta_copies_values_to_target() -> None:
    source = discord.Embed(title="source")
    target = discord.Embed(title="target")
    attach_footer_meta(source, service_name="riassunto", contributors=["gpt-4o-mini"], used_local_processing=False)

    copy_footer_meta(source, target)

    meta = get_footer_meta(target)
    assert meta is not None
    assert meta.service_name == "riassunto"
    assert meta.contributors == ["gpt-4o-mini"]
    assert meta.used_local_processing is False


def test_clone_embed_shell_keeps_footer_meta_without_copying_rendered_footer_text() -> None:
    source = discord.Embed(title="source")
    attach_footer_meta(source, service_name="riassunto", contributors=["gpt-4o-mini"], used_local_processing=False)

    cloned = _clone_embed_shell(source)

    meta = get_footer_meta(cloned)
    assert meta is not None
    assert meta.service_name == "riassunto"
    assert meta.contributors == ["gpt-4o-mini"]
    assert getattr(cloned.footer, "text", None) in (None, "")



def test_hydrate_persisted_embed_with_footer_reapplies_metadata_after_from_dict() -> None:
    async def _run() -> None:
        source = discord.Embed(title="persisted", description="payload")
        attach_footer_meta(source, service_name="daily_activity_report", contributors=["gpt-4o-mini"], used_local_processing=False)
        persisted = source.to_dict()
        footer_context = extract_persistable_footer_context(source)
        reloaded = discord.Embed.from_dict(persisted)

        await hydrate_persisted_embed_with_footer(
            reloaded,
            footer_context=footer_context,
            footer_service=None,
            default_service_name="daily_activity_report",
            finalize=False,
        )

        meta = get_footer_meta(reloaded)
        assert meta is not None
        assert meta.service_name == "daily_activity_report"
        assert meta.contributors == ["gpt-4o-mini"]
        assert reloaded.title == "persisted"
        assert reloaded.description == "payload"

    asyncio.run(_run())

def test_footer_service_apply_sets_footer_text() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="x")
        attach_footer_meta(embed, service_name="barcello", contributors=["gpt-4o-mini"], used_local_processing=True)
        service, _ = _build_footer_service()
        await service.set_version("1.0")
        await service.set_global_phrase("In via di sviluppo.")

        await service.apply(embed, default_service_name="fallback")

        assert embed.footer.text == "Barcellometro 1.0 · In via di sviluppo. · Dati elaborati con gpt-4o-mini"

    asyncio.run(_run())


def test_footer_service_apply_ignores_legacy_minimal_text_and_uses_centralized_meta() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="x")
        attach_minimal_footer(embed, text="Legacy footer da non usare")
        attach_footer_meta(embed, service_name="riassunto", contributors=["gpt-4o-mini"], used_local_processing=False)
        service, _ = _build_footer_service()
        await service.set_version("1.0")
        await service.set_global_phrase("Sempre acceso.")

        await service.apply(embed, default_service_name="fallback")

        assert embed.footer.text == "Barcellometro 1.0 · Sempre acceso. · Dati elaborati con gpt-4o-mini"
        assert "Legacy footer da non usare" not in (embed.footer.text or "")

    asyncio.run(_run())


def test_finalize_embeds_multi_embed_does_not_crash() -> None:
    async def _run() -> None:
        embeds = [discord.Embed(title="one"), discord.Embed(title="two")]
        attach_footer_meta(embeds[0], service_name="riassunto", contributors=["gpt-4o-mini"])

        service, _ = _build_footer_service()
        await finalize_embeds(embeds, service, default_service_name="unknown")

        assert embeds[0].footer and "Barcellometro" in (embeds[0].footer.text or "")
        assert embeds[1].footer and "Barcellometro" in (embeds[1].footer.text or "")

    asyncio.run(_run())


def test_normalize_embeds_for_discord_preserves_footer_meta_on_split_pages() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="Split me")
        embed.add_field(name="F1", value="x" * 4000, inline=False)
        embed.add_field(name="F2", value="y" * 4000, inline=False)
        attach_footer_meta(embed, service_name="riassunto", contributors=["gpt-4o"], used_local_processing=False)

        normalized = normalize_embeds_for_discord([embed], max_chars=4500)
        assert len(normalized) >= 2

        service, _ = _build_footer_service()
        await service.set_version("dev6")
        await service.set_global_phrase("In via di sviluppo.")
        await finalize_embeds(normalized, service, default_service_name="riassunto")

        footer_texts = [item.footer.text for item in normalized]
        assert len(set(footer_texts)) == 1
        assert footer_texts[0] == "Barcellometro dev6 · In via di sviluppo. · Dati elaborati con gpt-4o"

    asyncio.run(_run())


def test_attach_footer_meta_to_all_applies_consistent_meta() -> None:
    embeds = [discord.Embed(title=f"page {idx}") for idx in range(1, 4)]

    out = attach_footer_meta_to_all(
        embeds,
        service_name="riassunto",
        contributors=["gpt-4o"],
        used_local_processing=False,
    )

    assert out == embeds
    for embed in embeds:
        meta = get_footer_meta(embed)
        assert meta is not None
        assert meta.service_name == "riassunto"
        assert meta.contributors == ["gpt-4o"]
        assert meta.used_local_processing is False


def test_finalize_embeds_multipage_riassunto_keeps_same_ai_footer_on_all_pages() -> None:
    async def _run() -> None:
        embeds = [discord.Embed(title=f"Dettagli {idx}") for idx in range(1, 4)]
        attach_footer_meta_to_all(
            embeds,
            service_name="riassunto",
            contributors=["gpt-4o"],
            used_local_processing=False,
        )
        service, _ = _build_footer_service()
        await service.set_version("dev6")
        await service.set_global_phrase("In via di sviluppo.")

        await finalize_embeds(embeds, service, default_service_name="riassunto")

        footers = [embed.footer.text for embed in embeds]
        assert len(set(footers)) == 1
        assert footers[0] == "Barcellometro dev6 · In via di sviluppo. · Dati elaborati con gpt-4o"
        assert all("in loco" not in (text or "") for text in footers)

    asyncio.run(_run())


def test_finalize_embeds_double_finalize_keeps_existing_ai_footer() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="Dettagli")
        attach_footer_meta(
            embed,
            service_name="riassunto",
            contributors=["gpt-4o"],
            used_local_processing=False,
        )
        service, _ = _build_footer_service()
        await service.set_version("dev6")
        await service.set_global_phrase("In via di sviluppo.")

        await finalize_embeds([embed], service, default_service_name="riassunto")
        first_footer = embed.footer.text

        await finalize_embeds([embed], service, default_service_name="riassunto")

        assert first_footer == "Barcellometro dev6 · In via di sviluppo. · Dati elaborati con gpt-4o"
        assert embed.footer.text == first_footer
        assert get_footer_meta(embed) is None

    asyncio.run(_run())


def test_footer_meta_is_cleaned_up_after_apply() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="cleanup")
        attach_footer_meta(embed, service_name="barcello", contributors=["gpt-4o-mini"])
        service, _ = _build_footer_service()

        assert get_footer_meta(embed) is not None
        await service.apply(embed)
        assert get_footer_meta(embed) is None

    asyncio.run(_run())


def test_footer_service_tracks_multiple_variants_for_same_service() -> None:
    async def _run() -> None:
        service, _ = _build_footer_service()
        await service.record_service_footer_profile(
            service_name="audio_notes",
            contributors=["small", "argos"],
            used_local_processing=True,
            last_rendered_footer="f1",
        )
        await service.record_service_footer_profile(
            service_name="audio_notes",
            contributors=["gpt-4o-transcribe", "gpt-4o-mini"],
            used_local_processing=False,
            last_rendered_footer="f2",
        )

        variants = await service.get_service_footer_variants("audio_notes")
        keys = sorted(variants.keys())
        assert keys == [
            "audio_notes|local|argos+small",
            "audio_notes|remote|gpt-4o-mini+gpt-4o-transcribe",
        ]

    asyncio.run(_run())


def test_unknown_service_is_not_persisted_or_returned_as_known() -> None:
    async def _run() -> None:
        service, _ = _build_footer_service()
        await service.record_service_footer_profile(
            service_name="unknown",
            contributors=[],
            used_local_processing=True,
            last_rendered_footer="fallback",
        )
        embed = discord.Embed(title="x")
        await service.apply(embed, default_service_name="unknown")

        assert await service.get_known_services() == []
        assert await service.get_service_footer_profile("unknown") is None
        assert await service.get_service_footer_variants("unknown") == {}

    asyncio.run(_run())


def test_footer_service_render_footer_mixed_ai_and_local_processing_keeps_clean_ai_wording() -> None:
    async def _run() -> None:
        service, _ = _build_footer_service()
        await service.set_version("dev6")
        await service.set_global_phrase("In via di sviluppo.")
        footer, _ = await service.render_footer(
            service_name="riassunto",
            contributors=["qwen2.5"],
            used_local_processing=True,
        )
        assert footer == "Barcellometro dev6 · In via di sviluppo. · Dati elaborati con qwen2.5"
        assert "e fallback" + " locale" not in footer

    asyncio.run(_run())


def test_footer_service_render_footer_orders_version_phrase_then_processing() -> None:
    async def _run() -> None:
        service, _ = _build_footer_service()
        await service.set_version("dev7.1")
        await service.set_global_phrase("Sempre acceso.")

        footer, phrase = await service.render_footer(
            service_name="status",
            contributors=["llama3.2"],
            used_local_processing=False,
        )

        assert phrase == "Sempre acceso."
        assert footer == "Barcellometro dev7.1 · Sempre acceso. · Dati elaborati con llama3.2"

    asyncio.run(_run())


def test_footer_service_render_footer_with_configured_phrase_and_no_contributors_keeps_brand_then_phrase() -> None:
    async def _run() -> None:
        service, _ = _build_footer_service()
        await service.set_version("dev8")
        await service.set_global_phrase("Sempre acceso.")

        footer, phrase = await service.render_footer(
            service_name="status",
            contributors=[],
            used_local_processing=True,
        )

        assert phrase == "Sempre acceso."
        assert footer == "Barcellometro dev8 · Sempre acceso."
        assert "Dati elaborati con" not in footer

    asyncio.run(_run())


def test_footer_service_render_footer_without_phrase_or_contributors_keeps_only_brand() -> None:
    async def _run() -> None:
        service, _ = _build_footer_service()
        await service.set_version("dev7.1")

        footer, phrase = await service.render_footer(
            service_name="status",
            contributors=[],
            used_local_processing=True,
        )

        assert phrase is None
        assert footer == "Barcellometro dev7.1"
        assert "In via di sviluppo." not in footer
        assert "Dati elaborati con" not in footer
        assert "Dati elaborati" + " in loco" not in footer
        assert " ·  · " not in footer

    asyncio.run(_run())


def test_footer_service_render_footer_with_phrase_and_no_contributors_skips_processing_segment() -> None:
    async def _run() -> None:
        service, _ = _build_footer_service()
        await service.set_version("dev8")
        await service.set_global_phrase("In via di sviluppo.")

        footer, phrase = await service.render_footer(
            service_name="status",
            contributors=[],
            used_local_processing=True,
        )

        assert phrase == "In via di sviluppo."
        assert footer == "Barcellometro dev8 · In via di sviluppo."
        assert "Dati elaborati con" not in footer
        assert "Dati elaborati" + " in loco" not in footer
        assert " ·  · " not in footer

    asyncio.run(_run())


def test_footer_service_render_footer_shows_processing_only_when_contributors_exist() -> None:
    async def _run() -> None:
        service, _ = _build_footer_service()
        await service.set_version("dev8")

        with_contributors, _ = await service.render_footer(
            service_name="status",
            contributors=["llama3.2"],
            used_local_processing=False,
        )
        without_contributors, _ = await service.render_footer(
            service_name="status",
            contributors=[],
            used_local_processing=False,
        )

        assert with_contributors == "Barcellometro dev8 · Dati elaborati con llama3.2"
        assert without_contributors == "Barcellometro dev8"
        assert "In via di sviluppo." not in with_contributors
        assert "In via di sviluppo." not in without_contributors
        assert "Dati elaborati con llama3.2" in with_contributors
        assert "Dati elaborati con" not in without_contributors
        assert "Dati elaborati" + " in loco" not in without_contributors

    asyncio.run(_run())


def test_footer_service_render_footer_minimal_without_phrase_keeps_only_brand() -> None:
    async def _run() -> None:
        service, _ = _build_footer_service()
        await service.set_version("dev9")

        footer, phrase = await service.render_footer(
            service_name="status",
            contributors=[],
            used_local_processing=True,
            minimal=True,
        )

        assert phrase is None
        assert footer == "Barcellometro dev9"
        assert "In via di sviluppo." not in footer
        assert "Dati elaborati con" not in footer

    asyncio.run(_run())


def test_footer_service_render_footer_minimal_with_contributors_matches_standard_rules() -> None:
    async def _run() -> None:
        service, _ = _build_footer_service()
        await service.set_version("dev9")

        footer, phrase = await service.render_footer(
            service_name="status",
            contributors=["llama3.2"],
            used_local_processing=False,
            minimal=True,
        )

        assert phrase is None
        assert footer == "Barcellometro dev9 · Dati elaborati con llama3.2"
        assert "In via di sviluppo." not in footer

    asyncio.run(_run())


def test_global_template_reset_removes_custom_value() -> None:
    async def _run() -> None:
        service, database = _build_footer_service()
        await service.set_version("1.2.3")
        await service.set_global_phrase("Frase custom")

        await service.set_version(None)
        await service.set_global_phrase(None)

        assert await service.get_version() is None
        assert await service.get_global_phrase() is None
        assert "footer.version" not in database.settings
        assert "footer.global_phrase" not in database.settings

    asyncio.run(_run())


def test_service_template_reset_removes_custom_value() -> None:
    async def _run() -> None:
        service, database = _build_footer_service()
        await service.set_service_phrase("riassunto", "Frase servizio")

        await service.set_service_phrase("riassunto", None)

        assert (await service.get_service_phrases()).get("riassunto") is None
        assert "footer.service_phrase.riassunto" not in database.settings

    asyncio.run(_run())


def test_footer_render_does_not_show_custom_phrase_after_global_reset() -> None:
    async def _run() -> None:
        service, _ = _build_footer_service()
        await service.set_version("dev10")
        await service.set_global_phrase("Frase custom")
        await service.set_global_phrase(None)

        footer, phrase = await service.render_footer(
            service_name="riassunto",
            contributors=["gpt-4o-mini"],
            used_local_processing=False,
        )

        assert phrase is None
        assert footer == "Barcellometro dev10 · Dati elaborati con gpt-4o-mini"
        assert "Frase custom" not in footer

    asyncio.run(_run())


def test_footer_render_does_not_show_custom_phrase_after_service_reset() -> None:
    async def _run() -> None:
        service, _ = _build_footer_service()
        await service.set_version("dev10")
        await service.set_global_phrase("Fallback globale")
        await service.set_service_phrase("riassunto", "Frase servizio")
        await service.set_service_phrase("riassunto", None)

        footer, phrase = await service.render_footer(
            service_name="riassunto",
            contributors=["gpt-4o-mini"],
            used_local_processing=False,
        )

        assert phrase == "Fallback globale"
        assert footer == "Barcellometro dev10 · Fallback globale · Dati elaborati con gpt-4o-mini"
        assert "Frase servizio" not in footer

    asyncio.run(_run())


def test_reset_commands_do_not_raise_attribute_error_on_database_commit() -> None:
    class _DatabaseWithoutCommit(_FakeDatabase):
        async def execute(self, _query: str, _params: tuple[str, ...]) -> None:
            raise AssertionError("footer reset should use delete_setting, not raw execute")

    async def _run() -> None:
        database = _DatabaseWithoutCommit()
        service = FooterService(database)
        await service.set_global_phrase("Frase custom")
        await service.set_service_phrase("riassunto", "Frase servizio")

        await service.set_global_phrase(None)
        await service.set_service_phrase("riassunto", None)

        assert await service.get_global_phrase() is None
        assert (await service.get_service_phrases()).get("riassunto") is None

    asyncio.run(_run())


def test_normalize_footer_thumbnail_supports_static_custom_emoji() -> None:
    assert normalize_footer_thumbnail("<:melons:1475962151502876695>") == "https://cdn.discordapp.com/emojis/1475962151502876695.png"


def test_normalize_footer_thumbnail_supports_animated_custom_emoji() -> None:
    assert normalize_footer_thumbnail("<a:pulse:1475962151502876696>") == "https://cdn.discordapp.com/emojis/1475962151502876696.gif"


def test_normalize_footer_thumbnail_keeps_remote_image_url() -> None:
    assert normalize_footer_thumbnail("https://example.com/icon.png") == "https://example.com/icon.png"


def test_normalize_footer_thumbnail_rejects_invalid_value() -> None:
    with pytest.raises(InvalidFooterThumbnailError):
        normalize_footer_thumbnail("not-a-thumbnail")


def test_footer_service_apply_uses_service_specific_thumbnail() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="emoji")
        attach_footer_meta(embed, service_name="status", contributors=[], used_local_processing=False)
        service, _ = _build_footer_service()
        await service.set_version("dev7.1")
        await service.set_global_phrase("In via di sviluppo.")
        await service.set_service_thumbnail("status", "<:melons:1475962151502876695>")

        await service.apply(embed)

        assert embed.footer.text == "Barcellometro dev7.1 · In via di sviluppo."
        assert embed.footer.icon_url == "https://cdn.discordapp.com/emojis/1475962151502876695.png"

    asyncio.run(_run())


def test_footer_service_apply_falls_back_to_global_thumbnail() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="emoji")
        attach_footer_meta(embed, service_name="riassunto", contributors=[], used_local_processing=False)
        service, _ = _build_footer_service()
        await service.set_version("dev7.1")
        await service.set_global_phrase("Sempre acceso")
        await service.set_global_thumbnail("<a:pulse:1475962151502876696>")

        await service.apply(embed)

        assert embed.footer.text == "Barcellometro dev7.1 · Sempre acceso"
        assert embed.footer.icon_url == "https://cdn.discordapp.com/emojis/1475962151502876696.gif"

    asyncio.run(_run())


def test_footer_service_apply_keeps_explicit_footer_icon_over_configured_thumbnails() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="icon precedence")
        attach_footer_meta(
            embed,
            service_name="status",
            contributors=[],
            used_local_processing=False,
            footer_icon_url="https://example.com/icon.png",
        )
        service, _ = _build_footer_service()
        await service.set_version("dev7.1")
        await service.set_global_phrase("Sempre acceso")
        await service.set_global_thumbnail("<:melons:1475962151502876695>")
        await service.set_service_thumbnail("status", "<a:pulse:1475962151502876696>")

        await service.apply(embed)

        assert embed.footer.text == "Barcellometro dev7.1 · Sempre acceso"
        assert embed.footer.icon_url == "https://example.com/icon.png"

    asyncio.run(_run())


def test_footer_service_apply_preserves_unicode_emoji_in_footer_text() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="unicode")
        attach_footer_meta(embed, service_name="status", contributors=[], used_local_processing=False)
        service, _ = _build_footer_service()
        await service.set_version("dev7.1")
        await service.set_global_phrase("Sempre acceso 🍉")

        await service.apply(embed)

        assert embed.footer.text == "Barcellometro dev7.1 · Sempre acceso 🍉"
        assert embed.footer.icon_url is None

    asyncio.run(_run())


def test_footer_service_apply_does_not_promote_custom_emoji_from_phrase() -> None:
    async def _run() -> None:
        embed = discord.Embed(title="custom-text")
        attach_footer_meta(embed, service_name="status", contributors=[], used_local_processing=False)
        service, _ = _build_footer_service()
        await service.set_version("dev7.1")
        await service.set_global_phrase("Sempre acceso <:melons:1475962151502876695>")

        await service.apply(embed)

        assert embed.footer.text == "Barcellometro dev7.1 · Sempre acceso <:melons:1475962151502876695>"
        assert embed.footer.icon_url is None

    asyncio.run(_run())
