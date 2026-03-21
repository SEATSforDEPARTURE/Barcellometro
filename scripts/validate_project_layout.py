from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOTS = ("app", "scripts", "tests")
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".jsonc", ".toml", ".yaml", ".yml", ".env", ".example", ".ini"}
ALLOWED_LEGACY_SETTINGS_LITERALS = {
    "README.md",
    "settings/README.md",
    "docs/project_structure_refactor_plan.md",
    "docs/test_suite_audit.md",
    "scripts/validate_project_layout.py",
    "tests/test_validate_project_layout.py",
    "tests/test_config_file_loader.py",
    "tests/test_settings_paths_docs.py",
}
CANONICAL_SETTINGS_FILES = {
    "settings/barcello_trigger.example.json",
    "settings/entitlements.example.json",
    "settings/greetings_trigger.example.json",
    "settings/aura_rules.example.json",
    "settings/aura_archetypes.example.json",
    "settings/aura_missions.example.json",
}
LEGACY_SHIM_PATTERNS = (
    "Compatibility shim",
    "TODO remove after import migration",
    "remove this compatibility shim after imports migrate",
)
SNAKE_CASE_ALLOWED = {"__init__.py"}


@dataclass(slots=True)
class Issue:
    severity: str
    code: str
    path: str
    message: str


@dataclass(slots=True)
class ValidationReport:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    def add(self, severity: str, code: str, path: Path, message: str) -> None:
        issue = Issue(severity=severity, code=code, path=path.as_posix(), message=message)
        if severity == "error":
            self.errors.append(issue)
        else:
            self.warnings.append(issue)

    @property
    def exit_code(self) -> int:
        return 1 if self.errors else 0


def _iter_files(root: Path) -> list[Path]:
    ignored_parts = {".git", ".venv", ".pytest_cache", "__pycache__"}
    return sorted(path for path in root.rglob("*") if path.is_file() and not any(part in ignored_parts for part in path.parts))


def _is_text_candidate(path: Path) -> bool:
    if path.suffix in TEXT_SUFFIXES:
        return True
    return path.name.endswith((".env", ".example", ".example.json"))


def _is_snake_case_python(path: Path) -> bool:
    name = path.name
    if name in SNAKE_CASE_ALLOWED:
        return True
    stem = path.stem
    return bool(stem) and stem == stem.lower() and all(ch.isalnum() or ch == "_" for ch in stem)


def _check_features_dir_absent(report: ValidationReport) -> None:
    features_dir = REPO_ROOT / "app" / "features"
    if features_dir.exists():
        report.add(
            "error",
            "legacy_features_dir",
            features_dir.relative_to(REPO_ROOT),
            "La directory app/features/ non è più ammessa: spostare il codice in app/services, app/renderers o app/plugins/commands_modular.",
        )


def _check_app_settings(report: ValidationReport) -> None:
    settings_dir = REPO_ROOT / "app" / "settings"
    if not settings_dir.exists():
        return
    for path in _iter_files(settings_dir):
        report.add(
            "error",
            "legacy_settings_dir",
            path.relative_to(REPO_ROOT),
            "Nuovi config file non sono ammessi sotto app/settings/; usare settings/ come unica root canonica.",
        )


def _check_legacy_settings_literals(report: ValidationReport) -> None:
    needle = "app/settings/"
    for path in _iter_files(REPO_ROOT):
        rel = path.relative_to(REPO_ROOT)
        if rel.as_posix().startswith(".git/") or rel.as_posix().startswith(".venv/"):
            continue
        if not _is_text_candidate(path):
            continue
        text = path.read_text(encoding="utf-8")
        if needle not in text:
            continue
        if rel.as_posix() in ALLOWED_LEGACY_SETTINGS_LITERALS:
            continue
        report.add(
            "error",
            "legacy_settings_literal",
            rel,
            "Literal legacy 'app/settings/' rilevato fuori dalle eccezioni documentate.",
        )


def _check_runtime_imports(report: ValidationReport) -> None:
    needles = ("from app.features", "import app.features", "app.features.")
    for root_name in PYTHON_ROOTS:
        root = REPO_ROOT / root_name
        if not root.exists():
            continue
        for path in _iter_files(root):
            if path.suffix != ".py":
                continue
            rel = path.relative_to(REPO_ROOT)
            if rel == Path("scripts/validate_project_layout.py"):
                continue
            text = path.read_text(encoding="utf-8")
            if any(needle in text for needle in needles):
                report.add(
                    "error",
                    "legacy_features_import",
                    rel,
                    "Sono vietati import o riferimenti runtime a app.features; usare i package canonici sotto app/services, app/renderers e app/plugins/commands_modular.",
                )


def _check_python_naming(report: ValidationReport) -> None:
    for root_name in PYTHON_ROOTS:
        root = REPO_ROOT / root_name
        if not root.exists():
            continue
        for path in _iter_files(root):
            if path.suffix != ".py":
                continue
            rel = path.relative_to(REPO_ROOT)
            if not _is_snake_case_python(path):
                report.add(
                    "error",
                    "python_naming",
                    rel,
                    "I file Python devono usare snake_case coerente con la naming scheme corrente.",
                )


def _check_settings_catalog(report: ValidationReport) -> None:
    settings_dir = REPO_ROOT / "settings"
    if not settings_dir.exists():
        report.add("error", "missing_settings_dir", Path("settings"), "Directory settings/ mancante.")
        return
    for path in _iter_files(settings_dir):
        rel = path.relative_to(REPO_ROOT)
        if path.name.endswith(".example.json") and rel.as_posix() not in CANONICAL_SETTINGS_FILES:
            report.add(
                "error",
                "unexpected_settings_template",
                rel,
                "Template config non documentato: aggiornare il piano/validator prima di aggiungere nuovi file in settings/.",
            )


def _check_legacy_shims(report: ValidationReport) -> None:
    for root_name in ("app", "scripts", "tests"):
        root = REPO_ROOT / root_name
        if not root.exists():
            continue
        for path in _iter_files(root):
            if path.suffix != ".py":
                continue
            rel = path.relative_to(REPO_ROOT)
            text = path.read_text(encoding="utf-8")
            if rel == Path("scripts/validate_project_layout.py"):
                continue
            if any(pattern in text for pattern in LEGACY_SHIM_PATTERNS):
                report.add(
                    "warning",
                    "legacy_shim",
                    rel,
                    "Compatibility shim legacy ancora presente: mantenere solo se strettamente necessario.",
                )


def validate_project_layout() -> ValidationReport:
    report = ValidationReport()
    _check_features_dir_absent(report)
    _check_app_settings(report)
    _check_legacy_settings_literals(report)
    _check_runtime_imports(report)
    _check_python_naming(report)
    _check_settings_catalog(report)
    _check_legacy_shims(report)
    return report


def _print_report(report: ValidationReport) -> None:
    rules = [
        "ERROR: app/features/ non deve esistere.",
        "ERROR: nessun nuovo file sotto app/settings/.",
        "ERROR: nessun literal hardcoded 'app/settings/' fuori dalle eccezioni documentate.",
        "ERROR: nessun import runtime verso app.features.",
        "ERROR: naming Python in snake_case coerente.",
        "ERROR: nessun nuovo template settings non documentato.",
        "WARNING: shim legacy ancora presenti nel codice.",
    ]
    print("Project layout validation")
    print("Implemented rules:")
    for rule in rules:
        print(f"- {rule}")
    print()

    for issue in report.errors:
        print(f"ERROR [{issue.code}] {issue.path}: {issue.message}")
    for issue in report.warnings:
        print(f"WARNING [{issue.code}] {issue.path}: {issue.message}")

    print()
    print(f"Summary: {len(report.errors)} error(s), {len(report.warnings)} warning(s).")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the repository project layout against the post-refactor rules.")
    parser.parse_args(argv)
    report = validate_project_layout()
    _print_report(report)
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
