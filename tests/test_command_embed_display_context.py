from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.shared.discord.command_embeds import build_command_embed, normalize_display_command_context


def test_normalize_display_context_frasi_template_global_show() -> None:
    context = normalize_display_command_context(
        top_level="admin",
        subcommand_path="frasi template_global_show",
        visual_top_level="frasi",
    )

    assert context.visual_title == "FRASI"
    assert context.visual_subtitle == "TEMPLATE_GLOBAL_SHOW"


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
    assert embed.description.startswith("**🛠️ USERS TEMPBAN_LIST**")


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
    assert embed.description.startswith("**🛠️ LIMITS_SHOW BASE**")
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
    assert embed.description.startswith("**🛠️ BONUS_SHOW MARIO ROSSI**")
    assert "<@123>" in (embed.description or "")


def test_build_command_embed_formats_period_subtitle_for_riassunto_ultimi() -> None:
    embed = asyncio.run(
        build_command_embed(
            top_level="riassunto",
            subcommand_path="riassunto ultimi",
            subtitle_args=[30, "minuti"],
            footer_service=None,
        )
    )

    assert embed.title == "🗒️ RIASSUNTO"
    assert embed.description.startswith("**🛠️ ULTIMI 30 MINUTI**")


def test_build_command_embed_formats_period_subtitle_for_attivita_ultimi() -> None:
    embed = asyncio.run(
        build_command_embed(
            top_level="admin",
            visual_top_level="attivita",
            subcommand_path="attivita ultimi",
            subtitle_args=[7, "giorni"],
            footer_service=None,
        )
    )

    assert embed.title == "📈 ATTIVITA"
    assert embed.description.startswith("**🛠️ ULTIMI 7 GIORNI**")


def test_build_command_embed_skips_long_unreadable_subtitle_input() -> None:
    embed = asyncio.run(
        build_command_embed(
            top_level="admin",
            visual_top_level="frasi",
            subcommand_path="frasi template_user_set",
            subtitle_args=["x" * 120],
            lines=[("user", "Mario"), ("text", "x" * 120)],
            footer_service=None,
        )
    )

    assert embed.title == "💬 FRASI"
    assert embed.description.startswith("**🛠️ TEMPLATE_USER_SET**")
    assert "X" * 120 not in (embed.description or "")
