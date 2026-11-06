"""Touch-vs-trade-through calibration (item 47 follow-through). Pure.

paperbook bounds join-vs-improve as pessimistic (only trade-throughs
fill a joined quote) vs optimistic (every touch fills). This module
measures where reality sits per venue: for each public trade print,
compare against the PREVAILING touch (best bid for prospective sells,
best ask for prospective buys):
- fill_join: print trades at-or-through our touch (joined quote fills).
- fill_improve: print trades at-or-through touch+1tick (improver fills).
- The tick premium = extra fills bought per tick paid: (improve-join)
  rate vs 1 tick cost on every improved fill.
Inputs: trades [(ts, price, size)] + touch series [(ts, touch)] (same
side convention: touch = the quote we'd join). Prints before our
observation window refuse (no look-behind). All rates with n stated.
"""
from .ticks import VENUE_TICK

TICK = VENUE_TICK  # one venue tick (0.005); item 101 killed the 0.01 twin


def _ts(at):
    from datetime import datetime
    if isinstance(at, (int, float)):
        return float(at)
    try:
        return datetime.fromisoformat(str(at).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def prevailing(touch_series, t):
    """Last touch at/before t, or None (no look-behind)."""
    best = None
    for ts, touch in touch_series:
        if ts <= t:
            best = touch
        else:
            break
    return best


def calibrate(trades, touch_series, tick=TICK, side='buy', max_touch_age_s=None):
    """trades: [(ts, price, size)] (prints are prints; size must be valid
    positive volume — zero/negative sizes refuse the print, not the run).
    touch_series: [(ts, touch)] sorted. side: 'buy' (resting bid fills on
    prints <= touch) or 'sell' (resting offer fills on prints >= touch).
    max_touch_age_s: touches older than this at print time count as stale
    (reported separately — stale-touch fills are not earned fills).
    Returns rates + n or refusal. Symmetric by construction."""
    ts_touch = []
    for t, x in touch_series:
        try:
            ts_touch.append((_ts(t), float(x)))
        except (TypeError, ValueError):
            continue
    ts_touch = [(t, x) for t, x in ts_touch if t is not None]
    ts_touch.sort()
    if side not in ('buy', 'sell'):
        return None
    n = join = improve = stale = 0
    for ts, price, size in trades:
        t = _ts(ts)
        try:
            p = float(price)
            s = float(size)
        except (TypeError, ValueError):
            continue
        if t is None or s <= 0:
            continue
        touch_t = None
        touch = None
        for tt, tx in ts_touch:
            if tt <= t:
                touch_t, touch = tt, tx
            else:
                break
        if touch is None:
            continue
        if max_touch_age_s is not None and t - touch_t > max_touch_age_s:
            stale += 1
            continue
        n += 1
        if side == 'buy':
            if p <= touch + 1e-9:
                join += 1
            if p <= touch + tick + 1e-9:
                improve += 1
        else:
            if p >= touch - 1e-9:
                join += 1
            if p >= touch - tick - 1e-9:
                improve += 1
    if n == 0:
        return None
    return {'n': n, 'join_rate': round(join / n, 3),
            'improve_rate': round(improve / n, 3),
            'extra_per_tick': round((improve - join) / n, 3),
            'stale_touch': stale}
