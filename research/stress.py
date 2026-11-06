"""Execution stress beyond one tick (backlog item 84). Pure.

Venue costs (measured: fees zero on SIG contest books) stay SEPARATE from
sensitivity scenarios (assumed, labeled with magnitude). Scenarios apply
to a planned exit (legs with prices/qtys, paired cost, floor):
- delayed: fill slips N ticks worse per leg (latency model).
- vanish: top K depth levels disappear pre-fill (re-walk remaining book).
- partial: fraction F fills at limit, rest repriced W ticks worse.
- outage: one leg never fills (orphan) — residual valued at floor plus
  single-leg mark (the nightmare case, quantified not hidden).
Each scenario returns stressed proceeds + edge + floor verdict. A plan
whose edge survives all four at stated magnitudes is robust; the first
scenario that breaks it names the fragility (report it, don't average).
"""
TICK = 0.005


def apply_delay(legs, ticks):
    """Shift every leg price down (sell) by ticks. legs: [(price, qty)]."""
    try:
        return [(round(float(p) - int(ticks) * TICK, 4), int(q))
                for p, q in legs]
    except (TypeError, ValueError):
        return None


def apply_vanish(levels_per_leg, drop_levels=2):
    """Remove top-K levels per leg; returns remaining ladders (may empty)."""
    try:
        return [list(lv[int(drop_levels):]) for lv in levels_per_leg]
    except (TypeError, ValueError):
        return None


def walk_proceeds(ladder, qty):
    """Proceeds selling qty into [(price, size)] best-first, or None when
    depth insufficient (unfillable remainder is NOT assumed)."""
    try:
        need, total = int(qty), 0.0
        for p, s in ladder:
            take = min(need, float(s))
            total += take * float(p)
            need -= take
            if need <= 0:
                break
        return round(total, 2) if need <= 0 else None
    except (TypeError, ValueError):
        return None


def partial_fill(limit_proceeds, qty, fill_frac, worse_ticks):
    """F fills at limit; rest repriced worse_ticks down per share."""
    try:
        f = float(fill_frac)
        q = int(qty)
        rest_px = float(limit_proceeds) / q - int(worse_ticks) * TICK
        return round(f * float(limit_proceeds) + (q - f * q) * rest_px, 2)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def orphan_residual(filled_leg_proceeds, stranded_qty, stranded_mark,
                    floor_intact):
    """One leg filled, other never does: cash + stranded marked at current
    bid (honest mark, not hope) + floor flag. Returns dict."""
    try:
        return {'cash': round(float(filled_leg_proceeds), 2),
                'stranded_mark': round(int(stranded_qty) * float(stranded_mark), 2),
                'floor_intact': bool(floor_intact)}
    except (TypeError, ValueError):
        return None
