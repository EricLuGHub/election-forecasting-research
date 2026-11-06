"""October-2 trial replay, predeclared horizons (backlog item 59). Pure.

Replays trial ENTRY legs (read-only journal records — their lane, our
read-only analysis) with three predeclared exit policies. All prices in
EXIT-instrument units; exit_side is the opposite of entry_side (sells
exit into bids, buy-backs into asks):
- H5/H10/H30: exit everything at first touch on/after entry+5/10/30 min.
- VALUE: exit at first touch reaching cost+gain/share (validated-profit
  doctrine); else hold to horizon end marked at touch — losers included,
  marked honestly, never skipped.
- ACTUAL: recorded exit fills where joinable (diagnostic comparison).
Every entry leg replays (no fill-based selection). Paper touches,
optimistic — the comparison across policies is the result, not the
absolute dollars.
"""


def _ts(at):
    from datetime import datetime
    if isinstance(at, (int, float)):
        return float(at)
    try:
        return datetime.fromisoformat(str(at).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def touch_at(series, t, exit_side):
    """First executable touch at/after t for the EXIT."""
    for ts, b, a in series:
        if ts < t:
            continue
        try:
            return float(b) if exit_side == 'sell' else float(a)
        except (TypeError, ValueError):
            continue
    return None


def replay(entries, books, horizons=(300.0, 600.0, 1800.0), gain=0.01):
    """entries: [(eid, ts, entry_side, qty, price)]. Returns per-policy
    totals + per-leg rows. Values in $."""
    out = {'h5': 0.0, 'h10': 0.0, 'h30': 0.0, 'value': 0.0, 'legs': []}
    for eid, ts, entry_side, qty, price in entries:
        t = _ts(ts)
        try:
            q, p = float(qty), float(price)
        except (TypeError, ValueError):
            continue
        if t is None or q <= 0:
            continue
        exit_side = 'buy' if entry_side == 'sell' else 'sell'
        series = sorted(books.get(str(eid), []))
        cost = q * p
        row = {'eid': str(eid), 'qty': q, 'cost': round(cost, 2)}
        for key, h in zip(('h5', 'h10', 'h30'), horizons):
            px = touch_at(series, t + h, exit_side)
            row[key] = round(q * px, 2) if px is not None else None
        tgt = p + gain if exit_side == 'sell' else p - gain
        hit = None
        cap = t + horizons[-1]  # item-106: value exits bound to horizon
        for tt, b, a in series:
            if tt < t or tt > cap:
                continue
            try:
                touch = float(b) if exit_side == 'sell' else float(a)
            except (TypeError, ValueError):
                continue
            if (touch >= tgt) if exit_side == 'sell' else (touch <= tgt):
                hit = touch
                break
        if hit is not None:
            row['value'] = round(q * hit, 2)
        else:
            last = touch_at(series, t + horizons[-1], exit_side)
            row['value'] = round(q * last, 2) if last is not None else None
        out['legs'].append(row)
    for key in ('h5', 'h10', 'h30', 'value'):
        vals = [r[key] for r in out['legs'] if r[key] is not None]
        out[key] = {'proceeds': round(sum(vals), 2),
                    'n': len(vals), 'missing': len(out['legs']) - len(vals)}
    return out
