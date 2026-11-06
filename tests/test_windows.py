"""Item-4 window tests."""
from datetime import datetime, timezone
from research.windows import (utc_day_bounds, rolling_day_bounds,
                              resolve_alltime_pnl, label_window)


def test_utc_day_bounds():
    now = datetime(2026, 10, 5, 9, 30, tzinfo=timezone.utc)
    start, end = utc_day_bounds(now)
    assert (start.hour, start.minute) == (0, 0)
    assert (end - start).total_seconds() == 86400.0


def test_rolling_day_bounds():
    now = datetime(2026, 10, 5, 9, 30, tzinfo=timezone.utc)
    start, end = rolling_day_bounds(now)
    assert (end - start).total_seconds() == 86400.0
    assert end == now


def test_fallback_basis_labeled():
    assert resolve_alltime_pnl(123.45, 100200.0) == (123.45, 'endpoint')
    assert resolve_alltime_pnl(None, 100200.0) == (200.0, 'total-minus-initial-fallback')
    assert resolve_alltime_pnl(None, None) == (None, 'unknown')
    assert resolve_alltime_pnl('junk', 100200.0) == (200.0, 'total-minus-initial-fallback')


def test_labels_carry_basis():
    assert label_window('utc_day').startswith('utc-day since')
    assert label_window('rolling').startswith('rolling-24h since')
