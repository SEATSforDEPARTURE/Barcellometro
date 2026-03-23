from __future__ import annotations

import asyncio
from types import SimpleNamespace

import discord

from app.services.footer import FooterService, attach_footer_meta, get_footer_meta
from app.shared.discord.command_embeds import build_command_embed, normalize_display_command_context
from app.shared.discord.footer_pipeline import finalize_embed


def test_normalize_display_context_triggers_phrases_template_global_show() -> None:
    context = normalize_display_command_context(
        top_level="admin",
        subcommand_path="triggers phrases template_global_show",
        visual_top_level="triggers",
    )

    assert context.visual_title == "TRIGGERS"
    assert context.visual_subtitle == "PHRASES TEMPLATE_GLOBAL_SHOW"


def test_normalize_display_context_qna_limits_with_parameter() -> None:
    context = normalize_display_command_context(
        top_level="admin",
        subcommand_path="qna limits_show",
        visual_top_level="qna",
        subtitle_args=["parameter:base"],
    )

    assert context.visual_title == "QNA"
    assert context.visual_subtitle == "LIMITS_SHOW BASE"
    assert "QNA" not in context.visual_subtitle


def test_normalize_display_context_campagne_prompt_status() -> None:
    context = normalize_display_command_context(
        top_level="admin",
        subcommand_path="campagne prompt status",
        visual_top_level="campagne",
    )

    assert context.visual_title == "CAMPAGNE"
    assert context.visual_subtitle == "PROMPT STATUS"


def test_normalize_display_context_admin_command_keeps_admin_title() -> None:
    context = normalize_display_command_context(
        top_level="admin",
        subcommand_path="retention on",
    )

    assert context.visual_title == "ADMIN"
    assert context.visual_subtitle == "RETENTION ON"


def test_build_command_embed_uses_visual_top_level_for_moderazione() -> None:
    async def _get_version() -> None:
        return None

    embed = asyncio.run(
        build_command_embed(
            top_level="admin",
            subcommand_path="moderazione users tempban_list",
            visual_top_level="moderazione",
            footer_service=SimpleNamespace(get_version=_get_version),
        )
    )

    assert embed.title == "🛠️ MODERAZIONE"
    assert embed.description.startswith("**ℹ️ USERS TEMPBAN_LIST**")
    assert get_footer_meta(embed) is not None
    assert get_footer_meta(embed).service_name == "status"


def test_build_command_embed_finalize_keeps_only_brand_without_configured_phrase() -> None:
    class _FooterService:
        async def get_version(self) -> str | None:
            return "dev7.1"

        async def is_enabled(self) -> bool:
            return True

        async def apply(self, embed: discord.Embed, *, default_service_name: str = "unknown") -> discord.Embed:
            embed.set_footer(text="Barcellometro dev7.1")
            return embed

    async def _run() -> discord.Embed:
        footer_service = _FooterService()
        embed = await build_command_embed(
            top_level="riassunto",
            subcommand_path="riassunto oggi",
            footer_service=footer_service,
        )
        await finalize_embed(embed, footer_service, default_service_name="riassunto")
        return embed

    embed = asyncio.run(_run())

    assert embed.footer.text == "Barcellometro dev7.1"


def test_build_command_embed_omits_top_level_duplication_for_parameterized_command() -> None:
    embed = asyncio.run(
        build_command_embed(
            top_level="admin",
            subcommand_path="qna limits_show",
            visual_top_level="qna",
            subtitle_args=["base"],
            lines=[("tier", "base")],
            footer_service=None,
        )
    )

    assert embed.title == "❓ QNA"
    assert embed.description.startswith("**ℹ️ LIMITS_SHOW BASE**")
    assert "QNA LIMITS_SHOW BASE" not in (embed.description or "")


def test_build_command_embed_uses_readable_user_name_in_subtitle() -> None:
    embed = asyncio.run(
        build_command_embed(
            top_level="admin",
            subcommand_path="qna bonus_show",
            visual_top_level="qna",
            subtitle_args=[SimpleNamespace(display_name="Mario Rossi", global_name=None, name="mario")],
            lines=[("user", "<@123>")],
            footer_service=None,
        )
    )

    assert embed.title == "❓ QNA"
    assert embed.description.startswith("**ℹ️ BONUS_SHOW MARIO ROSSI**")
    assert "<@123>" not in (embed.description or "")


def test_build_command_embed_admin_standard_footer_omits_invented_phrase() -> None:
    class _FooterService:
        async def get_version(self) -> str | None:
            return "dev7.1"

        async def is_enabled(self) -> bool:
            return True

        async def apply(self, embed: discord.Embed, *, default_service_name: str = "unknown") -> discord.Embed:
            embed.set_footer(text="Barcellometro dev7.1")
            return embed

    async def _run() -> discord.Embed:
        footer_service = _FooterService()
        embed = await build_command_embed(
            top_level="admin",
            subcommand_path="footer template_global_show",
            footer_service=footer_service,
            footer_service_name="status",
            lines=[("Phrase", "In via di sviluppo.")],
        )
        await finalize_embed(embed, footer_service, default_service_name="status")
        return embed

    embed = asyncio.run(_run())

    assert embed.footer.text == "Barcellometro dev7.1"


def test_build_command_embed_formats_period_subtitle_for_riassunto_ultimi() -> None:
    embed = asyncio.run(
        build_command_embed(
            top_level="riassunto",
            subcommand_path="riassunto ultimi",
            subtitle_args=[1, "ore"],
            footer_service=None,
        )
    )

    assert embed.title == "🗒️ RIASSUNTO"
    assert embed.description.startswith("**ℹ️ ULTIMA ORA**")


def test_build_command_embed_formats_period_subtitle_for_attivita_ultimi() -> None:
    embed = asyncio.run(
        build_command_embed(
            top_level="admin",
            visual_top_level="attivita",
            subcommand_path="attivita ultimi",
            subtitle_args=[1, "minuti"],
            footer_service=None,
        )
    )

    assert embed.title == "📈 ATTIVITA"
    assert embed.description.startswith("**ℹ️ ULTIMO MINUTO**")


def test_build_command_embed_formats_range_subtitle_centrally() -> None:
    embed = asyncio.run(
        build_command_embed(
            top_level="riassunto",
            subcommand_path="riassunto range",
            subtitle_args=["20/03/2026 10:15", "21/03/2026 11:45"],
            footer_service=None,
        )
    )

    assert embed.title == "🗒️ RIASSUNTO"
    assert embed.description.startswith("**ℹ️ DAL 20/03 10:15 AL 21/03 11:45**")


def test_build_command_embed_uses_real_top_level_for_resocontocanale() -> None:
    embed = asyncio.run(
        build_command_embed(
            top_level="resocontocanale",
            subcommand_path="resocontocanale status",
            footer_service=None,
        )
    )

    assert embed.title == "📓 RESOCONTOCANALE"
    assert embed.description.startswith("**ℹ️ STATUS**")
    assert "RESOCONTO STATUS" not in (embed.description or "")


def test_build_command_embed_strips_ugly_prefixes_from_narrative_bullets() -> None:
    embed = asyncio.run(
        build_command_embed(
            top_level="riassunto",
            subcommand_path="riassunto oggi",
            lines=[
                ("dettaglio", "Ti ho inviato il riassunto in DM."),
                ("warning", "Phrase entry #1 not found."),
                ("result", "updated"),
                ("error", "Qualcosa è andato storto."),
            ],
            kind="warning",
            footer_service=None,
        )
    )

    description = embed.description or ""
    assert "Dettaglio:" not in description
    assert "Warning:" not in description
    assert "Result:" not in description
    assert "Error:" not in description
    assert "• Ti ho inviato il riassunto in DM." in description
    assert "• Phrase entry #1 not found." in description
    assert "• Updated." in description
    assert "• Qualcosa è andato storto." in description


def test_build_command_embed_deduplicates_identity_lines_already_in_subtitle() -> None:
    embed = asyncio.run(
        build_command_embed(
            top_level="admin",
            visual_top_level="qna",
            subcommand_path="qna bonus_show",
            subtitle_args=[SimpleNamespace(display_name="Mario", global_name=None, name="mario")],
            lines=[("user", "<@123>"), ("bonus", 3), ("expires_at", "2026-03-21 10:00 UTC")],
            footer_service=None,
        )
    )

    description = embed.description or ""
    assert description.startswith("**ℹ️ BONUS_SHOW MARIO**")
    assert "• User:" not in description
    assert "<@123>" not in description
    assert "• Bonus: **3**" in description


def test_build_command_embed_deduplicates_tier_line_already_in_subtitle() -> None:
    embed = asyncio.run(
        build_command_embed(
            top_level="admin",
            visual_top_level="qna",
            subcommand_path="qna limits_show",
            subtitle_args=["base"],
            lines=[("tier", "base"), ("limit", 5)],
            footer_service=None,
        )
    )

    description = embed.description or ""
    assert description.startswith("**ℹ️ LIMITS_SHOW BASE**")
    assert "Tier: **base**" not in description
    assert "• Limit: **5**" in description


def test_build_command_embed_skips_long_unreadable_subtitle_input() -> None:
    embed = asyncio.run(
        build_command_embed(
            top_level="admin",
            visual_top_level="triggers",
            subcommand_path="triggers phrases template_user_set",
            subtitle_args=["x" * 120],
            lines=[("user", "Mario"), ("text", "x" * 120)],
            footer_service=None,
        )
    )

    assert embed.title == "⚡ TRIGGERS"
    assert embed.description.startswith("**ℹ️ PHRASES TEMPLATE_USER_SET**")
    assert "X" * 120 not in (embed.description or "")


def test_build_command_embed_never_reuses_subtitle_icon_for_info_sections() -> None:
    embed = asyncio.run(
        build_command_embed(
            top_level="admin",
            visual_top_level="qna",
            subcommand_path="qna limits_show",
            sections=[{"title": "Limits", "lines": [("max", 5)], "emoji": "ℹ️"}],
            footer_service=None,
        )
    )

    description = embed.description or ""
    assert description.startswith("**ℹ️ LIMITS_SHOW**")
    assert "**ℹ️ LIMITS**" not in description
    assert "**📊 LIMITS**" in description


def test_build_command_embed_never_reuses_subtitle_icon_for_standard_kinds() -> None:
    scenarios = {
        "success": ("✅", "**📋 RESULT**"),
        "warning": ("⚠️", "**📋 WARNINGS**"),
        "error": ("❌", "**🧩 ERRORS**"),
    }

    for kind, (subtitle_emoji, expected_section_header) in scenarios.items():
        embed = asyncio.run(
            build_command_embed(
                top_level="admin",
                visual_top_level="qna",
                subcommand_path="qna status",
                kind=kind,
                sections=[{"title": expected_section_header.split(' ', 1)[1].strip('*'), "lines": ["done"], "emoji": subtitle_emoji}],
                footer_service=None,
            )
        )

        description = embed.description or ""
        assert description.startswith(f"**{subtitle_emoji} STATUS**")
        assert expected_section_header in description
        assert f"**{subtitle_emoji} {expected_section_header.split(' ', 1)[1].strip('*')}**" not in description


def test_build_command_embed_uses_official_kind_mapping_for_all_standard_types() -> None:
    scenarios = {
        "success": ("✅", 0x57F287),
        "warning": ("⚠️", 0xFEE75C),
        "error": ("❌", 0xED4245),
        "info": ("ℹ️", 0x3498DB),
    }

    for kind, (emoji, color) in scenarios.items():
        embed = asyncio.run(
            build_command_embed(
                top_level="admin",
                visual_top_level="qna",
                subcommand_path="qna status",
                kind=kind,
                footer_service=None,
            )
        )

        assert embed.description == f"**{emoji} STATUS**"
        assert embed.colour.value == color


def test_build_command_embed_keeps_blank_line_between_subtitle_and_body() -> None:
    embed = asyncio.run(
        build_command_embed(
            top_level="admin",
            visual_top_level="qna",
            subcommand_path="qna status",
            lines=[("detail", "Prima riga."), ("detail", "Seconda riga.")],
            compact_lines=True,
            footer_service=None,
        )
    )

    assert embed.description == "**ℹ️ STATUS**\n\n• Prima riga.\n• Seconda riga."


def test_build_command_embed_strips_duplicate_kind_emoji_from_body_lines() -> None:
    embed = asyncio.run(
        build_command_embed(
            top_level="admin",
            visual_top_level="qna",
            subcommand_path="qna set",
            kind="success",
            lines=[("detail", "✅ Operazione completata."), ("status", "✅ enabled")],
            footer_service=None,
        )
    )

    description = embed.description or ""
    assert description.startswith("**✅ SET**\n\n")
    assert "• ✅ Operazione completata." not in description
    assert "• Operazione completata." in description
    assert "• Status: **enabled**" in description


class _FooterDb:
    def __init__(self) -> None:
        self.settings: dict[str, str] = {}

    async def get_setting(self, key: str) -> str | None:
        return self.settings.get(key)

    async def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value

    async def fetchall(self, _query: str, _params: tuple[str, ...]):
        return []


def _build_footer_service() -> FooterService:
    return FooterService(_FooterDb())


def test_build_command_embed_admin_embed_includes_global_phrase() -> None:
    async def _run() -> discord.Embed:
        footer_service = _build_footer_service()
        await footer_service.set_version('dev7.1')
        await footer_service.set_global_phrase('In via di sviluppo')
        embed = await build_command_embed(
            top_level='admin',
            subcommand_path='footer template_global_show',
            footer_service=footer_service,
            footer_service_name='status',
            lines=[('Phrase', 'In via di sviluppo')],
        )
        await finalize_embed(embed, footer_service, default_service_name='status')
        return embed

    embed = asyncio.run(_run())

    assert embed.footer is not None
    assert embed.footer.text == 'Barcellometro dev7.1 · In via di sviluppo'


def test_build_command_embed_default_footer_mode_uses_centralized_meta_pipeline() -> None:
    async def _run() -> discord.Embed:
        footer_service = _build_footer_service()
        await footer_service.set_version('dev7.1')
        await footer_service.set_global_phrase('Sempre acceso')
        embed = await build_command_embed(
            top_level='admin',
            subcommand_path='status',
            footer_service=footer_service,
            footer_service_name='status',
        )
        await finalize_embed(embed, footer_service, default_service_name='status')
        return embed

    embed = asyncio.run(_run())

    assert embed.footer is not None
    assert embed.footer.text == 'Barcellometro dev7.1 · Sempre acceso'


def test_build_command_embed_config_embed_includes_global_phrase() -> None:
    async def _run() -> discord.Embed:
        footer_service = _build_footer_service()
        await footer_service.set_version('dev7.1')
        await footer_service.set_global_phrase('Footer globale')
        embed = await build_command_embed(
            top_level='admin',
            subcommand_path='audionotes config_show',
            footer_service=footer_service,
            footer_service_name='audio_notes',
            lines=[('Queue Max', 50)],
        )
        await finalize_embed(embed, footer_service, default_service_name='audio_notes')
        return embed

    embed = asyncio.run(_run())

    assert embed.footer is not None
    assert embed.footer.text == 'Barcellometro dev7.1 · Footer globale'


def test_finalize_embed_without_footer_service_sets_brand_version_footer() -> None:
    async def _run() -> discord.Embed:
        embed = await build_command_embed(
            top_level="riassunto",
            subcommand_path="riassunto oggi",
            footer_service=None,
        )
        await finalize_embed(embed, None, default_service_name="riassunto")
        return embed

    embed = asyncio.run(_run())

    assert embed.footer is not None
    assert embed.footer.text is not None
    assert embed.footer.text.startswith("Barcellometro ")
    assert embed.footer.text != "Barcellometro"
    assert "Dati elaborati con" not in embed.footer.text



def test_finalize_embed_without_footer_service_keeps_contributor_segment() -> None:
    async def _run() -> discord.Embed:
        embed = discord.Embed(title="Status")
        attach_footer_meta(
            embed,
            service_name="status",
            contributors=["llama3.2"],
            used_local_processing=False,
        )
        await finalize_embed(embed, None, default_service_name="status")
        return embed

    embed = asyncio.run(_run())

    assert embed.footer is not None
    assert embed.footer.text is not None
    assert embed.footer.text.startswith("Barcellometro ")
    assert embed.footer.text != "Barcellometro"
    assert embed.footer.text.endswith("Dati elaborati con llama3.2")


def test_build_command_embed_uses_embed_namespace_title_for_footer_show() -> None:
    embed = asyncio.run(
        build_command_embed(
            top_level="embed",
            subcommand_path="footer template_global_show",
            sections=[],
            footer_service=None,
        )
    )

    assert embed.title == "📦 EMBED"
    assert embed.description.startswith("**ℹ️ FOOTER TEMPLATE_GLOBAL_SHOW**")


def test_build_command_embed_uses_service_name_in_embed_footer_subtitle_without_body_duplication() -> None:
    embed = asyncio.run(
        build_command_embed(
            top_level="embed",
            subcommand_path="footer template_service_show",
            subtitle_args=["riassunto"],
            lines=[("phrase", "Servizio"), ("thumbnail", "https://example.com/service.png")],
            footer_service=None,
        )
    )

    assert embed.title == "📦 EMBED"
    assert embed.description.startswith("**ℹ️ FOOTER TEMPLATE_SERVICE_SHOW RIASSUNTO**")
    assert "• Service:" not in (embed.description or "")
