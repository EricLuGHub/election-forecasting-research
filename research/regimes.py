"""Time-of-day and regime effects (backlog item 80). Pure.

Split quote flow into weekday/weekend (+ hour-of-day buckets) and compare
width (mean spread), intensity (changes/hour/eid), and continuation
(formed-move follow-through per c201 momentum). Election-night and
scheduled-event samples are OUT OF SAMPLE until they occur — the module
refuses to score regimes with no observations instead of extrapolating
(the item's own warning: a quiet Sunday does not settle weekday flow,
and neither does a loud Monday settle election night).

Fills/toxicity: quote data carries no fills; fill intensity comes from
the fills tape where available (caller-supplied), else reported absent."""
from .momentum import to_mids, summarize


def _ts(at):
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(at).replace('Z', '+00:00'))
    except ValueError:
        return None


def bucketize(rows):
    """[(at, eid, bid, ask)] -> {'weekday': [...], 'weekend': [...]} of
    (ts, eid, spread, mid). Skips bad rows."""
    out = {'weekday': [], 'weekend': []}
    for at, eid, bid, ask in rows:
        dt = _ts(at)
        try:
            b, a = float(bid), float(ask)
        except (TypeError, ValueError):
            continue
        if dt is None or a < b:
            continue
        key = 'weekend' if dt.weekday() >= 5 else 'weekday'
        out[key].append((dt.timestamp(), str(eid), a - b, (a + b) / 2))
    return out


def describe(obs):
    """Width/intensity summary or None when empty (no extrapolation)."""
    if not obs:
        return None
    spreads = [s for _, _, s, _ in obs]
    t0, t1 = min(t for t, _, _, _ in obs), max(t for t, _, _, _ in obs)
    hours = max((t1 - t0) / 3600, 1 / 60)
    eids = {e for _, e, _, _ in obs}
    return {'n': len(obs), 'mean_spread': round(sum(spreads) / len(spreads), 4),
            'changes_per_hour_eid': round(len(obs) / hours / max(len(eids), 1), 1),
            'span_h': round(hours, 1)}


def continuation_by_regime(rows, move_min=0.02):
    """c201-style continuation split by regime. Returns {regime: rate|None}
    plus counts. Thin regimes report None, not noise."""
    books = to_books_regime(rows)
    out = {}
    for regime, rws in books.items():
        mids = to_mids(rws)
        s = summarize(mids, move_min=move_min)
        out[regime] = {'rate': s['total']['continuation_rate'],
                       'n_events': s['total']['n_events']}
    return out


def to_books_regime(rows):
    """[(at, eid, bid, ask)] -> {regime: [(at, eid, bid, ask)]}."""
    out = {'weekday': [], 'weekend': []}
    for at, eid, bid, ask in rows:
        dt = _ts(at)
        if dt is None:
            continue
        out['weekend' if dt.weekday() >= 5 else 'weekday'].append((at, eid, bid, ask))
    return out
