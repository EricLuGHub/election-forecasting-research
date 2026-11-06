"""Complete policies vs simple baselines (backlog item 83). Pure.

The complexity under test: E8's rescore-gated exit timing (wait for
confirmation, clip to depth, check conflicts) vs dumb alternatives on
the same baskets:
- hold-to-settlement: floor value (the no-trade baseline for exits).
- first-flag: exit at the FIRST bankable observation (no timing skill).
- gated (actual): exit at the rescore-confirmed observation (what E8-live
  did: idgov/arsen fills are REALIZED, not estimated).
- stressed: every cash number re-run one tick worse per leg (adverse
  execution bound — policy must survive it, per item 84's spirit).

Metric: realized/stressed liquidation cash vs floor. A timing policy
that cannot beat first-flag on the same opportunities is ceremony.
Inputs are per-basket trajectories + fill records; no market access.
"""
TICK = 0.005


def cash(table, basket, rule):
    """table: {basket: {obs_name: proceeds|None, 'floor': f, 'fill': c|None}}.
    rule: 'hold' | 'first' | 'gated'. Returns (cash, basis)."""
    t = table.get(basket, {})
    obs = [(k, v) for k, v in t.items() if k not in ('floor', 'fill')]
    if rule == 'hold':
        return t.get('floor'), 'floor'
    if rule == 'first':
        for k, v in obs:
            if v is not None:
                return v, 'first-obs %s' % k
        return t.get('floor'), 'floor (never flagged)'
    if rule == 'gated':
        if t.get('fill') is not None:
            return t['fill'], 'realized fill'
        flagged = [(k, v) for k, v in obs if v is not None]
        if flagged:
            return flagged[-1][1], 'last-confirmed %s' % flagged[-1][0]
        return t.get('floor'), 'floor (never flagged)'
    return None, 'unknown rule'


def stressed_cash(proceeds, qty, ticks=1, tick=TICK):
    """One-tick-worse per leg bound. Returns None on bad inputs."""
    try:
        return round(float(proceeds) - int(qty) * ticks * tick, 2)
    except (TypeError, ValueError):
        return None


def compare(table, baskets, qty_of):
    """Per basket: {rule: cash} + stressed gated + verdicts."""
    out = {}
    for b in baskets:
        row = {}
        for rule in ('hold', 'first', 'gated'):
            row[rule] = cash(table, b, rule)
        g, basis = row['gated']
        s = stressed_cash(g, qty_of.get(b, 0)) if g is not None else None
        row['gated_stressed'] = (s, 'one-tick-worse')
        h, _ = row['hold']
        f, _ = row['first']
        if g is None or h is None:
            row['verdict'] = 'unmeasurable'
        elif g > f and f is not None and f > h:
            row['verdict'] = 'timing-adds'
        elif g is not None and f is not None and g >= f and g > h:
            row['verdict'] = 'timing-holds'
        elif g <= h:
            row['verdict'] = 'hold-wins'
        else:
            row['verdict'] = 'mixed'
        out[b] = row
    return out
