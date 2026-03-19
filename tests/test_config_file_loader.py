from pathlib import Path

from app.core.config_paths import BARCELLO_TRIGGER_JSON, ENTITLEMENTS_JSON
from app.config.file_loader import load_json_file


def test_load_json_file_prefers_runtime_barcello_config(tmp_path: Path, monkeypatch) -> None:
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    runtime = settings_dir / "barcello_trigger.json"
    example = settings_dir / "barcello_trigger.example.json"
    runtime.write_text('{"source":"runtime"}', encoding="utf-8")
    example.write_text('{"source":"example"}', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    loaded = load_json_file(BARCELLO_TRIGGER_JSON)
    assert loaded["source"] == "runtime"


def test_load_json_file_fallbacks_to_example_for_barcello_config(tmp_path: Path, monkeypatch) -> None:
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    example = settings_dir / "barcello_trigger.example.json"
    example.write_text('{"source":"example"}', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    loaded = load_json_file(BARCELLO_TRIGGER_JSON)
    assert loaded["source"] == "example"


def test_load_json_file_fallbacks_to_example_for_any_runtime_config(tmp_path: Path, monkeypatch) -> None:
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    example = settings_dir / "entitlements.example.json"
    example.write_text('{"source":"example"}', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    loaded = load_json_file(ENTITLEMENTS_JSON)
    assert loaded["source"] == "example"


def test_load_json_file_accepts_path_instances(tmp_path: Path, monkeypatch) -> None:
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    runtime = settings_dir / "entitlements.json"
    runtime.write_text('{"source":"runtime"}', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    loaded = load_json_file(runtime)
    assert loaded["source"] == "runtime"


def test_load_json_file_maps_legacy_app_settings_paths_to_root_settings(tmp_path: Path, monkeypatch) -> None:
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    example = settings_dir / "entitlements.example.json"
    example.write_text('{"source":"legacy-example"}', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    loaded = load_json_file("app/settings/entitlements.json")
    assert loaded["source"] == "legacy-example"
