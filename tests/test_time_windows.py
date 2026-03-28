from datetime import timedelta

from app.plugins.commands_modular.time_windows import rolling_window_timedelta


def test_rolling_window_timedelta_supports_standard_units() -> None:
    assert rolling_window_timedelta(10, "minuti") == timedelta(minutes=10)
    assert rolling_window_timedelta(3, "ore") == timedelta(hours=3)
    assert rolling_window_timedelta(7, "giorni") == timedelta(days=7)
    assert rolling_window_timedelta(2, "settimane") == timedelta(weeks=2)
