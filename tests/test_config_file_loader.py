from pathlib import Path

from app.services.config_file_loader import load_json_file


def test_load_json_file_prefers_runtime_barcello_config(tmp_path: Path, monkeypatch) -> None:
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    runtime = settings_dir / "barcello_trigger.json"
    example = settings_dir / "barcello_trigger.example.json"
    runtime.write_text('{"source":"runtime"}', encoding="utf-8")
    example.write_text('{"source":"example"}', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    loaded = load_json_file("settings/barcello_trigger.json")
    assert loaded["source"] == "runtime"


def test_load_json_file_fallbacks_to_example_for_barcello_config(tmp_path: Path, monkeypatch) -> None:
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    example = settings_dir / "barcello_trigger.example.json"
    example.write_text('{"source":"example"}', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    loaded = load_json_file("settings/barcello_trigger.json")
    assert loaded["source"] == "example"
