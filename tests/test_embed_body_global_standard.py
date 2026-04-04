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

_STANDARD_TITLE_RE = re.compile(r"^(?P<prefix>\S+)\s+__\*\*(?P<inner>.+)\*\*__$")
_STANDARD_FIELD_RE = re.compile(r"^(?P<prefix>\S+)\s+__\*\*(?P<inner>.+)\*\*__$")

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

_ILLEGAL_DESCRIPTION_SECTION_PATTERNS = [
    re.compile(r"(?mi)^\s*[^\w\s]\s+\*\*[^\n*]{2,}\*\*\s*$"),
    re.compile(r"(?mi)^\s*👇\s*\*\*\s*RISPOSTA\s*:?\s*\*\*\s*$"),
    re.compile(r"(?mi)^\s*📈\s*\*\*\s*TREND\s*\*\*\s*$"),
    re.compile(r"(?mi)^\s*🏆\s*\*\*\s*CLASSIFICA\s*\*\*\s*$"),
]

_SECTION_KEYWORDS = (
    "TREND",
    "CLASSIFICA",
    "STATISTICHE",
    "TOP",
    "BREAKDOWN",
    "RISPOSTA",
)


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

    illegal_section_lines = _find_illegal_section_headings_in_description(description)
    if has_fields and illegal_section_lines:
        raise AssertionError(
            "Description contiene sezioni hardcoded; usare fields standard per le sezioni principali. "
            f"Righe sospette: {illegal_section_lines}"
        )


def _looks_like_section_heading_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if any(pattern.search(stripped) for pattern in _ILLEGAL_DESCRIPTION_SECTION_PATTERNS):
        return True
    if "**" not in stripped:
        return False
    plain = stripped.replace("*", "").replace("_", "").upper()
    return any(keyword in plain for keyword in _SECTION_KEYWORDS)


def _find_illegal_section_headings_in_description(description: str | None) -> list[str]:
    if not description:
        return []
    return [line.strip() for line in description.splitlines() if _looks_like_section_heading_line(line)]


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
            for chunk in _literal_text_chunks(_keyword_expr(node, "description")):
                offenders = _find_illegal_section_headings_in_description(chunk)
                if offenders:
                    issues.append(
                        f"{path}:{node.lineno} description con heading strutturali hardcoded: {offenders[:3]}"
                    )

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

        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "description" in names:
                for chunk in _literal_text_chunks(node.value):
                    offenders = _find_illegal_section_headings_in_description(chunk)
                    if offenders:
                        issues.append(
                            f"{path}:{node.lineno} assegnazione description con heading strutturali hardcoded: {offenders[:3]}"
                        )

        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == "description":
            for chunk in _literal_text_chunks(node.value):
                offenders = _find_illegal_section_headings_in_description(chunk)
                if offenders:
                    issues.append(
                        f"{path}:{node.lineno} concatenazione description con heading strutturali hardcoded: {offenders[:3]}"
                    )

    if embed_ctor_count >= 3 and not helper_used:
        issues.append(
            f"{path}: uso intensivo di discord.Embed ({embed_ctor_count}) senza helper body canonici "
            f"{sorted(_CANONICAL_BODY_HELPERS)}"
        )

    return issues


def _literal_text_chunks(node: ast.AST | None) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return [value.value for value in node.values if isinstance(value, ast.Constant) and isinstance(value.value, str)]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return [*_literal_text_chunks(node.left), *_literal_text_chunks(node.right)]
    return []


def test_standard_body_helpers_contract() -> None:
    title = format_standard_title("resoconto canale", emoji="📓")
    assert_standard_title(title)

    field = format_standard_field_name("TREND", emoji="📈")
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
    assert_standard_field_name(format_standard_field_name("trend", emoji="📈"))


def test_description_heading_detector_flags_illegal_section_patterns() -> None:
    bad = "\n".join(
        [
            "*Intro*",
            "👇 **Risposta:**",
            "📈 **TREND**",
            "🏆 **CLASSIFICA**",
        ]
    )
    offenders = _find_illegal_section_headings_in_description(bad)
    assert offenders, "Il detector deve intercettare heading di sezione hardcoded in description"
    assert any("RISPOSTA" in line.upper() for line in offenders)
    assert any("TREND" in line.upper() for line in offenders)
    assert any("CLASSIFICA" in line.upper() for line in offenders)


def test_static_scanner_flags_structural_headings_in_description_literals() -> None:
    src = Path("tmp_embed_bad.py")
    src.write_text(
        '\n'.join(
            [
                "import discord",
                'description = "*Intro*"',
                'description += "\\n📈 **TREND**\\n- ok"',
                'embed = discord.Embed(title="✅ __**REPORT**__", description=description)',
            ]
        ),
        encoding="utf-8",
    )
    try:
        issues = _scan_embed_bypasses(src)
    finally:
        src.unlink(missing_ok=True)
    assert any("heading strutturali hardcoded" in item for item in issues)


def test_static_scanner_allows_narrative_bold_without_section_heading() -> None:
    src = Path("tmp_embed_good.py")
    src.write_text(
        '\n'.join(
            [
                "import discord",
                'description = "*Ottimo risultato*: crescita continua e collaborazione alta."',
                'embed = discord.Embed(title="✅ __**REPORT**__", description=description)',
                'embed.add_field(name="📈 __**TREND**__", value="ok", inline=False)',
            ]
        ),
        encoding="utf-8",
    )
    try:
        issues = _scan_embed_bypasses(src)
    finally:
        src.unlink(missing_ok=True)
    assert not any("heading strutturali hardcoded" in item for item in issues)


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




def test_standard_helpers_are_idempotent_on_canonical_values() -> None:
    assert format_standard_title("📓 __**RESOCONTO CANALE**__") == "📓 __**RESOCONTO CANALE**__"
    assert format_standard_field_name("📈 __**TREND**__") == "📈 __**TREND**__"
    assert format_standard_description("*Intro standard*", italic=True) == "*Intro standard*"


def test_runtime_renderer_outputs_do_not_use_inverted_markdown_in_field_names() -> None:
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
    for embed in channel_embeds:
        for field in embed.fields:
            assert not field.name.strip().startswith("**__")

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

    assert any("TREND" in f.name for f in activity_embeds[0].fields), (
        "Activity report: la sezione TREND deve essere un field standard, non solo testo in description"
    )
    assert any("STATISTICHE SERVER" in f.name for f in activity_embeds[0].fields), (
        "Activity report: STATISTICHE SERVER deve stare nei fields"
    )
    assert any("MOMENTI SALIENTI" in f.name for f in channel_embeds[1].fields), (
        "Channel summary: le sezioni principali (es. MOMENTI SALIENTI) devono stare nei fields"
    )
    assert any("MISSIONI" in f.name for emb in aura_embeds[1:] for f in emb.fields), (
        "Aura: le sezioni di dettaglio (es. MISSIONI) devono comparire come fields"
    )
