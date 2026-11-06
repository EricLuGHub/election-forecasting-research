"""Strategy-specific venue feasibility (backlog item 60). Pure.

Retires the "five venues must widen" rule: one liquid, consistently
positive venue justifies a bounded experiment; five wide, toxic venues
justify nothing. Per-venue gate (predeclared bars, not tuned):
- FILL: join fill rate >= 0.30 (patience can work) OR improve fills
  ~1.0 with edge clearing the tick (c216 bounds apply).
- EDGE: marginal-curve best edge >= $15 at rate >= 1c (the $15/1c bars).
- CAPACITY: executable depth >= 250 shares at bar-clearing levels
  (below dust-clip economics, size honestly).
Verdict per venue: feasible (all three) / thin (edge without capacity
or fills) / refused (missing data — not scored, never assumed). Count
of wide venues is not an input anywhere.
"""
MIN_FILL = 0.30
MIN_EDGE = 15.0
MIN_QTY = 250


def feasible(name, join_rate, best_edge, best_qty, depth_at_bar):
    """(verdict, detail). Any None input refuses the venue."""
    for v in (join_rate, best_edge, best_qty, depth_at_bar):
        if v is None:
            return 'refused', {'venue': name, 'reason': 'missing data'}
    try:
        jr, edge, qty, depth = (float(join_rate), float(best_edge),
                                float(best_qty), float(depth_at_bar))
    except (TypeError, ValueError):
        return 'refused', {'venue': name, 'reason': 'bad inputs'}
    fills_ok = jr >= MIN_FILL
    edge_ok = edge >= MIN_EDGE and qty >= MIN_QTY
    cap_ok = depth >= MIN_QTY
    detail = {'venue': name, 'fills_ok': fills_ok, 'edge_ok': edge_ok,
              'cap_ok': cap_ok}
    if fills_ok and edge_ok and cap_ok:
        detail['why'] = 'fill opportunity + net edge + capacity'
        return 'feasible', detail
    miss = [k for k, ok in (('fills', fills_ok), ('edge', edge_ok),
                            ('capacity', cap_ok)) if not ok]
    detail['why'] = 'missing: %s' % ','.join(miss)
    return 'thin', detail
