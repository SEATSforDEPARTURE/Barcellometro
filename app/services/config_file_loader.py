from __future__ import annotations

import json
import logging
from os import PathLike
from pathlib import Path
from typing import Any

from app.core.config_paths import resolve_config_path

logger = logging.getLogger(__name__)
PathInput = str | PathLike[str]


def _strip_jsonc_comments(text: str) -> str:
    result: list[str] = []
    i = 0
    in_string = False
    string_char = ""
    escape = False
    while i < len(text):
        ch = text[i]
        if in_string:
            result.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == string_char:
                in_string = False
            i += 1
            continue
        if ch in {'"', "'"}:
            in_string = True
            string_char = ch
            result.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < len(text):
            next_ch = text[i + 1]
            if next_ch == "/":
                i += 2
                while i < len(text) and text[i] not in {"\n", "\r"}:
                    i += 1
                continue
            if next_ch == "*":
                i += 2
                while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                i += 2
                continue
        result.append(ch)
        i += 1
    return "".join(result)


def load_json_file(path: PathInput | None, *, example_path: PathInput | None = None) -> dict[str, Any]:
    if not path:
        return {}

    resolved_path, used_example = resolve_config_path(path, example_path=example_path)
    if resolved_path is None:
        return {}

    if used_example:
        logger.warning("%s not found, using example config %s", Path(path), resolved_path)

    try:
        raw = resolved_path.read_text(encoding="utf-8")
    except OSError:
        logger.exception("Failed to read config file %s", resolved_path)
        return {}

    try:
        if resolved_path.suffix == ".jsonc":
            raw = _strip_jsonc_comments(raw)
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Invalid JSON in config file %s", resolved_path)
        return {}

    if isinstance(parsed, dict):
        return parsed
    return {}
