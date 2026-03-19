from app.services.barcello_window_defaults import resolve_window_minutes


def test_resolve_window_minutes_uses_default_without_overrides() -> None:
    cfg = {"window_minutes": 60}
    assert resolve_window_minutes("123", default_window=60, trigger_config=cfg) == 60


def test_resolve_window_minutes_uses_channel_override_when_valid() -> None:
    cfg = {
        "channel_overrides": {
            "123": {"window_minutes": 30},
        }
    }
    assert resolve_window_minutes("123", default_window=60, trigger_config=cfg) == 30


def test_resolve_window_minutes_falls_back_on_invalid_override() -> None:
    cfg = {
        "channel_overrides": {
            "123": {"window_minutes": "bad"},
        }
    }
    assert resolve_window_minutes("123", default_window=60, trigger_config=cfg) == 60
