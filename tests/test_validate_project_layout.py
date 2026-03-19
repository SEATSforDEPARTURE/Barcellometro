from scripts.validate_project_layout import validate_project_layout


def test_project_layout_validator_passes_repo_state() -> None:
    report = validate_project_layout()
    assert report.errors == []
