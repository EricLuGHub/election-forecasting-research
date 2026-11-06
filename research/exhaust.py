"""Exhaustion fade: enter only after move + refill + reversal (item 68). Pure.

Unconditional fading (E3 style) bets every gap. Momentum (c201) bets
continuation and loses 74%. The exhaustion policy bets reversion ONLY
when three conditions coincide on the same exchange:
1. MOVE: mid shifts >= MOVE_MIN over LOOKBACK (a real displacement);
2. REFILL: spread narrows back to <= pre-move spread (makers returned —
   spread is the depth proxy available in quote data; depth-gated entry
   is a stated follow-up, not smuggled in);
3. REVERSAL: a tick back toward the pre-move mid with no reference/news
   input (quote-data only — news-filtering needs the item-70 calendar).
Entry: maker at the extreme + tick-back (optimistic touch assumption,
labeled). Win = full reversion to pre-move mid within horizon; loss =
extension >= move_min beyond the trigger extreme; else flat. Triggers
are horizon-embargoed (non-overlapping; item-105). Missed trades =
formed moves never triggering all three (throughput cost, counted).
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


def to_books(rows):
    """[(at, eid, bid, ask)] -> {eid: [(ts, bid, ask, mid, spread)]}."""
    out = {}
    for at, eid, bid, ask in rows:
        t = _ts(at)
        try:
            b, a = float(bid), float(ask)
        except (TypeError, ValueError):
            continue
        if t is None or a < b:
            continue
        out.setdefault(str(eid), []).append((t, b, a, (b + a) / 2, a - b))
    for v in out.values():
        v.sort()
    return out


def triggers(series, move_min=MOVE_MIN, lookback_h=LOOKBACK_H,
             horizon_h=HORIZON_H):
    """[(t_trig, pre_mid, direction)] exhaustion entries. direction is the
    FADE direction (+1 = buy the dip after a down move). Non-overlapping
    by horizon embargo (item-105: overlapping triggers double-count)."""
    lb = lookback_h * 3600
    hz = horizon_h * 3600
    out = []
    embargo = 0.0
    for i, (t, b, a, m, s) in enumerate(series):
        if t < embargo:
            continue
        base = None
        for j in range(i, -1, -1):
            if series[j][0] <= t - lb:
                base = series[j]
                break
        if base is None:
            continue
        bt, bb, ba, bm, bs = base
        if abs(m - bm) < move_min:
            continue
        if s > bs:
            continue  # spread not refilled
        if (m - bm) > 0 and m >= max(x[3] for x in series[max(0, i - 3):i + 1]):
            continue  # still making highs — no reversal yet
        if (m - bm) < 0 and m <= min(x[3] for x in series[max(0, i - 3):i + 1]):
            continue  # still making lows
        out.append((t, bm, 1 if m < bm else -1))
        embargo = t + hz
    return out


def simulate(series, horizon_h=HORIZON_H, move_min=MOVE_MIN, **kw):
    """Per triggered trade from the TRIGGER price (maker at the extreme +
    tick-back, optimistic touch assumption, labeled). Win = full reversion
    to pre-move mid within horizon; loss = extension >= move_min beyond
    the trigger extreme; else flat. Returns dict."""
    hz = horizon_h * 3600
    trig = triggers(series, horizon_h=horizon_h,
                    **{k: v for k, v in kw.items()
                       if k in ('move_min', 'lookback_h')})
    res = {'n_trig': 0, 'win': 0, 'loss': 0, 'flat': 0,
           'formed': 0, 'missed': 0}
    res['n_trig'] = len(trig)
    for t, pre, direction in trig:
        entry = next((m for tt, b, a, m, s in series if tt >= t), None)
        if entry is None:
            continue
        post = [(tt, m) for tt, b, a, m, s in series if tt > t]
        end = next((m for tt, m in post if tt >= t + hz), None)
        if end is None and post:
            end = post[-1][1]
        if end is None:
            continue
        disp = (pre - entry) * direction  # remaining displacement to capture
        if disp < 0.005:
            res['flat'] += 1  # entry already at/through pre: nothing left
        elif (end - pre) * direction >= 0:
            res['win'] += 1  # full reversion to pre-move mid
        elif (end - entry) * direction <= -move_min:
            res['loss'] += 1  # extended >= move against from entry
        else:
            res['flat'] += 1
    lb = kw.get('lookback_h', LOOKBACK_H) * 3600
    mm = kw.get('move_min', MOVE_MIN)
    for i, (t, b, a, m, s) in enumerate(series):
        for j in range(i, -1, -1):
            if series[j][0] <= t - lb:
                if abs(m - series[j][3]) >= mm:
                    res['formed'] += 1
                break
    res['missed'] = res['formed'] - len(trig)
    return res
