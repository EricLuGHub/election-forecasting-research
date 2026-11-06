"""Convergence probability and time-to-exit, survival view (item 40).

Tracks every qualified basket INCLUDING never-converging ones (right-censored
at last observation) instead of averaging winners alone. Depleted-by-other-
means baskets (e.g. E1 reductions) are censored with a note — a competing
risk, not a convergence.

BIAS NOTE (read before quoting the curve): flags already BANKABLE at the
first observation are left-censored (event happened sometime in
[entry, first-obs]) but are scored at first-obs time. Ignoring that pushes
the curve UP — treat S(t) as an UPPER bound on convergence speed, never as
a promise. With n≈21 the curve is wide; the framework accumulates, the
first estimate merely orients.
"""
import json
import re
from datetime import datetime, timezone


def parse_ts(ts):
    if not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    except ValueError:
        return None
    if dt.tzinfo is None:
        # Salvaged timestamps truncated before the offset. All writer
        # clocks are UTC (see Pi review.log `at` fields); assume UTC rather
        # than drop the observation. Recorded, not hidden.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _salvage(line):
    """Best-effort (basket, state, at) from truncated log lines. State sits
    early in the JSON so flips survive truncation; magnitudes may not."""
    def grab(key):
        m = re.search(r'"%s":\s*"([^"]+)' % key, line)
        return m.group(1) if m else None
    return grab('basket'), grab('state'), grab('at')


def parse_flags(lines):
    """Log lines -> {basket: [(at, state)]}. Rows without timestamps are
    returned separately (counted, never timed)."""
    traj = {}
    timeless = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            basket, state, at = r.get('basket'), r.get('state'), r.get('at')
        except ValueError:
            basket, state, at = _salvage(line)
        if not basket or not state:
            continue
        dt = parse_ts(at)
        if dt is None:
            timeless += 1
            continue
        traj.setdefault(basket, []).append((dt, state))
    for v in traj.values():
        v.sort()
    return traj, timeless


def survival_table(ledger, traj, now, shorts_prefix='shelf-'):
    """Per-basket: entry, first BANKABLE time|None, status, hours.

    status: 'flagged' | 'censored' (never flagged by `now`) |
            'depleted' (paired qty gone via other means — censored w/ note).
    Shorts (no joint-exit concept) are skipped, not censored.
    """
    rows = []
    for name, info in ledger.items():
        if name.startswith(shorts_prefix) and 'floor' not in info:
            continue
        entry = parse_ts(info.get('at'))
        if entry is None:
            continue
        obs = traj.get(name, [])
        flags = [t for t, s in obs if s == 'BANKABLE']
        depleted = any(s == 'depleted' for _, s in obs)
        if flags:
            first = min(flags)
            rows.append({'basket': name, 'entry': entry,
                         'first_flag': first, 'status': 'flagged',
                         'hours': (first - entry).total_seconds() / 3600})
        else:
            last = max([t for t, _ in obs]) if obs else entry
            rows.append({'basket': name, 'entry': entry,
                         'first_flag': None,
                         'status': 'depleted' if depleted else 'censored',
                         'hours': (now - entry).total_seconds() / 3600
                         if not obs else (last - entry).total_seconds() / 3600})
    return rows


def kaplan_meier(rows):
    """Right-censored KM over flagged-event times. Returns [(t_hours,
    S, at_risk)] steps. 'depleted' counts as censored (not an event)."""
    events = sorted(round(r['hours'], 1) for r in rows
                    if r['status'] == 'flagged')
    times = sorted(set(events))
    curve = []
    n = len(rows)
    surv = 1.0
    hrs = [round(r['hours'], 1) for r in rows]
    for t in times:
        at_risk = sum(1 for h in hrs if h >= t)
        d = sum(1 for e in events if e == t)
        if at_risk > 0:
            surv *= (1 - d / at_risk)
        curve.append((round(t, 1), round(surv, 3), at_risk))
    return curve
