"""Momentum vs reversion where naive fading failed (backlog item 67). Pure.

E3 faded unconditional gaps and lost. The open question is CONDITIONAL:
after a formed move (mid shifts >= MOVE_MIN over LOOKBACK), does the next
HORIZON continue or revert? Method: non-overlapping formed-move events per
exchange, sign of the following horizon move, continuation rate + mean
follow-through. The fade baseline (always bet reversion) wins exactly
(1 - continuation) — reported, not re-run.

Honesty guards: flat books yield no events (not zero continuation);
single-exchange n is reported beside every rate; formed moves on
seed-ladder flicker (c191) are suspect — depth-change filter is a stated
follow-up, not smuggled in.
"""
MOVE_MIN = 0.02
LOOKBACK_H = 1.0
HORIZON_H = 1.0


def _ts(at):
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(at).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def to_mids(rows):
    """[(at, eid, bid, ask)] -> {eid: [(ts, mid)]} sorted. Skips bad rows."""
    out = {}
    for at, eid, bid, ask in rows:
        t = _ts(at)
        try:
            mid = (float(bid) + float(ask)) / 2
        except (TypeError, ValueError):
            continue
        if t is None:
            continue
        out.setdefault(str(eid), []).append((t, mid))
    for v in out.values():
        v.sort()
    return out


def formed_events(series, move_min=MOVE_MIN, lookback_h=LOOKBACK_H,
                  horizon_h=HORIZON_H):
    """Non-overlapping (t_form, direction) with |move| >= bar over lookback.
    direction: +1 (up) / -1 (down)."""
    lb, hz = lookback_h * 3600, horizon_h * 3600
    events = []
    i, embargo = 0, 0.0
    n = len(series)
    while i < n:
        t, m = series[i]
        if t < embargo:
            i += 1
            continue
        base = None
        for j in range(i, -1, -1):
            if series[j][0] <= t - lb:
                base = series[j][1]
                break
        if base is not None and abs(m - base) >= move_min:
            events.append((t, 1 if m > base else -1))
            embargo = t + hz
        i += 1
    return events


def score_event(series, t_form, direction, horizon_h=HORIZON_H):
    """Follow-through sign over horizon; None when no cover (censored)."""
    hz = horizon_h * 3600
    m0 = next((m for t, m in series if t >= t_form), None)
    m1 = next((m for t, m in series if t >= t_form + hz), None)
    if m0 is None or m1 is None:
        return None
    diff = m1 - m0
    if diff == 0:
        return 0
    return 1 if (diff > 0) == (direction > 0) else -1


def summarize(mids, **kw):
    """{eid: {n_events, n_scored, wins, losses, flats, missing,
    continuation_rate, fade_win_rate}} + totals. Win/loss/flat/missing
    separated (item-105: flats are NOT fade wins). Horizon forwarded to
    score_event (was silently defaulted)."""
    horizon_h = kw.get('horizon_h', HORIZON_H)
    total = {'n_events': 0, 'n_scored': 0, 'continued': 0, 'wins': 0,
             'losses': 0, 'flats': 0, 'missing': 0}
    per = {}
    for eid, series in mids.items():
        ev = formed_events(series, **kw)
        followed = [score_event(series, t, d, horizon_h) for t, d in ev]
        scored = [f for f in followed if f is not None]
        cont = sum(1 for f in scored if f == 1)
        wins = sum(1 for f in scored if f == -1)
        flats = sum(1 for f in scored if f == 0)
        per[eid] = {'n_events': len(ev), 'n_scored': len(scored),
                    'wins': wins, 'losses': cont, 'flats': flats,
                    'missing': len(ev) - len(scored),
                    'continuation_rate': (round(cont / len(scored), 3)
                                          if scored else None),
                    'fade_win_rate': (round(wins / len(scored), 3)
                                      if scored else None)}
        total['n_events'] += len(ev)
        total['n_scored'] += len(scored)
        total['continued'] += cont
        total['wins'] += wins
        total['losses'] += cont
        total['flats'] += flats
        total['missing'] += len(ev) - len(scored)
    if total['n_scored']:
        total['continuation_rate'] = round(total['continued'] / total['n_scored'], 3)
        # fade wins = strict reversions ONLY (item-105: flats are not wins)
        total['fade_win_rate'] = round(total['wins'] / total['n_scored'], 3)
        total['fade_baseline_wr'] = total['fade_win_rate']
    else:
        total['continuation_rate'] = None
        total['fade_win_rate'] = None
        total['fade_baseline_wr'] = None
    return {'per_eid': per, 'total': total}
