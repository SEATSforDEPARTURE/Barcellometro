from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "app/plugins/commands_modular/barcellometro_attivita_logic.py"
spec = importlib.util.spec_from_file_location("barcellometro_attivita_logic", MODULE_PATH)
logic = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(logic)


class _FakeDatabase:
    def __init__(self, cfg: dict | None = None) -> None:
        self.cfg = cfg
        self.upserts: list[dict] = []

    async def get_activity_monitoring_config(self, guild_id: str):
        return self.cfg

    async def upsert_activity_monitoring_config(self, guild_id: str, *, enabled: bool, mod_channel_id: str | None, send_time_local: str) -> None:
        self.upserts.append(
            {
                "guild_id": guild_id,
                "enabled": enabled,
                "mod_channel_id": mod_channel_id,
                "send_time_local": send_time_local,
            }
        )


class _FakeDailyReport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def send_now(self, *, guild_id: str, mod_channel_id: str) -> None:
        self.calls.append((guild_id, mod_channel_id))


def test_attivita_ora_sets_time_only_and_does_not_call_send_now() -> None:
    db = _FakeDatabase(cfg={"enabled": 1, "mod_channel_id": "123"})
    report = _FakeDailyReport()

    mod_channel = asyncio.run(logic.set_activity_send_time(db, guild_id="1", hhmm="20:30"))

    assert mod_channel == "123"
    assert db.upserts and db.upserts[0]["send_time_local"] == "20:30"
    assert report.calls == []


def test_attivita_invia_calls_send_now() -> None:
    db = _FakeDatabase(cfg={"enabled": 1, "mod_channel_id": "555"})
    report = _FakeDailyReport()

    mod_channel = asyncio.run(logic.send_activity_now(db, report, guild_id="77"))

    assert mod_channel == "555"
    assert report.calls == [("77", "555")]


def test_validate_hhmm_accepts_and_rejects_values() -> None:
    assert logic.validate_hhmm("20:30") is None
    assert logic.validate_hhmm("25:00") is not None
    assert logic.validate_hhmm("ab:cd") is not None
    assert logic.validate_hhmm("9:00") is not None
