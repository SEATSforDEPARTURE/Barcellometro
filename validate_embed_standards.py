from __future__ import annotations

import argparse
import ast
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
    "apply_standard_report_style",
    "_apply_campaign_footer",
}

CANONICAL_HELPER_FILES = {
    "app/shared/discord/command_embeds.py",
    "app/shared/discord/report_embeds.py",
    "app/shared/discord/component_notices.py",
    "app/shared/discord/footer_pipeline.py",
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
    "finalize_embed",
    "finalize_embeds",
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
        _FooterMetaVisitor(path, report).visit(tree)
        if path in command_roots:
            _CommandFunctionVisitor(path, report).visit(tree)
    return report


def _print_report(report: ValidationReport) -> None:
    print("Embed standards validation")
    print("Rules:")
    print("- No raw text messages through Discord send APIs.")
    print("- Slash commands must use the standard command embed builder helpers.")
    print("- Embed construction must include footer meta wiring.")
    print("- No duplicate generic embed helper systems are allowed.")
    print("- Technical namespaces must not leak into standard command embed titles.")
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
