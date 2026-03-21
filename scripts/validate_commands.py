from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMANDS_ROOT = REPO_ROOT / "app" / "plugins"
COMMANDS_FILE = COMMANDS_ROOT / "commands.py"
COMMANDS_MODULAR_INIT = COMMANDS_ROOT / "commands_modular" / "__init__.py"
MODULAR_DIR = COMMANDS_ROOT / "commands_modular"
DEFAULT_REPORT_PATH = REPO_ROOT / "docs" / "command_tree_report.md"

CANONICAL_ADMIN_ROOT = "admin"
BANNED_SEGMENTS = {"delete", "clear", "create", "update", "stats", "get", "toggle"}
ENGLISH_ALLOWED_SHORT = {"admin", "ai", "dm", "dms", "qna", "stt"}
ITALIAN_MARKERS = {
    "attivita",
    "calibra",
    "canale",
    "configurazione",
    "domanda",
    "frase",
    "frasi",
    "giornata",
    "ieri",
    "imposta",
    "messaggi",
    "oggi",
    "periodi",
    "riassunto",
    "rimuovi",
    "utente",
    "ultimi",
    "vocale",
}
LOCALIZED_COMMAND_EXCEPTIONS = {
    "domanda",
    "riassunto.oggi",
    "riassunto.ieri",
    "riassunto.ultimi",
    "riassunto.range",
    "aura.oggi",
    "aura.ieri",
    "aura.ultimi",
    "aura.range",
    "attivita.oggi",
    "attivita.ieri",
    "attivita.ultimi",
    "attivita.range",
    "resocontocanale.aura.oggi",
    "resocontocanale.aura.ieri",
    "resocontocanale.aura.ultimi",
    "resocontocanale.aura.range",
    "resocontoserver.aura.oggi",
    "resocontoserver.aura.ieri",
    "resocontoserver.aura.ultimi",
    "resocontoserver.aura.range",
}
LOCALIZED_ROOT_EXCEPTIONS = {"riassunto", "attivita", "resocontocanale", "resocontoserver", "frasi"}
CONFIG_TARGET_NAMES = {
    "channel",
    "id",
    "role",
    "schedule_id",
    "service",
    "task",
    "type",
    "user",
    "utente",
    "voice_channel",
}

@dataclass(slots=True)
class ParameterRecord:
    name: str
    required: bool
    description: str | None
    line: int


@dataclass(slots=True)
class CommandRecord:
    path: str
    root: str
    subgroup: str | None
    action: str
    description: str | None
    params: list[ParameterRecord]
    source_file: str
    line: int


@dataclass(slots=True)
class Issue:
    severity: str
    code: str
    message: str
    path: str
    source_file: str | None = None
    line: int | None = None


@dataclass(slots=True)
class ValidationResult:
    commands: list[CommandRecord] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "warning"]


@dataclass(slots=True)
class GroupDef:
    name: str
    description: str | None
    line: int


@dataclass(slots=True)
class PendingCommand:
    group_var: str | None
    name: str
    description: str | None
    params: list[ParameterRecord]
    line: int
    file_path: str


def _literal_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _call_keyword(call: ast.Call, keyword: str) -> ast.AST | None:
    for item in call.keywords:
        if item.arg == keyword:
            return item.value
    return None


def _is_app_commands_group_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "app_commands"
        and node.func.attr == "Group"
    )


def _is_app_commands_describe(call: ast.AST) -> bool:
    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "app_commands"
        and call.func.attr == "describe"
    )


def _decorated_command_info(node: ast.AsyncFunctionDef | ast.FunctionDef) -> tuple[str | None, str, str | None] | None:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr != "command" or not isinstance(func.value, ast.Name):
            continue
        group_var = None if func.value.id == "app_commands" else func.value.id
        name = _literal_str(_call_keyword(decorator, "name"))
        description = _literal_str(_call_keyword(decorator, "description"))
        if name:
            return group_var, name, description
    return None


def _extract_descriptions(node: ast.AsyncFunctionDef | ast.FunctionDef) -> dict[str, str]:
    descriptions: dict[str, str] = {}
    for decorator in node.decorator_list:
        if not _is_app_commands_describe(decorator):
            continue
        for item in decorator.keywords:
            value = _literal_str(item.value)
            if item.arg and value is not None:
                descriptions[item.arg] = value
    return descriptions


def _extract_params(node: ast.AsyncFunctionDef | ast.FunctionDef, descriptions: dict[str, str]) -> list[ParameterRecord]:
    args = list(node.args.args)
    defaults = list(node.args.defaults)
    default_offset = len(args) - len(defaults)
    params: list[ParameterRecord] = []
    for index, arg in enumerate(args):
        if arg.arg in {"self", "cls", "interaction"}:
            continue
        required = index < default_offset
        params.append(
            ParameterRecord(
                name=arg.arg,
                required=required,
                description=descriptions.get(arg.arg),
                line=arg.lineno,
            )
        )
    return params


def _parse_register_functions() -> dict[str, dict[str, Any]]:
    parsed: dict[str, dict[str, Any]] = {}

    def iter_register_module_paths() -> list[Path]:
        paths = {path for path in MODULAR_DIR.glob("*.py")}
        init_tree = ast.parse(COMMANDS_MODULAR_INIT.read_text(), filename=str(COMMANDS_MODULAR_INIT))
        for node in init_tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(target, ast.Name) and target.id == "_MODULE_BY_ATTR" for target in node.targets):
                continue
            if not isinstance(node.value, ast.Dict):
                continue
            for key_node, value_node in zip(node.value.keys, node.value.values):
                key = _literal_str(key_node)
                module_name = _literal_str(value_node)
                if not key or not module_name or not key.startswith("register_"):
                    continue
                paths.add(REPO_ROOT / f"{module_name.replace('.', '/')}.py")
            break
        return sorted(path for path in paths if path.exists())

    for path in iter_register_module_paths():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not node.name.startswith("register_"):
                continue
            params = [arg.arg for arg in node.args.args]
            groups: dict[str, GroupDef] = {}
            parents: dict[str, str] = {}
            commands: list[PendingCommand] = []

            for inner in ast.walk(node):
                if isinstance(inner, ast.Assign) and len(inner.targets) == 1 and isinstance(inner.targets[0], ast.Name) and _is_app_commands_group_call(inner.value):
                    group_name = _literal_str(_call_keyword(inner.value, "name"))
                    group_description = _literal_str(_call_keyword(inner.value, "description"))
                    if group_name:
                        groups[inner.targets[0].id] = GroupDef(name=group_name, description=group_description, line=inner.lineno)
                elif isinstance(inner, ast.Expr) and isinstance(inner.value, ast.Call):
                    call = inner.value
                    if isinstance(call.func, ast.Attribute) and call.func.attr == "add_command" and isinstance(call.func.value, ast.Name) and call.args:
                        child = call.args[0]
                        if isinstance(child, ast.Name):
                            parents[child.id] = call.func.value.id
                    elif isinstance(call.func, ast.Name) and call.func.id == "add_group_once" and len(call.args) >= 2:
                        parent, child = call.args[:2]
                        if isinstance(parent, ast.Name) and isinstance(child, ast.Name):
                            parents[child.id] = parent.id
                elif isinstance(inner, ast.AsyncFunctionDef | ast.FunctionDef):
                    command_info = _decorated_command_info(inner)
                    if not command_info:
                        continue
                    group_var, command_name, description = command_info
                    describe_map = _extract_descriptions(inner)
                    commands.append(
                        PendingCommand(
                            group_var=group_var,
                            name=command_name,
                            description=description,
                            params=_extract_params(inner, describe_map),
                            line=inner.lineno,
                            file_path=str(path.relative_to(REPO_ROOT)),
                        )
                    )
            parsed[node.name] = {
                "params": params,
                "groups": groups,
                "parents": parents,
                "commands": commands,
            }
    return parsed


def _parse_root_group_mapping(register_defs: dict[str, dict[str, Any]]) -> dict[str, dict[str, str | None]]:
    tree = ast.parse(COMMANDS_FILE.read_text(), filename=str(COMMANDS_FILE))
    root_groups: dict[str, str] = {}
    register_mappings: dict[str, dict[str, str | None]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and _is_app_commands_group_call(node.value):
            name = _literal_str(_call_keyword(node.value, "name"))
            if name:
                root_groups[node.targets[0].id] = name
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        func_name = node.func.id
        if func_name not in register_defs:
            continue
        params = register_defs[func_name]["params"]
        mapping: dict[str, str | None] = {}
        for param_name, arg in zip(params, node.args):
            root_name: str | None = None
            if isinstance(arg, ast.Name):
                root_name = root_groups.get(arg.id)
            elif isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name) and arg.value.id == "bot" and arg.attr == "tree":
                root_name = None
            mapping[param_name] = root_name
        register_mappings[func_name] = mapping
    return register_mappings


def _resolve_group_path(
    group_var: str | None,
    root_mapping: dict[str, str | None],
    local_groups: dict[str, GroupDef],
    parents: dict[str, str],
) -> list[str]:
    if group_var is None:
        return []
    if group_var in root_mapping:
        root_name = root_mapping[group_var]
        return [] if root_name is None else [root_name]
    if group_var not in local_groups:
        raise KeyError(f"Unknown group variable: {group_var}")
    parent = parents.get(group_var)
    if parent:
        prefix = _resolve_group_path(parent, root_mapping, local_groups, parents)
    else:
        default_roots = [value for value in root_mapping.values() if value is not None]
        prefix = [default_roots[0]] if len(default_roots) == 1 else []
    return [*prefix, local_groups[group_var].name]


def _looks_localized(text: str | None) -> bool:
    if not text:
        return False
    normalized = re.sub(r"[^a-z0-9_ ]+", " ", text.lower())
    tokens = set(normalized.split())
    return bool(tokens & ITALIAN_MARKERS)


def _should_skip_localized_checks(command: CommandRecord) -> bool:
    return command.path in LOCALIZED_COMMAND_EXCEPTIONS or command.root in LOCALIZED_ROOT_EXCEPTIONS


def _infer_subgroup(segments: list[str]) -> str | None:
    if len(segments) <= 2:
        return None
    return ".".join(segments[1:-1])


def _build_command_records() -> ValidationResult:
    register_defs = _parse_register_functions()
    root_mappings = _parse_root_group_mapping(register_defs)
    result = ValidationResult()

    for register_name, parsed in register_defs.items():
        root_mapping = root_mappings.get(register_name)
        if root_mapping is None:
            continue
        for pending in parsed["commands"]:
            segments = [*_resolve_group_path(pending.group_var, root_mapping, parsed["groups"], parsed["parents"]), pending.name]
            if not segments:
                continue
            path = ".".join(segments)
            result.commands.append(
                CommandRecord(
                    path=path,
                    root=segments[0],
                    subgroup=_infer_subgroup(segments),
                    action=segments[-1],
                    description=pending.description,
                    params=pending.params,
                    source_file=pending.file_path,
                    line=pending.line,
                )
            )
    return result


def _add_issue(result: ValidationResult, severity: str, code: str, message: str, path: str, source_file: str | None = None, line: int | None = None) -> None:
    result.issues.append(Issue(severity=severity, code=code, message=message, path=path, source_file=source_file, line=line))


def _validate_commands(result: ValidationResult) -> ValidationResult:
    by_parent: dict[str, list[CommandRecord]] = {}
    for command in result.commands:
        parent = command.path.rsplit(".", 1)[0] if "." in command.path else ""
        by_parent.setdefault(parent, []).append(command)

        segments = command.path.split(".")
        action = command.action
        if action in BANNED_SEGMENTS:
            _add_issue(result, "error", "banned_segment", f"Command uses banned legacy action '{action}'.", command.path, command.source_file, command.line)
        if not re.fullmatch(r"[a-z]+(?:_[a-z]+){0,2}", action):
            _add_issue(result, "error", "snake_case", f"Action '{action}' must be snake_case with at most two underscores.", command.path, command.source_file, command.line)
        if action.count("_") > 2:
            _add_issue(result, "error", "underscore_limit", f"Action '{action}' exceeds the max underscore limit.", command.path, command.source_file, command.line)
        if (not _should_skip_localized_checks(command)) and _looks_localized(command.description):
            _add_issue(result, "warning", "localized_description", "Command description looks non-English.", command.path, command.source_file, command.line)
        if not command.description:
            _add_issue(result, "warning", "missing_description", "Command description is missing.", command.path, command.source_file, command.line)

        for param in command.params:
            if not param.description:
                _add_issue(result, "warning", "missing_param_description", f"Parameter '{param.name}' is missing a description.", command.path, command.source_file, param.line)
            elif (not _should_skip_localized_checks(command)) and _looks_localized(param.description):
                _add_issue(result, "warning", "localized_param_description", f"Parameter '{param.name}' description looks non-English.", command.path, command.source_file, param.line)
            if param.required and param.name not in CONFIG_TARGET_NAMES and any(token in command.action for token in ("set", "config", "template", "policy", "show")):
                _add_issue(result, "warning", "required_param", f"Parameter '{param.name}' is required in a configuration-style command; verify it is indispensable.", command.path, command.source_file, param.line)

        if command.path in LOCALIZED_COMMAND_EXCEPTIONS or command.root in LOCALIZED_ROOT_EXCEPTIONS:
            result.exceptions.append(command.path)

    for parent, commands in by_parent.items():
        action_names = {command.action for command in commands}
        path_label = parent or "<root>"
        if "on" in action_names and not {"on", "off", "status"}.issubset(action_names):
            missing = ", ".join(sorted({"on", "off", "status"} - action_names))
            _add_issue(result, "error", "toggle_triad", f"Missing on/off/status triad members: {missing}.", path_label)
        if "config_set" in action_names:
            missing = [name for name in ("config_show", "config_reset") if name not in action_names]
            if missing:
                _add_issue(result, "error", "config_triad", f"Missing config companions: {', '.join(missing)}.", path_label)
        if "entry_add" in action_names:
            missing = [name for name in ("entry_edit", "entry_remove", "entry_show", "entry_list") if name not in action_names]
            if missing:
                _add_issue(result, "error", "entry_family", f"Missing entry companions: {', '.join(missing)}.", path_label)
        for action in sorted(action_names):
            if not action.endswith("_set"):
                continue
            if not (action.startswith("template_") or action.endswith("scope_set") or "template" in action or "scope" in action):
                continue
            stem = action[:-4]
            missing = [name for name in (f"{stem}_show", f"{stem}_reset") if name not in action_names]
            if missing:
                _add_issue(result, "error", "template_scope_triad", f"Missing template/scope companions for '{action}': {', '.join(missing)}.", path_label)

        plain_show = [name for name in action_names if name == "show"]
        plain_list = [name for name in action_names if name == "list"]
        if plain_show and plain_list:
            _add_issue(result, "warning", "show_list_overlap", "Parent exposes both plain 'show' and plain 'list'; verify there is no semantic duplication.", path_label)

    result.commands.sort(key=lambda item: item.path)
    result.issues.sort(key=lambda issue: (issue.severity, issue.code, issue.path, issue.line or 0))
    result.exceptions = sorted(set(result.exceptions))
    return result




def validate_command_tree() -> ValidationResult:
    return _validate_commands(_build_command_records())


def _inventory_rows(commands: list[CommandRecord]) -> list[str]:
    rows = ["| Root | Subgroup | Action | Description | Source |", "| --- | --- | --- | --- | --- |"]
    for command in commands:
        subgroup = command.subgroup or "—"
        description = (command.description or "").replace("|", "\\|")
        source = f"`{command.source_file}:{command.line}`"
        rows.append(f"| `{command.root}` | `{subgroup}` | `{command.action}` | {description} | {source} |")
    return rows


def render_markdown_report(result: ValidationResult) -> str:
    error_count = len(result.errors)
    warning_count = len(result.warnings)
    lines = [
        "# Command Tree Validation Report",
        "",
        "Questo report inventaria i comandi realmente registrati nel repository. Per il vocabolario canonico delle action e la loro semantica normativa fa fede `docs/command_standards.md`; le action composte (`config_set`, `schedule_add`, `template_global_reset`, ecc.) vanno lette come estensioni dei verbi canonici e non introducono nuove action standard.",
        "",
        f"- Commands discovered: **{len(result.commands)}**",
        f"- Errors: **{error_count}**",
        f"- Warnings: **{warning_count}**",
        "",
        "## Inventory",
        "",
        * _inventory_rows(result.commands),
        "",
        "## Issues",
        "",
    ]
    if result.issues:
        for issue in result.issues:
            location = f" (`{issue.source_file}:{issue.line}`)" if issue.source_file and issue.line else ""
            lines.append(f"- **{issue.severity.upper()} {issue.code}** — `{issue.path}`: {issue.message}{location}")
    else:
        lines.append("- No validator errors or warnings.")
    lines.extend(["", "## Localized exceptions", ""])
    if result.exceptions:
        lines.append("The following commands remain intentionally localized and are excluded from the English-only rule for now:")
        lines.extend(f"- `{path}`" for path in result.exceptions)
    else:
        lines.append("- No localized exceptions are configured.")
    lines.extend([
        "",
        "## Usage",
        "",
        "- Run `python -m scripts.validate_commands` for a console report.",
        "- Run `python -m scripts.validate_commands --write-report` to refresh this markdown file.",
        "- Run `pytest tests/test_command_standard_validator.py` to fail CI on validator errors.",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Barcellometro slash-command naming and structure.")
    parser.add_argument("--write-report", action="store_true", help="Write the markdown report to docs/command_tree_report.md.")
    parser.add_argument("--json", action="store_true", help="Print the validation summary as JSON.")
    args = parser.parse_args()

    result = validate_command_tree()
    payload = {
        "commands": [command.path for command in result.commands],
        "errors": [issue.__dict__ if hasattr(issue, "__dict__") else {"severity": issue.severity, "code": issue.code, "message": issue.message, "path": issue.path, "source_file": issue.source_file, "line": issue.line} for issue in result.errors],
        "warnings": [issue.__dict__ if hasattr(issue, "__dict__") else {"severity": issue.severity, "code": issue.code, "message": issue.message, "path": issue.path, "source_file": issue.source_file, "line": issue.line} for issue in result.warnings],
        "exceptions": result.exceptions,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Discovered {len(result.commands)} commands.")
        print(f"Errors: {len(result.errors)} | Warnings: {len(result.warnings)}")
        for issue in result.errors + result.warnings:
            location = f" ({issue.source_file}:{issue.line})" if issue.source_file and issue.line else ""
            print(f"[{issue.severity.upper()}] {issue.code} {issue.path}: {issue.message}{location}")

    if args.write_report:
        DEFAULT_REPORT_PATH.write_text(render_markdown_report(result))
        print(f"Wrote report to {DEFAULT_REPORT_PATH.relative_to(REPO_ROOT)}")

    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
