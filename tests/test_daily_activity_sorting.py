from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

MODULE_PATH = Path(__file__).resolve().parents[1] / "app/services/daily_activity_sorting.py"
spec = importlib.util.spec_from_file_location("activity_sorting_service", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def test_sort_channels_like_discord_visual_order() -> None:
    cat_a = SimpleNamespace(id=10, position=1)
    cat_b = SimpleNamespace(id=20, position=2)

    ch_a2 = SimpleNamespace(id=102, position=2, category=cat_a, name="a2", type="text")
    ch_b1 = SimpleNamespace(id=201, position=1, category=cat_b, name="b1", type="voice")
    ch_a1 = SimpleNamespace(id=101, position=1, category=cat_a, name="a1", type="text")
    ch_no_cat = SimpleNamespace(id=999, position=0, category=None, name="zz", type="text")

    ordered = mod.sort_channels_like_discord([ch_a2, ch_b1, ch_no_cat, ch_a1])
    assert [c.id for c in ordered] == [101, 102, 201, 999]


def test_sort_channels_like_discord_type_rank_with_same_position() -> None:
    cat = SimpleNamespace(id=10, position=1)
    text_pos1 = SimpleNamespace(id=11, position=1, category=cat, name="text-1", type="text")
    voice_pos0 = SimpleNamespace(id=12, position=0, category=cat, name="voice-0", type="voice")
    text_pos0 = SimpleNamespace(id=13, position=0, category=cat, name="text-0", type="text")

    ordered = mod.sort_channels_like_discord([text_pos1, voice_pos0, text_pos0])
    assert [c.id for c in ordered] == [13, 11, 12]


def test_sort_channels_like_discord_text_before_voice_even_if_voice_has_lower_position() -> None:
    cat = SimpleNamespace(id=777, position=1)
    pollaio_text = SimpleNamespace(id=21, position=10, category=cat, name="pollaio", type="text")
    pascolo_voice = SimpleNamespace(id=22, position=0, category=cat, name="pascolo", type="voice")

    ordered = mod.sort_channels_like_discord([pascolo_voice, pollaio_text])
    assert [c.id for c in ordered] == [21, 22]


def test_sort_channels_like_discord_orders_by_position_within_same_type_group() -> None:
    cat = SimpleNamespace(id=12, position=1)
    text_1 = SimpleNamespace(id=31, position=2, category=cat, name="text-1", type="text")
    text_2 = SimpleNamespace(id=32, position=1, category=cat, name="text-2", type="text")
    voice_1 = SimpleNamespace(id=33, position=3, category=cat, name="voice-1", type="voice")
    voice_2 = SimpleNamespace(id=34, position=0, category=cat, name="voice-2", type="voice")

    ordered = mod.sort_channels_like_discord([voice_1, text_1, text_2, voice_2])
    assert [c.id for c in ordered] == [32, 31, 34, 33]


def test_sort_inactive_entries_by_recency_then_never_written() -> None:
    entries = [
        {"user_id": 5, "display_name": "Zeta", "last_message_ts": None},
        {"user_id": 2, "display_name": "Beta", "last_message_ts": "2026-02-20T10:00:00+00:00"},
        {"user_id": 3, "display_name": "Gamma", "last_message_ts": "2026-02-20T09:00:00+00:00"},
        {"user_id": 1, "display_name": "Alpha", "last_message_ts": "2026-02-20T11:00:00+00:00"},
        {"user_id": 4, "display_name": "Delta", "last_message_ts": None},
    ]

    ordered = mod.sort_inactive_entries(entries)
    assert [e["user_id"] for e in ordered] == [1, 2, 3, 4, 5]
