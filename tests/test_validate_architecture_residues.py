from __future__ import annotations

from pathlib import Path

from scripts.validate_architecture_residues import validate_architecture_residues


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_architecture_residue_validator_matches_current_repo_state() -> None:
    report = validate_architecture_residues()

    assert report.errors == []
    assert any(issue.code == "legacy_shim_present" for issue in report.warnings)
    assert any(issue.code == "documented_legacy_import_exception" for issue in report.warnings)


def test_architecture_residue_validator_flags_missing_shim_target_name(tmp_path: Path) -> None:
    _write(
        tmp_path / "app/services/channel_summary_service.py",
        "class AnotherService:\n    pass\n",
    )
    _write(
        tmp_path / "app/services/server_activity_report_service.py",
        "from app.services.channel_summary_service import ChannelSummaryService\n\nDailyResocontoService = ChannelSummaryService\n",
    )

    report = validate_architecture_residues(tmp_path)

    assert any(issue.code == "missing_shim_target_name" for issue in report.errors)


def test_architecture_residue_validator_flags_broken_package_reexport(tmp_path: Path) -> None:
    _write(tmp_path / "app/pkg/__init__.py", "from app.pkg.missing import renamed\n")

    report = validate_architecture_residues(tmp_path)

    assert any(issue.code == "missing_reexport_module" for issue in report.errors)


def test_architecture_residue_validator_flags_source_based_tests_on_legacy_shim(tmp_path: Path) -> None:
    _write(tmp_path / "app/services/channel_summary_service.py", "class ChannelSummaryService:\n    pass\n")
    _write(
        tmp_path / "app/services/server_activity_report_service.py",
        "from app.services.channel_summary_service import ChannelSummaryService\n\nDailyResocontoService = ChannelSummaryService\n",
    )
    _write(
        tmp_path / "tests/test_source_based.py",
        'from pathlib import Path\n\nsource = Path("app/services/server_activity_report_service.py").read_text()\n',
    )

    report = validate_architecture_residues(tmp_path)

    assert any(issue.code == "legacy_shim_test_target" for issue in report.errors)


def test_architecture_residue_validator_flags_non_documented_legacy_imports(tmp_path: Path) -> None:
    legacy_module = "app" + ".features.summary.services"
    _write(tmp_path / "app/consumer.py", f"from {legacy_module} import report_service\n")

    report = validate_architecture_residues(tmp_path)

    assert any(issue.code == "legacy_import_path" for issue in report.errors)
