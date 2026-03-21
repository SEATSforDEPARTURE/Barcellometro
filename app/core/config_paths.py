from __future__ import annotations

from os import PathLike
from pathlib import Path

PathInput = str | PathLike[str]
SETTINGS_DIR = Path("settings")

ENTITLEMENTS_JSON = SETTINGS_DIR / "entitlements.json"
ENTITLEMENTS_EXAMPLE_JSON = SETTINGS_DIR / "entitlements.example.json"
AURA_RULES_JSON = SETTINGS_DIR / "aura_rules.json"
AURA_RULES_EXAMPLE_JSON = SETTINGS_DIR / "aura_rules.example.json"
AURA_ARCHETYPES_JSON = SETTINGS_DIR / "aura_archetypes.json"
AURA_ARCHETYPES_EXAMPLE_JSON = SETTINGS_DIR / "aura_archetypes.example.json"
AURA_MISSIONS_JSON = SETTINGS_DIR / "aura_missions.json"
AURA_MISSIONS_EXAMPLE_JSON = SETTINGS_DIR / "aura_missions.example.json"
BARCELLO_TRIGGER_JSON = SETTINGS_DIR / "barcello_trigger.json"
BARCELLO_TRIGGER_EXAMPLE_JSON = SETTINGS_DIR / "barcello_trigger.example.json"
GREETINGS_TRIGGER_JSON = SETTINGS_DIR / "greetings_trigger.json"
GREETINGS_TRIGGER_EXAMPLE_JSON = SETTINGS_DIR / "greetings_trigger.example.json"


_CANONICAL_SETTINGS_FILES = {
    "entitlements.json": ENTITLEMENTS_JSON,
    "entitlements.example.json": ENTITLEMENTS_EXAMPLE_JSON,
    "aura_rules.json": AURA_RULES_JSON,
    "aura_rules.example.json": AURA_RULES_EXAMPLE_JSON,
    "aura_archetypes.json": AURA_ARCHETYPES_JSON,
    "aura_archetypes.example.json": AURA_ARCHETYPES_EXAMPLE_JSON,
    "aura_missions.json": AURA_MISSIONS_JSON,
    "aura_missions.example.json": AURA_MISSIONS_EXAMPLE_JSON,
    "barcello_trigger.json": BARCELLO_TRIGGER_JSON,
    "barcello_trigger.example.json": BARCELLO_TRIGGER_EXAMPLE_JSON,
    "greetings_trigger.json": GREETINGS_TRIGGER_JSON,
    "greetings_trigger.example.json": GREETINGS_TRIGGER_EXAMPLE_JSON,
}


def normalize_config_path(path: PathInput) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate

    parts = candidate.parts
    if len(parts) >= 2 and parts[0] == "settings":
        normalized = SETTINGS_DIR.joinpath(*parts[1:])
        return _CANONICAL_SETTINGS_FILES.get(normalized.name, normalized)
    if len(parts) >= 3 and parts[0] == "app" and parts[1] == "settings":
        normalized = SETTINGS_DIR.joinpath(*parts[2:])
        return _CANONICAL_SETTINGS_FILES.get(normalized.name, normalized)

    return _CANONICAL_SETTINGS_FILES.get(candidate.name, candidate)


def example_config_path(path: PathInput) -> Path:
    runtime_path = normalize_config_path(path)
    name = runtime_path.name
    if name.endswith(".example.json"):
        return runtime_path
    if name.endswith(".jsonc"):
        stem = name[:-len(".jsonc")]
    elif name.endswith(".json"):
        stem = name[:-len(".json")]
    else:
        stem = runtime_path.stem
    return runtime_path.with_name(f"{stem}.example.json")


def resolve_config_path(path: PathInput, *, example_path: PathInput | None = None) -> tuple[Path | None, bool]:
    runtime_path = normalize_config_path(path)
    if runtime_path.exists():
        return runtime_path, False

    fallback_path = normalize_config_path(example_path) if example_path is not None else example_config_path(runtime_path)
    if fallback_path.exists():
        return fallback_path, True

    return None, False
