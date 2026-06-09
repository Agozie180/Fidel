from datetime import datetime, timezone

from backend.api import FidelRuntime, trade_window


def test_trade_window_splits_utc_day_into_three_parts():
    assert trade_window(datetime(2026, 6, 22, 0, 0, tzinfo=timezone.utc)) == "morning"
    assert trade_window(datetime(2026, 6, 22, 7, 59, tzinfo=timezone.utc)) == "morning"
    assert trade_window(datetime(2026, 6, 22, 8, 0, tzinfo=timezone.utc)) == "afternoon"
    assert trade_window(datetime(2026, 6, 22, 15, 59, tzinfo=timezone.utc)) == "afternoon"
    assert trade_window(datetime(2026, 6, 22, 16, 0, tzinfo=timezone.utc)) == "night"
    assert trade_window(datetime(2026, 6, 22, 23, 59, tzinfo=timezone.utc)) == "night"


def test_only_one_trade_is_available_per_window_per_day():
    runtime = FidelRuntime()
    day = "2026-06-22"
    assert runtime._window_trade_available(day, "morning")
    runtime._record_window_trade(day, "morning")
    assert not runtime._window_trade_available(day, "morning")
    assert runtime._window_trade_available(day, "afternoon")
    assert runtime.daily_trade_count[day] == 1
    runtime._record_window_trade(day, "afternoon")
    runtime._record_window_trade(day, "night")
    assert runtime.daily_trade_count[day] == 3


def test_activity_log_suppresses_duplicate_messages():
    runtime = FidelRuntime()
    assert runtime._log_activity("decision", "CAKE BUY 90%: risk checks passed")
    assert not runtime._log_activity("decision", "CAKE BUY 90%: risk checks passed")
    assert runtime._log_activity("decision", "CAKE BUY 91%: risk checks passed")
    assert len(runtime.activity) == 2

