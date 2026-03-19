from pathlib import Path


def test_env_examples_use_root_settings_paths() -> None:
    for name in ("example.main.env", "example.worker1.env", "example.worker2.env"):
        content = Path(name).read_text(encoding="utf-8")
        assert "ENTITLEMENTS_CONFIG_PATH=settings/entitlements.json" in content
        assert "app/settings/" not in content


def test_readmes_describe_settings_as_source_of_truth() -> None:
    settings_readme = Path("settings/README.md").read_text(encoding="utf-8")
    root_readme = Path("README.md").read_text(encoding="utf-8")

    assert "source of truth" in settings_readme
    assert "`settings/`" in settings_readme
    assert "settings/README.md" in root_readme
    assert "app/settings/" in root_readme
