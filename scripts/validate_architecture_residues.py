from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOTS = ("app", "scripts", "tests")

LEGACY_SHIM_MODULES = {
    "app/services/server_activity_report_service.py": {
        "canonical_module": "app.services.channel_summary_service",
        "reason": "Alias module storico mantenuto per compatibilità mentre il bot usa ancora il nome DailyResocontoService.",
    },
}

BANNED_IMPORT_PREFIXES = {
    "app.features": "Usare i package canonici sotto app/services, app/renderers e app/plugins/commands_modular.",
}

BANNED_IMPORT_MODULES = {
    "app.services.server_activity_report_service": "Usare app.services.channel_summary_service.",
    "app.services.aura_render": "Usare app.renderers.aura_renderer.",
}


TEST_SOURCE_TARGET_EXCEPTIONS = {
    "tests/test_validate_architecture_residues.py",
}

DOCUMENTED_IMPORT_EXCEPTIONS = {
    ("app/core/bot.py", "app.services.server_activity_report_service"): (
        "Eccezione temporanea documentata: il bot espone ancora DailyResocontoService tramite lo shim "
        "legacy finché il wiring runtime non viene aggiornato."
    ),
}

RULES = (
    (
        "shim_import_targets",
        "Gli shim legacy non devono importare moduli o simboli che non esistono più.",
    ),
    (
        "package_reexports",
        "I package __init__.py non devono re-exportare moduli o simboli rinominati/non presenti.",
    ),
    (
        "test_source_targets",
        "I test source-based non devono puntare a file shim legacy quando esiste il modulo reale.",
    ),
    (
        "legacy_imports",
        "Gli import Python non devono usare path legacy non consentiti, salvo eccezioni documentate.",
    ),
    (
        "legacy_shims",
        "Gli shim legacy ancora presenti devono essere segnalati come WARNING.",
    ),
)


@dataclass(slots=True)
class Issue:
    severity: str
    rule: str
    code: str
    path: str
    message: str


@dataclass(slots=True)
class ValidationReport:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    def add(self, severity: str, rule: str, code: str, path: Path, message: str) -> None:
        issue = Issue(severity=severity, rule=rule, code=code, path=path.as_posix(), message=message)
        if severity == "error":
            self.errors.append(issue)
        else:
            self.warnings.append(issue)

    @property
    def exit_code(self) -> int:
        return 1 if self.errors else 0


def _iter_python_files(root: Path) -> list[Path]:
    ignored_parts = {".git", ".venv", ".pytest_cache", "__pycache__"}
    return sorted(
        path
        for path in root.rglob("*.py")
        if path.is_file() and not any(part in ignored_parts for part in path.parts)
    )


def _relative(root: Path, path: Path) -> Path:
    return path.relative_to(root)


def _path_to_module(root: Path, path: Path) -> str | None:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return None
    parts = list(rel.parts)
    if not parts or parts[0] not in PYTHON_ROOTS:
        return None
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = path.stem
    return ".".join(parts)


def _is_repo_module_name(module_name: str) -> bool:
    return any(module_name == root_name or module_name.startswith(f"{root_name}.") for root_name in PYTHON_ROOTS)


def _module_to_file(root: Path, module_name: str) -> Path | None:
    if not _is_repo_module_name(module_name):
        return None
    module_path = root / Path(*module_name.split("."))
    file_path = module_path.with_suffix(".py")
    if file_path.exists():
        return file_path
    init_path = module_path / "__init__.py"
    if init_path.exists():
        return init_path
    return None


def _resolve_imported_module(root: Path, importer: Path, node: ast.ImportFrom) -> str | None:
    importer_module = _path_to_module(root, importer)
    if importer_module is None:
        return None

    package_parts = importer_module.split(".")
    current_package = package_parts if importer.name == "__init__.py" else package_parts[:-1]

    if node.level:
        if node.level > len(current_package):
            return None
        base_parts = current_package[: len(current_package) - node.level + 1]
    else:
        base_parts = []

    if node.module:
        base_parts.extend(node.module.split("."))

    return ".".join(part for part in base_parts if part)


@dataclass(slots=True)
class ModuleInfo:
    path: Path
    defined_names: set[str]
    exported_names: set[str] | None
    has_dynamic_getattr: bool


def _literal_string_list(node: ast.AST) -> list[str] | None:
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return None
    values: list[str] = []
    for item in node.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            return None
        values.append(item.value)
    return values


def _collect_module_info(root: Path, path: Path, cache: dict[Path, ModuleInfo]) -> ModuleInfo:
    cached = cache.get(path)
    if cached is not None:
        return cached

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    defined_names: set[str] = set()
    exported_names: set[str] | None = None
    has_dynamic_getattr = False

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined_names.add(node.name)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "__getattr__":
                has_dynamic_getattr = True
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound_name = alias.asname or alias.name.split(".")[-1]
                defined_names.add(bound_name)
            continue
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defined_names.add(target.id)
                    if target.id == "__all__":
                        exported_names = set(_literal_string_list(node.value) or [])
            continue
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined_names.add(node.target.id)

    info = ModuleInfo(
        path=path,
        defined_names=defined_names,
        exported_names=exported_names,
        has_dynamic_getattr=has_dynamic_getattr,
    )
    cache[path] = info
    return info


def _package_has_submodule(package_path: Path, name: str) -> bool:
    if package_path.name != "__init__.py":
        return False
    package_dir = package_path.parent
    return (package_dir / f"{name}.py").exists() or (package_dir / name / "__init__.py").exists()


def _module_has_name(root: Path, module_name: str, name: str, cache: dict[Path, ModuleInfo]) -> bool:
    module_path = _module_to_file(root, module_name)
    if module_path is None:
        return False
    info = _collect_module_info(root, module_path, cache)
    if name in info.defined_names:
        return True
    if _package_has_submodule(module_path, name):
        return True
    return False




def _check_shim_import_targets(root: Path, report: ValidationReport, cache: dict[Path, ModuleInfo]) -> None:
    for shim_rel, meta in LEGACY_SHIM_MODULES.items():
        shim_path = root / shim_rel
        if not shim_path.exists():
            continue
        tree = ast.parse(shim_path.read_text(encoding="utf-8"), filename=str(shim_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported_module = _resolve_imported_module(root, shim_path, node)
                if imported_module is None:
                    continue
                target_path = _module_to_file(root, imported_module)
                if target_path is None:
                    report.add(
                        "error",
                        "shim_import_targets",
                        "missing_shim_target_module",
                        _relative(root, shim_path),
                        f"Shim legacy importa il modulo '{imported_module}' che non esiste più.",
                    )
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    if not _module_has_name(root, imported_module, alias.name, cache):
                        report.add(
                            "error",
                            "shim_import_targets",
                            "missing_shim_target_name",
                            _relative(root, shim_path),
                            f"Shim legacy importa '{alias.name}' da '{imported_module}', ma il simbolo non è più presente.",
                        )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if _module_to_file(root, alias.name) is None:
                        report.add(
                            "error",
                            "shim_import_targets",
                            "missing_shim_import",
                            _relative(root, shim_path),
                            f"Shim legacy importa '{alias.name}', ma il modulo non esiste più nel repo.",
                        )


def _check_package_reexports(root: Path, report: ValidationReport, cache: dict[Path, ModuleInfo]) -> None:
    for path in _iter_python_files(root):
        if path.name != "__init__.py":
            continue
        rel = _relative(root, path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        local_info = _collect_module_info(root, path, cache)

        for node in tree.body:
            if not isinstance(node, ast.ImportFrom):
                continue
            imported_module = _resolve_imported_module(root, path, node)
            if imported_module is None:
                continue
            if not _is_repo_module_name(imported_module):
                continue
            target_path = _module_to_file(root, imported_module)
            if target_path is None:
                report.add(
                    "error",
                    "package_reexports",
                    "missing_reexport_module",
                    rel,
                    f"Re-export da '{imported_module}' non valido: il modulo non esiste più.",
                )
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                if not _module_has_name(root, imported_module, alias.name, cache):
                    report.add(
                        "error",
                        "package_reexports",
                        "missing_reexport_name",
                        rel,
                        f"Re-export '{alias.name}' da '{imported_module}' non valido: simbolo assente.",
                    )

        if local_info.exported_names is not None and not local_info.has_dynamic_getattr:
            for exported_name in sorted(local_info.exported_names):
                if exported_name not in local_info.defined_names and not _package_has_submodule(path, exported_name):
                    report.add(
                        "error",
                        "package_reexports",
                        "missing___all___binding",
                        rel,
                        f"__all__ espone '{exported_name}', ma il nome non è definito nel package.",
                    )


def _check_test_source_targets(root: Path, report: ValidationReport) -> None:
    tests_root = root / "tests"
    if not tests_root.exists():
        return
    shim_targets = set(LEGACY_SHIM_MODULES)
    for path in _iter_python_files(tests_root):
        text = path.read_text(encoding="utf-8")
        rel = _relative(root, path)
        if rel.as_posix() in TEST_SOURCE_TARGET_EXCEPTIONS:
            continue
        for shim_rel in sorted(shim_targets):
            if shim_rel in text:
                canonical_module = LEGACY_SHIM_MODULES[shim_rel]["canonical_module"]
                canonical_path = _module_to_file(root, canonical_module)
                replacement = canonical_path.relative_to(root).as_posix() if canonical_path else canonical_module
                report.add(
                    "error",
                    "test_source_targets",
                    "legacy_shim_test_target",
                    rel,
                    f"Test source-based punta allo shim legacy '{shim_rel}'; usare il modulo reale '{replacement}'.",
                )


def _matches_banned_import(module_name: str) -> tuple[str, str] | None:
    if module_name in BANNED_IMPORT_MODULES:
        return module_name, BANNED_IMPORT_MODULES[module_name]
    for prefix, message in BANNED_IMPORT_PREFIXES.items():
        if module_name == prefix or module_name.startswith(f"{prefix}."):
            return prefix, message
    return None


def _check_legacy_imports(root: Path, report: ValidationReport) -> None:
    for path in _iter_python_files(root):
        rel = _relative(root, path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    match = _matches_banned_import(alias.name)
                    if match is None:
                        continue
                    rule_key, message = match
                    exception_message = DOCUMENTED_IMPORT_EXCEPTIONS.get((rel.as_posix(), alias.name))
                    if exception_message:
                        report.add(
                            "warning",
                            "legacy_imports",
                            "documented_legacy_import_exception",
                            rel,
                            f"Import legacy consentito solo come eccezione documentata ('{alias.name}'): {exception_message}",
                        )
                        continue
                    report.add(
                        "error",
                        "legacy_imports",
                        "legacy_import_path",
                        rel,
                        f"Import legacy '{alias.name}' non consentito. {message}",
                    )
            elif isinstance(node, ast.ImportFrom):
                imported_module = _resolve_imported_module(root, path, node)
                if not imported_module:
                    continue
                match = _matches_banned_import(imported_module)
                if match is None:
                    continue
                rule_key, message = match
                exception_message = DOCUMENTED_IMPORT_EXCEPTIONS.get((rel.as_posix(), imported_module))
                if exception_message:
                    report.add(
                        "warning",
                        "legacy_imports",
                        "documented_legacy_import_exception",
                        rel,
                        f"Import legacy consentito solo come eccezione documentata ('{imported_module}'): {exception_message}",
                    )
                    continue
                report.add(
                    "error",
                    "legacy_imports",
                    "legacy_import_path",
                    rel,
                    f"Import legacy '{imported_module}' non consentito. {message}",
                )


def _check_legacy_shims(root: Path, report: ValidationReport) -> None:
    for shim_rel, meta in sorted(LEGACY_SHIM_MODULES.items()):
        shim_path = root / shim_rel
        if not shim_path.exists():
            continue
        canonical_module = meta["canonical_module"]
        canonical_path = _module_to_file(root, canonical_module)
        replacement = canonical_path.relative_to(root).as_posix() if canonical_path else canonical_module
        report.add(
            "warning",
            "legacy_shims",
            "legacy_shim_present",
            _relative(root, shim_path),
            f"Shim legacy ancora presente; modulo reale: '{replacement}'. {meta['reason']}",
        )


def validate_architecture_residues(repo_root: Path = REPO_ROOT) -> ValidationReport:
    report = ValidationReport()
    cache: dict[Path, ModuleInfo] = {}
    _check_shim_import_targets(repo_root, report, cache)
    _check_package_reexports(repo_root, report, cache)
    _check_test_source_targets(repo_root, report)
    _check_legacy_imports(repo_root, report)
    _check_legacy_shims(repo_root, report)
    return report


def _print_report(report: ValidationReport) -> None:
    print("Architecture residue validation")
    print("Implemented rules:")
    for _, description in RULES:
        print(f"- {description}")
    print()

    issues_by_rule: dict[str, list[Issue]] = {rule: [] for rule, _ in RULES}
    for issue in report.errors + report.warnings:
        issues_by_rule.setdefault(issue.rule, []).append(issue)

    for rule, description in RULES:
        issues = issues_by_rule.get(rule, [])
        if not issues:
            print(f"OK [{rule}] {description}")
            continue
        for issue in issues:
            label = issue.severity.upper()
            print(f"{label} [{issue.code}] {issue.path}: {issue.message}")

    print()
    print(f"Summary: {len(report.errors)} error(s), {len(report.warnings)} warning(s).")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate legacy architectural residues after the project refactor.")
    parser.parse_args(argv)
    report = validate_architecture_residues()
    _print_report(report)
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
