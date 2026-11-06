"""Spread thresholds in VENUE ticks (backlog item 48, fixed per item 101).

Supersedes integer-hundredths arithmetic: ONE venue tick = 0.005 and
all price math goes through research.ticks (to_vticks/from_vticks).
Compare 2/4/6/8-vtick books (1/2/3/4c) under the same execution model:
join fills at join_rate capturing spread/2; improve fills ~always at
spread/2 minus ONE venue tick. Eligible sets at a $0.005 bar: join
[6,8]vt, improve [4,6,8]vt — the c217 conclusions survive unit repair,
and the improve bar refines to 2c+.
"""
from .ticks import to_vticks, VENUE_TICK

TICK = 1  # one venue tick


def bucket_expected(spread_vt, join_rate, side='join'):
    """Expected capture in venue ticks per share attempt."""
    try:
        s, r = int(spread_vt), float(join_rate)
    except (TypeError, ValueError):
        return None
    if s < 0 or not 0 <= r <= 1:
        return None
    if side == 'join':
        return round(r * s / 2, 2)
    if side == 'improve':
        return round(max(s / 2 - TICK, 0), 2)
    return None


def eligible(buckets, side, min_expected=1.0):
    """buckets: [(spread_vt, join_rate)] -> spreads clearing the bar
    (venue ticks)."""
    out = []
    for s, r in buckets:
        e = bucket_expected(s, r, side)
        if e is not None and e >= min_expected:
            out.append(s)
    return sorted(out)
