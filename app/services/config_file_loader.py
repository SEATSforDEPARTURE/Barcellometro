from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


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
        if ch in {"\"", "'"}:
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


def load_json_file(path: str) -> dict[str, Any]:
    if not path:
        return {}
    if not os.path.exists(path):
        if path == "settings/barcello_trigger.json":
            example_path = path.replace(".json", ".example.json")
            if os.path.exists(example_path):
                logger.warning("%s not found, using example config", path)
                path = example_path
            else:
                return {}
        else:
            return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except OSError:
        logger.exception("Failed to read config file %s", path)
        return {}
    try:
        if path.endswith(".jsonc"):
            raw = _strip_jsonc_comments(raw)
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Invalid JSON in config file %s", path)
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}
