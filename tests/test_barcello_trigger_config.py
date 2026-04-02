from __future__ import annotations

import json
import re
import sys
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

if "discord" not in sys.modules:
    discord_stub = types.ModuleType("discord")
    abc_stub = types.SimpleNamespace(Messageable=object)
    discord_stub.abc = abc_stub
    discord_stub.Client = object
    discord_stub.Interaction = object
    sys.modules["discord"] = discord_stub
if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.AsyncOpenAI = object
    sys.modules["openai"] = openai_stub
if "httpx" not in sys.modules:
    httpx_stub = types.ModuleType("httpx")
    httpx_stub.AsyncClient = object
    httpx_stub.Client = object
    sys.modules["httpx"] = httpx_stub

from app.services.triggers_service import TriggerEngineService


def _collect_template_strings(node: object, *, in_templates: bool = False) -> list[str]:
    out: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            out.extend(_collect_template_strings(value, in_templates=in_templates or key == "templates"))
    elif isinstance(node, list):
        if in_templates:
            out.extend(item for item in node if isinstance(item, str))
        else:
            for item in node:
                out.extend(_collect_template_strings(item, in_templates=in_templates))
    return out


def test_barcello_trigger_loader_falls_back_to_example_when_runtime_missing(tmp_path: Path, monkeypatch) -> None:
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    (settings_dir / "barcello_trigger.example.json").write_text(
        json.dumps({"window_minutes": 15, "templates": {"INIT": ["Fallback ok"]}}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    service._barcello_trigger_cfg_path = settings_dir / "barcello_trigger.json"

    cfg = service._load_barcello_trigger_cfg_cached()
    assert cfg["window_minutes"] == 15
    assert cfg["templates"]["INIT"] == ["Fallback ok"]


def test_barcello_trigger_loader_uses_example_when_runtime_is_invalid_json(tmp_path: Path, monkeypatch) -> None:
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    (settings_dir / "barcello_trigger.json").write_text("{", encoding="utf-8")
    (settings_dir / "barcello_trigger.example.json").write_text(
        json.dumps({"window_minutes": 20, "templates": {"INIT": ["Example valid"]}}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    service._barcello_trigger_cfg_path = settings_dir / "barcello_trigger.json"

    cfg = service._load_barcello_trigger_cfg_cached()
    assert cfg["window_minutes"] == 20
    assert cfg["templates"]["INIT"] == ["Example valid"]


def test_barcello_trigger_example_json_is_valid_and_has_core_sections() -> None:
    payload = json.loads(Path("settings/barcello_trigger.example.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert isinstance(payload.get("templates"), dict) and payload["templates"]
    assert isinstance(payload.get("moods"), dict) and payload["moods"]
    assert isinstance(payload.get("scheduled_update_templates"), dict) and payload["scheduled_update_templates"]
    assert isinstance(payload.get("scheduled_update_phrases"), dict) and payload["scheduled_update_phrases"]
    assert isinstance(payload.get("channels"), dict)


def test_barcello_trigger_scheduled_templates_have_required_placeholders() -> None:
    payload = json.loads(Path("settings/barcello_trigger.example.json").read_text(encoding="utf-8"))
    scheduled = payload.get("scheduled_update_templates")
    assert isinstance(scheduled, dict)
    template_strings = _collect_template_strings({"templates": scheduled})
    assert template_strings
    expected = {"{time_phrase}", "{state_label}"}
    assert any(all(token in text for token in expected) for text in template_strings)


def test_barcello_trigger_example_templates_do_not_start_with_emoji() -> None:
    payload = json.loads(Path("settings/barcello_trigger.example.json").read_text(encoding="utf-8"))
    pattern = re.compile(r"^\s*[\U0001F300-\U0001FAFF\u2600-\u27BF]\s*")
    template_strings = _collect_template_strings(payload)
    assert template_strings, "Expected template strings in barcello example config"
    offenders = [text for text in template_strings if pattern.match(text)]
    assert offenders == []


def test_barcello_scheduled_renderer_keeps_required_markdown_structure() -> None:
    payload = json.loads(Path("settings/barcello_trigger.example.json").read_text(encoding="utf-8"))
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    description = service._style_barcello_scheduled_description(
        service._render_barcello_scheduled_description(
            cfg=payload,
            current_color="VERDE",
            score=88,
            trend={"direction": "stable", "delta_score": 0},
            now_rome=datetime(2026, 4, 2, 9, 0),
        )
    )

    assert description.startswith("*") and description.endswith("*")
    assert "***9 in punto***" in description
    assert "Barcy è ***" in description
    assert description.count("***") >= 6


def test_barcello_scheduled_renderer_includes_state_label_for_requested_state() -> None:
    payload = json.loads(Path("settings/barcello_trigger.example.json").read_text(encoding="utf-8"))
    service = TriggerEngineService(Mock(), Mock(), Mock(), Mock(), community_insights=Mock())
    description = service._style_barcello_scheduled_description(
        service._render_barcello_scheduled_description(
            cfg=payload,
            current_color="ROSSO",
            score=20,
            trend={"direction": "down", "delta_score": -4},
            now_rome=datetime(2026, 4, 2, 21, 0),
        )
    )

    allowed_labels = payload["scheduled_update_phrases"]["states"]["ROSSO"]["labels"]
    assert any(f"***{label}***" in description for label in allowed_labels)
