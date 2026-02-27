from __future__ import annotations

import sys
import types

if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(Row=dict)

if "discord" not in sys.modules:
    discord_stub = types.ModuleType("discord")
    discord_stub.Member = object
    discord_stub.Client = object
    discord_stub.Guild = object
    discord_stub.Object = object
    discord_stub.Interaction = object
    discord_stub.Message = object
    discord_stub.ButtonStyle = types.SimpleNamespace(primary=1, danger=2, secondary=3)
    discord_stub.abc = types.SimpleNamespace(Messageable=object)
    discord_stub.ui = types.SimpleNamespace(
        View=object,
        Button=object,
        button=lambda *args, **kwargs: (lambda fn: fn),
    )
    sys.modules["discord"] = discord_stub

from app.services.inactive_members_moderation import _state_int


class _FakeRow:
    def __init__(self, data: dict[str, object]) -> None:
        self._data = data

    def keys(self):
        return self._data.keys()

    def __getitem__(self, key: str):
        return self._data[key]


def test_state_int_handles_row_dict_and_missing_values() -> None:
    row = _FakeRow({"reminder_count": "2"})
    assert _state_int(row, "reminder_count", 0) == 2
    assert _state_int(row, "missing", 7) == 7
    assert _state_int({"reminder_count": None}, "reminder_count", 3) == 3
    assert _state_int({"reminder_count": "x"}, "reminder_count", 5) == 5
    assert _state_int(None, "reminder_count", 4) == 4
