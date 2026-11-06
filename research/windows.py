"""Time-window comparisons (backlog item 4).

Portfolio `day` is a ROLLING 24h window; leaderboard `1d` is CALENDAR UTC.
All-time `periodPnl` may be null (fall back to verified initial balance).
Every comparison records its window basis + baseline timestamp; like is only
compared with like.
"""
from datetime import datetime, timedelta, timezone

STARTING_BALANCE = 100000.0


def utc_day_bounds(now=None):
    """(start, end) of the current UTC calendar day."""
    now = now or datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def rolling_day_bounds(now=None):
    """(start, end) of the trailing 24h window."""
    now = now or datetime.now(timezone.utc)
    return now - timedelta(hours=24), now


def resolve_alltime_pnl(period_pnl, total_value, starting_balance=STARTING_BALANCE):
    """(value, basis) with explicit fallback instead of null propagation."""
    if period_pnl is not None:
        try:
            return round(float(period_pnl), 2), 'endpoint'
        except (TypeError, ValueError):
            pass
    if total_value is not None:
        try:
            return round(float(total_value) - float(starting_balance), 2), \
                'total-minus-initial-fallback'
        except (TypeError, ValueError):
            pass
    return None, 'unknown'


def label_window(kind, at=None):
    """Human-readable window label with basis, e.g. for logs/digests."""
    at = at or datetime.now(timezone.utc)
    if kind == 'utc_day':
        start, _ = utc_day_bounds(at)
        return 'utc-day since %s' % start.strftime('%Y-%m-%dT%H:%MZ')
    start, _ = rolling_day_bounds(at)
    return 'rolling-24h since %s' % start.strftime('%Y-%m-%dT%H:%MZ')
