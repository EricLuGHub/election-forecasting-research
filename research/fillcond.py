"""Conditional returns given a fill (backlog item 86). Pure.

Unconditional pretty quotes say nothing about what fills cost. For each
fill (eid, ts, side, price, qty): mid moves in symmetric windows BEFORE
(fill-chasing: was the book running toward us?) and AFTER (adverse
selection: did it keep running past us?) vs PLACEBO timestamps (same
eids, random times — the null distribution). Inventory duration: fill to
first offsetting fill on the same eid (crude pairing, stated); unpaired
fills report duration None (held, not zero).

All moves in ticks of the fill's favorability sign where signed, raw
otherwise — no sign gymnastics hidden.
"""
PRE_H = 0.5
POST_H = 0.5


def _ts(at):
    from datetime import datetime
    if isinstance(at, (int, float)):
        return float(at)
    try:
        return datetime.fromisoformat(str(at).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def window_move(series, t, hours, direction=1):
    """Mid change over the window ending (direction<0) or starting
    (direction>0) at t. None without cover on both ends."""
    h = abs(float(hours)) * 3600
    if direction > 0:
        m0 = next((m for ts, m in series if ts >= t), None)
        m1 = next((m for ts, m in series if ts >= t + h), None)
    else:
        cands = [m for ts, m in series if ts <= t - h]
        m0 = cands[-1] if cands else None
        m1 = next((m for ts, m in series if ts >= t), None)
    if m0 is None or m1 is None:
        return None
    return m1 - m0


def fill_moves(series_by_eid, fills, pre_h=PRE_H, post_h=POST_H):
    """fills: [(eid, ts, side)]. Returns {eid: [(pre, post)]} in raw mid
    units (sign with side at analysis, not here). Skips coverless fills."""
    out = {}
    for eid, ts, side in fills:
        t = _ts(ts)
        series = series_by_eid.get(str(eid), [])
        if t is None or not series:
            continue
        pre = window_move(series, t, pre_h, direction=-1)
        post = window_move(series, t, post_h, direction=1)
        if pre is None or post is None:
            continue
        out.setdefault(str(eid), []).append((pre, post, side))
    return out


def summarize(moves):
    """Distribution stats + placebo-ready moments. moves: [(pre, post)]."""
    import math
    pres = [p for p, _, _ in moves]
    posts = [q for _, q, _ in moves]
    if not moves:
        return None
    def stats(xs):
        n = len(xs)
        mean = sum(xs) / n
        var = sum((x - mean) ** 2 for x in xs) / n
        srt = sorted(xs)
        return {'n': n, 'mean': round(mean, 4),
                'sd': round(math.sqrt(var), 4),
                'p10': round(srt[max(0, n // 10 - 1)], 4),
                'p50': round(srt[n // 2], 4),
                'p90': round(srt[min(n - 1, 9 * n // 10)], 4)}
    return {'pre': stats(pres), 'post': stats(posts)}
