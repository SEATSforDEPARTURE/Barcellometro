from __future__ import annotations

import asyncio
import ast
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime
import re

import discord

from app.renderers.activity_report_renderer import build_daily_activity_embeds
from app.renderers.aura_renderer import AuraRenderPayload, AuraTrendInfo, build_aura_embeds
from app.renderers.channel_summary import MessageMeta, QuoteRenderItem, build_channel_summary_embeds
from app.services.barcello_service import BarcelloResult
from app.services.content_summary_service import SummaryItem, SummaryResult
from app.shared.discord.command_embeds import build_command_embed, build_command_embeds
from app.shared.discord.embed_body import (
    BodyFormatOptions,
    apply_standard_body_helpers,
    format_standard_description,
    format_standard_field_name,
    format_standard_title,
)

_STANDARD_TITLE_RE = re.compile(r"^(?:(?P<prefix>\S+)\s+)?__\*\*(?P<inner>.+)\*\*__$")
_STANDARD_FIELD_RE = re.compile(r"^(?:(?P<prefix>\S+)\s+)?__\*\*(?P<inner>.+)\*\*__$")

_CANONICAL_BODY_HELPERS = {
    "format_standard_title",
    "format_standard_description",
    "format_standard_field_name",
    "apply_standard_body_helpers",
}

_KNOWN_SUSPECT_FILES = [
    Path("app/renderers/user_activity_report_renderer.py"),
    Path("app/renderers/channel_summary.py"),
    Path("app/renderers/server_activity_report_renderer.py"),
    Path("app/renderers/activity_report_renderer.py"),
    Path("app/renderers/activity_dm_report_renderer.py"),
    Path("app/renderers/aura_renderer.py"),
    Path("app/services/campaign_content_formatter.py"),
    Path("app/plugins/commands_modular/barcello.py"),
    Path("app/plugins/commands_modular/attivita.py"),
    Path("app/plugins/commands_modular/resoconto.py"),
]


def _extract_inner_standard_text(value: str, *, field: bool) -> str:
    pattern = _STANDARD_FIELD_RE if field else _STANDARD_TITLE_RE
    match = pattern.match(value)
    assert match is not None, f"Formato non standard: {value!r}"
    return match.group("inner").strip()


def assert_standard_title(title: str | None) -> None:
    assert title is not None and title.strip(), "Titolo embed mancante"
    rendered = title.strip()
    inner = _extract_inner_standard_text(rendered, field=False)
    assert any(ch.isalpha() for ch in inner), f"Titolo senza contenuto alfabetico: {title!r}"
    assert inner.upper() == inner, f"Titolo non uppercase: {title!r}"


def assert_standard_field_name(name: str | None) -> None:
    assert name is not None and name.strip(), "Field name mancante"
    rendered = name.strip()
    inner = _extract_inner_standard_text(rendered, field=True)
    assert inner, f"Field name senza contenuto: {name!r}"
    assert inner.upper() == inner, f"Field name non uppercase: {name!r}"


def assert_standard_description(description: str | None, *, strict: bool, has_fields: bool = False) -> None:
    if description is None:
        return
    text = description.strip()
    assert text, "Description vuota"

    if strict:
        assert text.startswith("*") and text.endswith("*"), f"Description strict non in corsivo: {description!r}"
        if has_fields:
            assert description.endswith("\n\n"), "Description strict deve chiudere con riga vuota prima dei field"
    else:
        cleaned = text.lstrip("*_`> ")
        first_token = cleaned.split(maxsplit=1)[0] if cleaned else ""
        if first_token:
            assert not all(not c.isalnum() for c in first_token), (
                "Description non dovrebbe iniziare da faccina/simbolo grezzo: "
                f"{description!r}"
            )


def _all_embed_python_files() -> list[Path]:
    return [
        path
        for path in Path("app").rglob("*.py")
        if path.is_file() and "__pycache__" not in path.parts
    ]


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _file_uses_body_helpers(source: str) -> bool:
    return any(f"{helper}(" in source for helper in _CANONICAL_BODY_HELPERS)


def _is_embed_ctor(call: ast.Call) -> bool:
    if isinstance(call.func, ast.Attribute):
        return isinstance(call.func.value, ast.Name) and call.func.value.id == "discord" and call.func.attr == "Embed"
    return False


def _is_string_literal(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _keyword_expr(call: ast.Call, key: str) -> ast.AST | None:
    for kw in call.keywords:
        if kw.arg == key:
            return kw.value
    return None


def _literal_text(node: ast.AST | None) -> str | None:
    if _is_string_literal(node):
        return str(node.value)
    return None


def _scan_embed_bypasses(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    issues: list[str] = []
    helper_used = _file_uses_body_helpers(source)
    embed_ctor_count = 0

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_embed_ctor(node):
            embed_ctor_count += 1
            title_expr = _keyword_expr(node, "title")
            title_text = _literal_text(title_expr)
            if title_text is not None:
                try:
                    assert_standard_title(title_text)
                except AssertionError as exc:
                    issues.append(f"{path}:{node.lineno} titolo manuale non standard: {exc}")

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_field":
            name_expr = _keyword_expr(node, "name")
            if name_expr is None and node.args:
                name_expr = node.args[0]
            name_text = _literal_text(name_expr)
            if name_text is not None:
                try:
                    assert_standard_field_name(name_text)
                except AssertionError as exc:
                    issues.append(f"{path}:{node.lineno} field name manuale non standard: {exc}")

    if embed_ctor_count >= 2 and not helper_used:
        issues.append(
            f"{path}: uso intensivo di discord.Embed ({embed_ctor_count}) senza helper body canonici "
            f"{sorted(_CANONICAL_BODY_HELPERS)}"
        )

    return issues


def test_standard_body_helpers_contract() -> None:
    title = format_standard_title("resoconto canale", emoji="📓")
    assert_standard_title(title)

    field = format_standard_field_name("Trend", emoji="📈")
    assert_standard_field_name(field)

    description = format_standard_description("Riepilogo operativo", italic=True, blank_line_before_fields=True)
    assert_standard_description(description, strict=True, has_fields=True)

    embed = discord.Embed(title="report runtime", description="Body runtime")
    embed.add_field(name="Trend", value="ok", inline=False)
    apply_standard_body_helpers(
        embed,
        options=BodyFormatOptions(
            title_emoji="📊",
            title_uppercase=True,
            description_italic=True,
            blank_line_before_fields=True,
            format_field_names=True,
        ),
    )
    assert_standard_title(embed.title)
    assert_standard_description(embed.description, strict=True, has_fields=True)
    assert_standard_field_name(embed.fields[0].name)


def test_command_embeds_respect_body_contract() -> None:
    async def _run() -> None:
        embed = await build_command_embed(
            top_level="riassunto",
            subcommand_path="riassunto oggi",
            visual_top_level="channelsummary",
            lines=[("status", "ok")],
            sections=[{"title": "Dettagli", "lines": [("window", "oggi")]}],
            footer_service=None,
        )
        assert_standard_title(embed.title)
        assert_standard_description(embed.description, strict=False)

        many = await build_command_embeds(
            top_level="aura",
            subcommand_path="aura show",
            lines=[("utente", "Mario")],
            sections=[{"title": "metrics", "lines": [("score", 72)]}],
            footer_service=None,
        )
        assert len(many) >= 1
        for item in many:
            assert_standard_title(item.title)
            assert_standard_description(item.description, strict=False)

    asyncio.run(_run())


def test_embed_static_audit_detects_body_standard_bypasses() -> None:
    violations: list[str] = []
    for path in _all_embed_python_files():
        if "tests" in path.parts:
            continue
        violations.extend(_scan_embed_bypasses(path))

    assert not violations, "Bypass body standard rilevati:\n- " + "\n- ".join(sorted(violations))


def test_known_embed_builders_use_body_standard_helpers() -> None:
    violations: list[str] = []
    for path in _KNOWN_SUSPECT_FILES:
        violations.extend(_scan_embed_bypasses(path))

    assert not violations, (
        "File sospetti con bypass body standard:\n- "
        + "\n- ".join(sorted(violations))
        + "\nUsare helper centrali o output finale conforme."
    )


def _channel_summary_fixture() -> tuple[BarcelloResult, SummaryResult, dict[str, MessageMeta], dict[int, str], dict[int, str], dict[int, list[str]], list[QuoteRenderItem]]:
    bar = BarcelloResult(score=72, color="verde", trend={"delta": 3})
    m1 = SummaryItem(ts="2026-03-01T10:00:00+00:00", text="Mario avvia la discussione", author_id="1", message_ids=["10"])
    dyn = SummaryItem(ts="2026-03-01T11:00:00+00:00", text="Luigi approfondisce il tema", author_id="2", message_ids=["11"])
    summary = SummaryResult(
        themes=["community"],
        moments=[m1],
        quotes=[],
        dynamics=[dyn],
        degrade=[],
        invigorate=[],
        advice=["Tenere il ritmo."],
        metrics={},
        ai_status={},
    )
    index = {
        "10": MessageMeta(message_id="10", ts="2026-03-01T10:00:00+00:00", author_id="1"),
        "11": MessageMeta(message_id="11", ts="2026-03-01T11:00:00+00:00", author_id="2"),
    }
    quote_items = [
        QuoteRenderItem(
            message_id="10",
            ts="2026-03-01T10:00:00+00:00",
            quote_text="Messaggio simbolico",
            author_display="Mario",
        )
    ]
    return bar, summary, index, {id(m1): "10"}, {id(dyn): "11"}, {id(dyn): ["Luigi"]}, quote_items


def test_runtime_renderer_outputs_follow_body_standard() -> None:
    # channel_summary
    bar, summary, index, moment_primary, dynamic_primary, dynamic_names, quote_items = _channel_summary_fixture()
    channel_embeds = build_channel_summary_embeds(
        guild_id=1,
        channel_id=2,
        channel_name="generale",
        barcello_status=bar,
        barcello_line="Linea di sintesi",
        summary_result=summary,
        message_index=index,
        advice_bullets=["Coinvolgere nuovi utenti"],
        proverbio="Chi ben comincia è a metà dell'opera.",
        window_header="**🗓️ Oggi. Domenica, 1 Marzo 2026**",
        moment_primary=moment_primary,
        dynamic_primary=dynamic_primary,
        dynamic_names=dynamic_names,
        quote_render_items=quote_items,
    )

    # activity_report
    score = SimpleNamespace(messages_count=20, active_users_count=3, peak_hour_local=11, continuity_hours=7, score=68, emoji="🟢", label="INTENSA", trend_text="Trend ok")
    details = SimpleNamespace(score=score, top_active_users=[], inactive_users=[], advice_bullets=["Consiglio"])
    activity_embeds = build_daily_activity_embeds(
        guild=SimpleNamespace(id=1),
        guild_name="Server Test",
        channel_payloads=[{
            "channel": SimpleNamespace(name="generale"),
            "details": details,
            "active_non_bot": 3,
            "members_with_access": 10,
            "inactive_non_bot": 7,
            "peak_hour": 21,
            "silence_hour": 5,
            "continuity_hours": 7,
            "is_voice": False,
            "voice_sessions_count": 0,
            "voice_total_seconds": 0,
        }],
        server_summary={
            "active_non_bot": 3,
            "total_non_bot_members": 10,
            "label": "INTENSA",
            "score": 74,
            "trend_text": "Trend ok",
            "peak_hour": 20,
            "silence_hour": 4,
            "continuity_hours": 8,
        },
        period_label="oggi",
        window_start_dt=datetime(2026, 3, 1, 0, 0),
        window_end_dt=datetime(2026, 3, 1, 12, 0),
    )

    # aura
    aura_embeds = build_aura_embeds(
        profile_name="role1",
        aura_payload=AuraRenderPayload(
            username="Mario",
            server_name="Server Test",
            channel_name="generale",
            period_line="Ultime 24 ore",
            karma_server_percent=72,
            karma_channel_percent=61,
            server_points_total=120,
            channel_points_month=35,
            metrics_json='{"msg_count": 10, "unique_interactions": 3}',
            channel_metrics_json='{"msg_count": 3, "unique_interactions": 2}',
            ledger=[{"reason_code": "ondemand.aggregate", "total": 12}],
            archetype_metrics={"scores": {"scintilla": 41}},
            trend=AuraTrendInfo(
                server_direction="improving",
                server_comment="Trend positivo.",
                channel_direction="stable",
                channel_comment="Trend stabile.",
                server_delta=2,
                channel_delta=0,
            ),
        ),
        include_sections=["details.missions"],
        details_title_prefix="🗒️ DETTAGLI AURA",
        details_embeds_max=2,
        ledger_lines=["👍 **+5 P.A.** test"],
    )

    for embed in [*channel_embeds[:2], *activity_embeds[:2], *aura_embeds[:2]]:
        assert_standard_title(embed.title)
        assert_standard_description(embed.description, strict=False, has_fields=bool(embed.fields))
        for field in embed.fields:
            assert_standard_field_name(field.name)
