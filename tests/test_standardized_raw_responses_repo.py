import ast
from pathlib import Path

TARGET_METHODS = {
    ("interaction", "response", "send_message"),
    ("interaction", "followup", "send"),
    ("channel", "send"),
}


def _attribute_chain(node: ast.AST) -> tuple[str, ...] | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return tuple(reversed(parts))
    return None


def _iter_target_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Await):
            call = node.value
        else:
            call = node
        if not isinstance(call, ast.Call):
            continue
        chain = _attribute_chain(call.func)
        if chain in TARGET_METHODS:
            yield chain, call


def test_app_code_no_longer_uses_raw_text_send_calls() -> None:
    violations: list[str] = []

    for path in sorted(Path("app").rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for chain, call in _iter_target_calls(tree):
            if not call.args:
                continue
            violations.append(f"{path}:{call.lineno} uses positional args with {'.'.join(chain)}")

    assert not violations, "\n".join(violations)
