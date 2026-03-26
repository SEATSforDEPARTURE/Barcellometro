from __future__ import annotations

import argparse
import ast
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_SCAN_ROOTS = ("app",)
IGNORED_PARTS = {".git", ".venv", ".pytest_cache", "__pycache__"}

RAW_TEXT_TARGETS = {
    ("interaction", "response", "send_message"),
    ("interaction", "followup", "send"),
}

STANDARD_COMMAND_HELPERS = {
    "send_standard_response",
    "send_legacy_standard_response",
    "build_command_embed",
    "build_command_embeds",
    "send_command_embeds",
    "send_standard_component_notice",
}

FOOTER_ATTACHMENT_HELPERS = {
    "attach_footer_meta",
    "attach_footer_meta_to_all",
    "attach_minimal_footer",
    "copy_footer_meta",
    "build_report_cover_embed",
    "hydrate_persisted_embed_with_footer",
    "hydrate_persisted_embeds_with_footer",
    "apply_standard_report_style",
    "_apply_campaign_footer",
}

CANONICAL_HELPER_FILES = {
    "app/shared/discord/command_embeds.py",
    "app/shared/discord/report_embeds.py",
    "app/shared/discord/component_notices.py",
    "app/shared/discord/footer_pipeline.py",
    "app/shared/discord/embed_rendering.py",
    "app/shared/discord/embed_limits.py",
    "app/shared/discord/delivery.py",
    "app/services/footer.py",
    "app/services/discord_embed_utils.py",
}

CANONICAL_HELPER_FUNCTIONS = STANDARD_COMMAND_HELPERS | {
    "attach_footer_meta",
    "attach_footer_meta_to_all",
    "attach_minimal_footer",
    "copy_footer_meta",
    "hydrate_persisted_embed_with_footer",
    "hydrate_persisted_embeds_with_footer",
    "finalize_embed",
    "finalize_embeds",
    "finalize_embed_rendering",
    "finalize_embeds_rendering",
}

DUPLICATE_HELPER_NAME_PATTERNS = (
    "standard_response",
    "command_embed",
    "footer_meta",
    "minimal_footer",
    "component_notice",
)

DISPLAY_TOP_LEVEL_OVERRIDES = {
    "frasi",
    "campagne",
    "qna",
    "insights",
    "moderazione",
    "greetings",
    "inattivi",
    "privacy",
    "roles",
    "attivita",
    "aura",
    "riassunto",
    "resoconto",
    "resocontocanale",
    "resocontoserver",
    "domanda",
    "ask",
}

RUNTIME_SUBTITLE_PARAM_NAMES = {
    "tier",
    "user",
    "utente",
    "role",
    "channel",
    "id",
    "id_or_name",
    "schedule_id",
    "quantita",
    "quantity",
    "unita",
    "unit",
    "type",
    "scope",
    "duration",
    "amount",
    "priority",
    "da",
    "a",
}

_STANDARD_HEADING_RE = re.compile(r"^(?P<prefix>\S+)\s+__\*\*(?P<inner>.+)\*\*__$")
_CANONICAL_BODY_HELPERS = {
    "format_standard_title",
    "format_standard_field_name",
    "apply_standard_body_helpers",
    "format_standard_description",
}


@dataclass(slots=True)
class Issue:
    rule: str
    path: str
    line: int
    message: str


@dataclass(slots=True)
class ValidationReport:
    errors: list[Issue] = field(default_factory=list)

    def add(self, rule: str, path: Path, line: int, message: str) -> None:
        self.errors.append(Issue(rule=rule, path=path.as_posix(), line=line, message=message))

    @property
    def exit_code(self) -> int:
        return 1 if self.errors else 0


class _FunctionContextVisitor(ast.NodeVisitor):
    def __init__(self, file_path: Path, report: ValidationReport) -> None:
        self.file_path = file_path
        self.report = report
        self._function_stack: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._function_stack.append(node.name)
        self.generic_visit(node)
        self._function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._function_stack.append(node.name)
        self.generic_visit(node)
        self._function_stack.pop()

    @property
    def current_function(self) -> str | None:
        return self._function_stack[-1] if self._function_stack else None


def _iter_python_files(root: Path, scan_roots: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    for relative_root in scan_roots:
        base = root / relative_root
        if not base.exists():
            continue
        files.extend(
            path
            for path in base.rglob("*.py")
            if path.is_file() and not any(part in IGNORED_PARTS for part in path.parts)
        )
    return sorted(set(files))


def _iter_repo_text_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in IGNORED_PARTS for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def _attribute_chain(node: ast.AST) -> tuple[str, ...] | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return tuple(reversed(parts))
    return None


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _keyword_value(node: ast.Call, name: str) -> ast.AST | None:
    for keyword in node.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _is_string_expr(node: ast.AST | None) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _is_string_expr(node.left) or _is_string_expr(node.right)
    return False


def _is_none_literal(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _literal_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_standard_uppercase_heading(value: str) -> bool:
    match = _STANDARD_HEADING_RE.match(value.strip())
    if match is None:
        return False
    inner = match.group("inner").strip()
    if not inner or not any(ch.isalpha() for ch in inner):
        return False
    return inner.upper() == inner


def _source_uses_canonical_body_helpers(source: str) -> bool:
    return any(f"{helper}(" in source for helper in _CANONICAL_BODY_HELPERS)


def _check_hardcoded_embed_title_and_field_contract(
    tree: ast.AST,
    path: Path,
    source: str,
    report: ValidationReport,
) -> None:
    rel = path.relative_to(REPO_ROOT)
    if rel.parts[:1] == ("tests",):
        return

    embed_ctor_count = 0
    helper_used = _source_uses_canonical_body_helpers(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        chain = _attribute_chain(node.func)

        if chain == ("discord", "Embed"):
            embed_ctor_count += 1
            title_text = _literal_str(_keyword_value(node, "title"))
            if title_text is not None and not _is_standard_uppercase_heading(title_text):
                report.add(
                    "embed_title_literal_standard",
                    rel,
                    node.lineno,
                    "Hardcoded discord.Embed(title=...) must be '(emoji) __**UPPERCASE**__' (bold + underline + uppercase).",
                )

        if isinstance(node.func, ast.Attribute) and node.func.attr == "add_field":
            name_expr = _keyword_value(node, "name")
            if name_expr is None and node.args:
                name_expr = node.args[0]
            name_text = _literal_str(name_expr)
            if name_text is not None and not _is_standard_uppercase_heading(name_text):
                report.add(
                    "embed_field_name_literal_standard",
                    rel,
                    node.lineno,
                    "Hardcoded embed.add_field(name=...) must be '(emoji) __**UPPERCASE**__' (bold + underline + uppercase).",
                )

    if embed_ctor_count >= 3 and not helper_used:
        report.add(
            "embed_body_helpers_required_for_embed_heavy_files",
            rel,
            1,
            "File creates many discord.Embed instances and must use canonical body helpers to prevent title/field regressions.",
        )


def _check_legacy_footer_service_wiring(tree: ast.AST, path: Path, report: ValidationReport) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) != "send_legacy_standard_response":
            continue
        if any(keyword.arg == "footer_service" for keyword in node.keywords):
            continue
        report.add(
            "legacy_footer_service_required",
            path.relative_to(REPO_ROOT),
            node.lineno,
            "send_legacy_standard_response must receive footer_service so global footer phrases reach legacy/admin embeds.",
        )


_ALLOWED_MANUAL_SET_FOOTER_FILES = {
    REPO_ROOT / "app" / "services" / "footer.py",
    REPO_ROOT / "app" / "shared" / "discord" / "footer_pipeline.py",
}

_ALLOWED_MANUAL_SET_AUTHOR_FILES = {
    REPO_ROOT / "app" / "services" / "author.py",
    REPO_ROOT / "app" / "shared" / "discord" / "author_pipeline.py",
    REPO_ROOT / "app" / "plugins" / "commands_modular" / "riassunto.py",
}

_ALLOWED_MANUAL_SET_IMAGE_FILES = {
    REPO_ROOT / "app" / "services" / "embed_images.py",
    REPO_ROOT / "app" / "shared" / "discord" / "embed_images_pipeline.py",
    REPO_ROOT / "app" / "services" / "member_flow_notifications.py",
    REPO_ROOT / "app" / "plugins" / "commands_modular" / "riassunto.py",
}


def _check_manual_set_footer_calls(tree: ast.AST, path: Path, report: ValidationReport) -> None:
    if path in _ALLOWED_MANUAL_SET_FOOTER_FILES or path.parts[:1] == ("tests",):
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        chain = _attribute_chain(node.func)
        if chain is None or chain[-1] != "set_footer":
            continue
        report.add(
            "manual_footer_bypass",
            path.relative_to(REPO_ROOT),
            node.lineno,
            "Manual embed.set_footer(...) bypasses the centralized footer contract; use footer metadata/helpers instead.",
        )


def _check_manual_set_author_calls(tree: ast.AST, path: Path, report: ValidationReport) -> None:
    if path in _ALLOWED_MANUAL_SET_AUTHOR_FILES or path.parts[:1] == ("tests",):
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        chain = _attribute_chain(node.func)
        if chain is None or chain[-1] != "set_author":
            continue
        report.add(
            "manual_author_bypass",
            path.relative_to(REPO_ROOT),
            node.lineno,
            "Manual embed.set_author(...) bypasses the centralized author contract; use author metadata/helpers instead.",
        )


def _check_manual_set_embed_images_calls(tree: ast.AST, path: Path, report: ValidationReport) -> None:
    if path in _ALLOWED_MANUAL_SET_IMAGE_FILES or path.parts[:1] == ("tests",):
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        chain = _attribute_chain(node.func)
        if chain is None or chain[-1] not in {"set_image", "set_thumbnail"}:
            continue
        report.add(
            "manual_embed_images_bypass",
            path.relative_to(REPO_ROOT),
            node.lineno,
            "Manual embed.set_image/set_thumbnail bypasses the centralized images contract; use embed image metadata/helpers instead.",
        )


def _check_body_helpers_adoption(path: Path, source: str, report: ValidationReport) -> None:
    rel = path.relative_to(REPO_ROOT)
    if rel.as_posix() != "app/shared/discord/command_embeds.py":
        return
    if "format_standard_title(" not in source:
        report.add(
            "body_helpers_required",
            rel,
            1,
            "Command embed builder must route title rendering through format_standard_title.",
        )


def _check_body_helpers_uppercase_contract(path: Path, source: str, report: ValidationReport) -> None:
    rel = path.relative_to(REPO_ROOT)
    if rel.as_posix() != "app/shared/discord/embed_body.py":
        return
    if "rendered = base.upper()" not in source:
        report.add(
            "body_title_uppercase_required",
            rel,
            1,
            "format_standard_title must always normalize title content to uppercase.",
        )
    if "normalized = base.upper()" not in source:
        report.add(
            "body_field_uppercase_required",
            rel,
            1,
            "format_standard_field_name must always normalize field-name content to uppercase.",
        )


_PHASE3_MIGRATED_RENDERERS: dict[str, dict[str, object]] = {
    "app/renderers/channel_summary.py": {"allow_title_pagination": False},
    "app/renderers/detail_embeds.py": {"allow_title_pagination": False},
    "app/renderers/activity_report_renderer.py": {"allow_title_pagination": False},
    "app/renderers/activity_dm_report_renderer.py": {"allow_title_pagination": False},
    "app/renderers/server_activity_report_renderer.py": {"allow_title_pagination": False},
    "app/renderers/user_activity_report_renderer.py": {"allow_title_pagination": False},
    "app/renderers/aura_renderer.py": {"allow_title_pagination": True},
}


def _check_phase3_renderer_metadata_adoption(path: Path, source: str, report: ValidationReport) -> None:
    rel = path.relative_to(REPO_ROOT).as_posix()
    if rel not in _PHASE3_MIGRATED_RENDERERS:
        return

    if "attach_author_meta(" not in source and "attach_author_meta_to_all(" not in source:
        report.add(
            "phase3_renderer_author_meta_required",
            path.relative_to(REPO_ROOT),
            1,
            "Migrated renderer must attach author metadata through centralized author helpers.",
        )
    if "attach_embed_images_meta(" not in source and "attach_embed_images_meta_to_all(" not in source:
        report.add(
            "phase3_renderer_images_meta_required",
            path.relative_to(REPO_ROOT),
            1,
            "Migrated renderer must attach embed images metadata through centralized images helpers.",
        )
    if "attach_footer_meta(" not in source and "attach_footer_meta_to_all(" not in source:
        report.add(
            "phase3_renderer_footer_meta_required",
            path.relative_to(REPO_ROOT),
            1,
            "Migrated renderer must attach footer metadata through centralized footer helpers.",
        )


def _check_renderer_title_pagination_bypass(path: Path, tree: ast.AST, report: ValidationReport) -> None:
    rel = path.relative_to(REPO_ROOT).as_posix()
    cfg = _PHASE3_MIGRATED_RENDERERS.get(rel)
    if cfg is None or bool(cfg.get("allow_title_pagination")):
        return

    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if "(Pag " not in node.value and "(Pag." not in node.value:
            continue
        report.add(
            "renderer_title_pagination_bypass",
            path.relative_to(REPO_ROOT),
            node.lineno,
            "Pagination must not be hardcoded in embed titles for migrated renderers; rely on author pagination pipeline.",
        )

_RISKY_PERSISTED_EMBED_TARGETS = {
    ("interaction", "response", "edit_message"),
    ("interaction", "response", "send_message"),
    ("interaction", "followup", "send"),
}


def _is_discord_embed_from_dict_call(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Call) and _attribute_chain(node.func) == ("discord", "Embed", "from_dict")


def _collect_from_dict_embed_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Assign) and _is_discord_embed_from_dict_call(child.value):
            for target in child.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name) and _is_discord_embed_from_dict_call(child.value):
            names.add(child.target.id)
    return names


def _expr_contains_from_dict_embed(node: ast.AST | None, embed_names: set[str]) -> bool:
    if node is None:
        return False
    if _is_discord_embed_from_dict_call(node):
        return True
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in embed_names:
            return True
        if _is_discord_embed_from_dict_call(child):
            return True
    return False


def _check_persisted_embed_hydration(tree: ast.AST, file_path: Path, report: ValidationReport) -> None:
    file_rel = file_path.relative_to(REPO_ROOT)
    if file_rel.as_posix() in CANONICAL_HELPER_FILES:
        return
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        embed_names = _collect_from_dict_embed_names(node)
        if not embed_names and not any(_is_discord_embed_from_dict_call(child.value) for child in ast.walk(node) if isinstance(child, ast.Expr) and isinstance(child.value, ast.Call)):
            continue
        if _function_contains_call_names(node, {
            "hydrate_persisted_embed_with_footer",
            "hydrate_persisted_embeds_with_footer",
            "attach_footer_meta",
            "attach_footer_meta_to_all",
            "finalize_embed",
            "finalize_embeds",
        }):
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            chain = _attribute_chain(child.func)
            if chain not in _RISKY_PERSISTED_EMBED_TARGETS:
                continue
            risky_value = _keyword_value(child, "embed") or _keyword_value(child, "embeds")
            if not _expr_contains_from_dict_embed(risky_value, embed_names):
                continue
            report.add(
                "persisted_embed_requires_footer_hydration",
                file_rel,
                child.lineno,
                "Embeds rebuilt via discord.Embed.from_dict(...) must be rehydrated through the footer contract before edit/send.",
            )




def _literal_int(node: ast.AST | None) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    return None


def _contains_name(node: ast.AST | None, target_names: set[str]) -> bool:
    if node is None:
        return False
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in target_names:
            return True
    return False


def _dict_literal_values(tree: ast.AST, name: str) -> dict[str, str | int]:
    for node in getattr(tree, "body", []):
        if not isinstance(node, (ast.AnnAssign, ast.Assign)):
            continue
        targets: list[ast.expr] = [node.target] if isinstance(node, ast.AnnAssign) else list(node.targets)
        if not any(isinstance(target, ast.Name) and target.id == name for target in targets):
            continue
        if not isinstance(node.value, ast.Dict):
            return {}
        parsed: dict[str, str | int] = {}
        for key_node, value_node in zip(node.value.keys, node.value.values, strict=False):
            key = _literal_str(key_node)
            if key is None:
                continue
            value = _literal_str(value_node)
            if value is None:
                value = _literal_int(value_node)
            if value is None:
                continue
            parsed[key] = value
        return parsed
    return {}


def _is_command_decorator(decorator: ast.AST) -> bool:
    return (
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr == "command"
    )


def _function_contains_call_names(node: ast.AST, names: set[str]) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and _call_name(child) in names:
            return True
    return False


def _find_function_def(tree: ast.AST, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _is_name(node: ast.AST | None, expected: str) -> bool:
    return isinstance(node, ast.Name) and node.id == expected


def _is_truthy_name_test(node: ast.AST | None, expected: str) -> bool:
    return _is_name(node, expected)


def _is_parts_append_call(node: ast.AST, expected_name: str) -> bool:
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return False
    call = node.value
    return (
        isinstance(call.func, ast.Attribute)
        and _is_name(call.func.value, "parts")
        and call.func.attr == "append"
        and len(call.args) == 1
        and _is_name(call.args[0], expected_name)
    )


def _render_footer_text_has_canonical_order(tree: ast.AST) -> bool:
    node = _find_function_def(tree, "render_footer_text")
    if node is None:
        return False

    has_brand_parts_assignment = False
    has_clean_phrase_assignment = False
    append_order: list[str] = []
    for statement in node.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target = statement.targets[0]
            if _is_name(target, "parts") and isinstance(statement.value, ast.List):
                if len(statement.value.elts) == 1 and _is_name(statement.value.elts[0], "brand"):
                    has_brand_parts_assignment = True
            if _is_name(target, "clean_phrase") and isinstance(statement.value, ast.IfExp):
                test = statement.value.test
                body = statement.value.body
                orelse = statement.value.orelse
                if (
                    _is_truthy_name_test(test, "phrase")
                    and isinstance(body, ast.Call)
                    and _call_name(body) == "_clean_footer_text"
                    and len(body.args) == 1
                    and _is_name(body.args[0], "phrase")
                    and isinstance(orelse, ast.Constant)
                    and orelse.value == ""
                ):
                    has_clean_phrase_assignment = True
        if isinstance(statement, ast.If) and _is_truthy_name_test(statement.test, "clean_phrase"):
            if len(statement.body) == 1 and _is_parts_append_call(statement.body[0], "clean_phrase"):
                append_order.append("phrase")
        if isinstance(statement, ast.If) and _is_truthy_name_test(statement.test, "processing"):
            if len(statement.body) == 1 and _is_parts_append_call(statement.body[0], "processing"):
                append_order.append("processing")

    return has_brand_parts_assignment and has_clean_phrase_assignment and append_order == ["phrase", "processing"]


def _is_discord_embed_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _attribute_chain(node.func) == ("discord", "Embed")


def _iter_embed_assignment_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Assign) and _is_discord_embed_call(child.value):
            for target in child.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name) and _is_discord_embed_call(child.value):
            names.add(child.target.id)
    return names


def _find_footer_attachment_targets(node: ast.AST) -> set[str]:
    attached: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if _call_name(child) not in FOOTER_ATTACHMENT_HELPERS:
            continue
        if not child.args:
            continue
        first_arg = child.args[0]
        if isinstance(first_arg, ast.Name):
            attached.add(first_arg.id)
    return attached


def _check_raw_text_messages(tree: ast.AST, file_path: Path, report: ValidationReport) -> None:
    file_rel = file_path.relative_to(REPO_ROOT)
    if file_rel.as_posix() in CANONICAL_HELPER_FILES:
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        chain = _attribute_chain(node.func)
        if chain not in RAW_TEXT_TARGETS:
            continue
        if node.args:
            report.add(
                "raw_text_messages",
                file_rel,
                node.lineno,
                f"Direct positional send via {'.'.join(chain)} is forbidden; use standard embed helpers and keyword arguments.",
            )
            continue
        content_value = _keyword_value(node, "content")
        if _is_none_literal(content_value):
            continue
        if _is_string_expr(content_value) and _keyword_value(node, "embed") is None and _keyword_value(node, "embeds") is None:
            report.add(
                "raw_text_messages",
                file_rel,
                node.lineno,
                f"Raw string content sent via {'.'.join(chain)} without an embed.",
            )


class _CommandFunctionVisitor(_FunctionContextVisitor):
    def __init__(self, file_path: Path, report: ValidationReport) -> None:
        super().__init__(file_path, report)
        self.file_rel = file_path.relative_to(REPO_ROOT)

    def _check_command_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if not any(_is_command_decorator(decorator) for decorator in node.decorator_list):
            return
        if _function_contains_call_names(node, STANDARD_COMMAND_HELPERS):
            return
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            chain = _attribute_chain(child.func)
            if chain in RAW_TEXT_TARGETS:
                self.report.add(
                    "commands_use_standard_embed_builder",
                    self.file_rel,
                    child.lineno,
                    f"Slash command '{node.name}' sends responses directly via {'.'.join(chain)} instead of the standard embed helper.",
                )
                return
            if _is_discord_embed_call(child):
                self.report.add(
                    "commands_use_standard_embed_builder",
                    self.file_rel,
                    child.lineno,
                    f"Slash command '{node.name}' builds discord.Embed directly instead of using the standard command embed builder.",
                )
                return

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._check_command_function(node)
        super().visit_FunctionDef(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._check_command_function(node)
        super().visit_AsyncFunctionDef(node)


class _FooterMetaVisitor(_FunctionContextVisitor):
    def __init__(self, file_path: Path, report: ValidationReport) -> None:
        super().__init__(file_path, report)
        self.file_rel = file_path.relative_to(REPO_ROOT)

    def _check_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if self.file_rel.as_posix() in CANONICAL_HELPER_FILES:
            return
        if node.name.startswith("_"):
            return
        embed_names = _iter_embed_assignment_names(node)
        embed_lines = [
            child.lineno
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and _is_discord_embed_call(child)
        ]
        if not embed_lines:
            return
        if _function_contains_call_names(node, FOOTER_ATTACHMENT_HELPERS):
            attached_names = _find_footer_attachment_targets(node)
            if not embed_names or attached_names:
                return
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and str(_call_name(child) or "").lower().endswith("footer"):
                    return
            if _function_contains_call_names(node, {"attach_footer_meta_to_all", "apply_standard_report_style", "build_report_cover_embed"}):
                return
            if embed_names.issubset(attached_names):
                return
        for line in embed_lines:
            self.report.add(
                "footer_meta_required",
                self.file_rel,
                line,
                "Function builds discord.Embed without an obvious footer meta attachment call in the same function.",
            )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._check_function(node)
        super().visit_FunctionDef(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._check_function(node)
        super().visit_AsyncFunctionDef(node)


def _check_duplicate_helper_systems(tree: ast.AST, file_path: Path, report: ValidationReport) -> None:
    file_rel = file_path.relative_to(REPO_ROOT)
    rel_str = file_rel.as_posix()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = node.name
        if name in CANONICAL_HELPER_FUNCTIONS:
            if rel_str not in CANONICAL_HELPER_FILES:
                report.add(
                    "no_duplicate_embed_helper_systems",
                    file_rel,
                    node.lineno,
                    f"Helper '{name}' duplicates a canonical embed helper outside the approved modules.",
                )
            continue
        if rel_str in CANONICAL_HELPER_FILES:
            continue
        normalized = name.lower()
        if any(pattern in normalized for pattern in DUPLICATE_HELPER_NAME_PATTERNS) and ("embed" in normalized or "footer" in normalized or "response" in normalized):
            report.add(
                "no_duplicate_embed_helper_systems",
                file_rel,
                node.lineno,
                f"Helper '{name}' looks like a parallel embed standardization system; extend the canonical helper modules instead.",
            )


def _check_display_command_context(tree: ast.AST, file_path: Path, report: ValidationReport) -> None:
    file_rel = file_path.relative_to(REPO_ROOT)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _call_name(node) not in STANDARD_COMMAND_HELPERS:
            continue
        top_level = _literal_str(_keyword_value(node, "top_level"))
        subcommand_path = _literal_str(_keyword_value(node, "subcommand_path"))
        visual_top_level = _literal_str(_keyword_value(node, "visual_top_level"))
        if not top_level or not subcommand_path:
            continue
        if top_level.lower() == "resoconto":
            report.add(
                "display_command_context",
                file_rel,
                node.lineno,
                "Do not use generic top_level='resoconto' for standardized embeds; use the real visible root such as 'resocontocanale' or 'resocontoserver'.",
            )
            continue

        path_parts = [part.strip().lower() for part in subcommand_path.split() if part.strip()]
        if not path_parts:
            continue
        expected_visual_top = path_parts[0]
        if expected_visual_top not in DISPLAY_TOP_LEVEL_OVERRIDES:
            continue
        if top_level.lower() != "admin" and top_level.lower() != expected_visual_top:
            if visual_top_level != expected_visual_top:
                report.add(
                    "display_command_context",
                    file_rel,
                    node.lineno,
                    f"top_level='{top_level}' does not match visible command root '{expected_visual_top}' for subcommand_path='{subcommand_path}'.",
                )
                continue
        if top_level.lower() == "admin" and visual_top_level != expected_visual_top:
            report.add(
                "display_command_context",
                file_rel,
                node.lineno,
                f"Provide visual_top_level='{expected_visual_top}' so the embed title matches the visible command root instead of the technical namespace.",
            )


def _check_manual_subtitle_concatenation(tree: ast.AST, file_path: Path, report: ValidationReport) -> None:
    file_rel = file_path.relative_to(REPO_ROOT)
    rel_str = file_rel.as_posix()
    if rel_str in CANONICAL_HELPER_FILES:
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _call_name(node) not in STANDARD_COMMAND_HELPERS:
            continue
        if _keyword_value(node, "subtitle_args") is not None or _keyword_value(node, "relevant_parameters") is not None:
            continue
        subcommand_expr = _keyword_value(node, "subcommand_path")
        if not isinstance(subcommand_expr, (ast.JoinedStr, ast.BinOp)):
            continue
        if _contains_name(subcommand_expr, RUNTIME_SUBTITLE_PARAM_NAMES):
            report.add(
                "subtitle_builder_centralization",
                file_rel,
                node.lineno,
                "Do not concatenate runtime subtitle fragments into subcommand_path manually; pass them via subtitle_args.",
            )


def _check_canonical_embed_configuration(report: ValidationReport) -> None:
    command_embeds_path = REPO_ROOT / "app" / "shared" / "discord" / "command_embeds.py"
    command_source = command_embeds_path.read_text(encoding="utf-8")
    command_tree = ast.parse(command_source, filename=str(command_embeds_path))

    expected_emojis = {
        "success": "✅",
        "warning": "⚠️",
        "error": "❌",
        "info": "ℹ️",
    }
    expected_colors = {
        "success": 0x57F287,
        "warning": 0xFEE75C,
        "error": 0xED4245,
        "info": 0x3498DB,
    }
    kind_emojis = _dict_literal_values(command_tree, "KIND_EMOJIS")
    kind_colors = _dict_literal_values(command_tree, "KIND_COLORS")

    for key, expected in expected_emojis.items():
        actual = kind_emojis.get(key)
        if actual != expected:
            report.add(
                "canonical_embed_kind_mapping",
                command_embeds_path.relative_to(REPO_ROOT),
                1,
                f"KIND_EMOJIS['{key}'] must be {expected!r}, found {actual!r}.",
            )
    for key, expected in expected_colors.items():
        actual = kind_colors.get(key)
        if actual != expected:
            report.add(
                "canonical_embed_kind_mapping",
                command_embeds_path.relative_to(REPO_ROOT),
                1,
                f"KIND_COLORS['{key}'] must be {hex(expected)}, found {actual!r}.",
            )

    if "resolved_subtitle_emoji = subcommand_emoji or KIND_EMOJIS[kind]" not in command_source:
        report.add(
            "canonical_embed_kind_mapping",
            command_embeds_path.relative_to(REPO_ROOT),
            1,
            "Standard command embeds must derive the subtitle icon from KIND_EMOJIS[kind].",
        )

    forbidden_command_snippets = (
        'footer_mode: FooterMode = "minimal"',
        "attach_minimal_footer(",
    )
    for snippet in forbidden_command_snippets:
        if snippet in command_source:
            report.add(
                "canonical_footer_pipeline_defaults",
                command_embeds_path.relative_to(REPO_ROOT),
                1,
                "Standard command embed helpers must default to centralized footer metadata and must not render minimal footers locally.",
            )
            break


    forbidden_command_fallback_snippets = (
        "finalize_embeds_author(embed_list, None",
        "finalize_embeds(embed_list, None",
        "if footer_service is None:",
    )
    for snippet in forbidden_command_fallback_snippets:
        if snippet in command_source:
            report.add(
                "canonical_footer_fallback_delivery",
                command_embeds_path.relative_to(REPO_ROOT),
                1,
                f"Standard command embeds must not finalize author/footer through null-service fallbacks; forbidden snippet found: {snippet!r}.",
            )
            break

    required_section_snippets = (
        "def _resolve_section_emoji(",
        "subtitle_emoji: str | None = None",
        "header_emoji = _resolve_section_emoji(",
        "subtitle_emoji=display_context.subtitle_emoji",
    )
    for snippet in required_section_snippets:
        if snippet not in command_source:
            report.add(
                "canonical_section_emoji_dedup",
                command_embeds_path.relative_to(REPO_ROOT),
                1,
                f"Standard command embeds must route section icons through the centralized subtitle/body dedup logic; missing snippet: {snippet!r}.",
            )
            break

    footer_path = REPO_ROOT / "app" / "services" / "footer.py"
    footer_source = footer_path.read_text(encoding="utf-8")
    footer_tree = ast.parse(footer_source, filename=str(footer_path))
    required_footer_snippets = (
        "def _clean_footer_text(",
        "def render_footer_text(",
        "brand = \"Barcellometro\"",
        "async def _resolve_footer_phrase(",
        "return service_phrases.get(service_name) or global_phrase or None",
        "return footer_text, clean_phrase or None",
        "CUSTOM_EMOJI_RE = re.compile(",
        "if meta.footer_icon_url is None and minimal_icon_url is not None:",
    )
    for snippet in required_footer_snippets:
        if snippet not in footer_source:
            report.add(
                "canonical_footer_order",
                footer_path.relative_to(REPO_ROOT),
                1,
                f"Footer renderer must keep ordered parts version → phrase → processing; missing snippet: {snippet!r}.",
            )
            break
    else:
        if not _render_footer_text_has_canonical_order(footer_tree):
            report.add(
                "canonical_footer_order",
                footer_path.relative_to(REPO_ROOT),
                1,
                "Footer renderer must keep ordered parts version → phrase → processing using an explicit cleaned phrase variable.",
            )

    if "FOOTER_DEFAULT_PHRASE" in footer_source or "or FOOTER_DEFAULT_PHRASE" in footer_source:
        report.add(
            "footer_phrase_fallback",
            footer_path.relative_to(REPO_ROOT),
            1,
            "FooterService must not use a hardcoded automatic fallback phrase for the central footer.",
        )
    if "FOOTER_FALLBACK_VERSION" in footer_source:
        report.add(
            "footer_version_implicit_fallback",
            footer_path.relative_to(REPO_ROOT),
            1,
            "FooterService must not inject implicit version fallbacks; version is shown only when explicitly configured.",
        )


    forbidden_repo_strings = {
        "Dati elaborati" + " in loco": "The local-only technical footer wording is forbidden project-wide.",
        "e fallback" + " locale": "The local-fallback footer wording is forbidden project-wide.",
    }
    for repo_path in _iter_repo_text_files(REPO_ROOT):
        try:
            source = repo_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for forbidden, message in forbidden_repo_strings.items():
            if forbidden not in source:
                continue
            line = source[: source.index(forbidden)].count("\n") + 1
            report.add(
                "forbidden_footer_phrase",
                repo_path.relative_to(REPO_ROOT),
                line,
                message,
            )


def _check_greetings_live_layout_contract(report: ValidationReport) -> None:
    member_flow_path = REPO_ROOT / "app" / "services" / "member_flow_notifications.py"
    member_flow_source = member_flow_path.read_text(encoding="utf-8")
    required_member_flow_snippets = (
        'embed = discord.Embed(title=copy.event_label, description=copy.narrative[:4096], colour=self._colour_for_event_type(str(canonical_payload.get("event_type_key") or action_type)))',
        "attach_author_meta(",
        'canonical_top_level_command="greetings"',
        "embed.set_thumbnail(url=avatar_url)",
        'attach_footer_meta(embed, service_name="member_flow_notifications", used_local_processing=True)',
    )
    for snippet in required_member_flow_snippets:
        if snippet not in member_flow_source:
            report.add(
                "greetings_live_layout_contract",
                member_flow_path.relative_to(REPO_ROOT),
                1,
                f"GREETINGS live renderer must keep the finalized author/title/thumbnail/footer layout; missing snippet: {snippet!r}.",
            )
            break

    forbidden_member_flow_snippets = (
        'embed.add_field(name="Evento"',
        "timestamp=created_at",
        "Oggi alle",
    )
    for snippet in forbidden_member_flow_snippets:
        if snippet in member_flow_source:
            report.add(
                "greetings_live_layout_contract",
                member_flow_path.relative_to(REPO_ROOT),
                1,
                f"GREETINGS live renderer must not reintroduce legacy layout fragments; forbidden snippet found: {snippet!r}.",
            )
            break

    docs_expectations = {
        REPO_ROOT / "docs" / "embed_command_rendering_standard.md": (
            "l'author live deve passare dalla pipeline standard",
            "il titolo dell'embed coincide con la label evento (`event_label`)",
            "non esiste più il field separato `Evento`",
            "la thumbnail dell'embed deve usare l'avatar dell'utente quando disponibile",
        ),
        REPO_ROOT / "settings" / "README.md": (
            "author standard via metadata canonici",
            "titolo embed = label evento",
            "thumbnail = avatar utente",
            "nessun campo separato `Evento`",
        ),
        REPO_ROOT / "settings" / "greetings_trigger.example.json": (
            "label evento nel titolo dell'embed",
            "titolo dell'embed",
        ),
    }
    for path, snippets in docs_expectations.items():
        source = path.read_text(encoding="utf-8")
        for snippet in snippets:
            if snippet not in source:
                report.add(
                    "greetings_live_layout_contract",
                    path.relative_to(REPO_ROOT),
                    1,
                    f"GREETINGS docs/config inventory must reflect the final layout; missing snippet: {snippet!r}.",
                )
                break

    forbidden_repo_strings = {
        "2 campi in `🚪 INGRESSI & USCITE` (`Evento` + campo narrativo largo)": "Legacy GREETINGS two-field layout wording must not appear in the repo.",
        "usa sempre **2 campi** e solo quelli: `Evento` + campo narrativo largo;": "Legacy GREETINGS two-field layout wording must not appear in the repo.",
        "campo Evento": "Legacy GREETINGS wording must refer to the embed title instead of a dedicated Evento field.",
    }
    for repo_path in (
        REPO_ROOT / "docs" / "embed_command_rendering_standard.md",
        REPO_ROOT / "settings" / "README.md",
        REPO_ROOT / "settings" / "greetings_trigger.example.json",
    ):
        source = repo_path.read_text(encoding="utf-8")
        for forbidden, message in forbidden_repo_strings.items():
            if forbidden not in source:
                continue
            line = source[: source.index(forbidden)].count("\n") + 1
            report.add(
                "greetings_live_layout_contract",
                repo_path.relative_to(REPO_ROOT),
                line,
                message,
            )


def validate_embed_standards(*, scan_roots: Iterable[str] = DEFAULT_SCAN_ROOTS) -> ValidationReport:
    report = ValidationReport()
    command_roots = {
        REPO_ROOT / "app" / "plugins" / "commands.py",
    }
    command_dir = REPO_ROOT / "app" / "plugins" / "commands_modular"
    if command_dir.exists():
        command_roots.update(path for path in command_dir.glob("*.py") if path.is_file())

    for path in _iter_python_files(REPO_ROOT, scan_roots):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        _check_raw_text_messages(tree, path, report)
        _check_duplicate_helper_systems(tree, path, report)
        _check_display_command_context(tree, path, report)
        _check_manual_subtitle_concatenation(tree, path, report)
        _check_legacy_footer_service_wiring(tree, path, report)
        _check_manual_set_footer_calls(tree, path, report)
        _check_manual_set_author_calls(tree, path, report)
        _check_manual_set_embed_images_calls(tree, path, report)
        _check_persisted_embed_hydration(tree, path, report)
        _check_body_helpers_adoption(path, source, report)
        _check_body_helpers_uppercase_contract(path, source, report)
        _check_phase3_renderer_metadata_adoption(path, source, report)
        _check_renderer_title_pagination_bypass(path, tree, report)
        _check_hardcoded_embed_title_and_field_contract(tree, path, source, report)
        _FooterMetaVisitor(path, report).visit(tree)
        if path in command_roots:
            _CommandFunctionVisitor(path, report).visit(tree)
    _check_canonical_embed_configuration(report)
    _check_greetings_live_layout_contract(report)
    return report


def _print_report(report: ValidationReport) -> None:
    print("Embed standards validation")
    print("Rules:")
    print("- No raw text messages through Discord send APIs.")
    print("- Slash commands must use the standard command embed builder helpers.")
    print("- Embed construction must include footer meta wiring.")
    print("- No duplicate generic embed helper systems are allowed.")
    print("- Technical namespaces must not leak into standard command embed titles.")
    print("- Embed titles and field names must always be `(emoji) __**UPPERCASE**__`.")
    print()

    if not report.errors:
        print("OK: no embed standard violations found.")
        return

    grouped: dict[str, list[Issue]] = defaultdict(list)
    for issue in sorted(report.errors, key=lambda item: (item.path, item.line, item.rule, item.message)):
        grouped[issue.path].append(issue)

    for path, issues in grouped.items():
        print(f"{path}:")
        for issue in issues:
            print(f"  - line {issue.line} [{issue.rule}] {issue.message}")
        print()

    print(f"Summary: {len(report.errors)} violation(s) across {len(grouped)} file(s).")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate repository embed standards.")
    parser.add_argument(
        "--roots",
        nargs="+",
        default=list(DEFAULT_SCAN_ROOTS),
        help="Repository-relative roots to scan (default: app).",
    )
    args = parser.parse_args(argv)
    report = validate_embed_standards(scan_roots=args.roots)
    _print_report(report)
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
