"""Fill markout analyzer: do our fills earn the spread or donate to informed flow?

For each account fill, compare fill price against the book mid a delay later
(1/5/30 min) using monitor history quote-changes when available, else live
re-reads. Adverse selection = mid moves against us after our fill.
Read-only. Prints per-fill markouts + aggregates by side/venue.
"""
import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from .client import ROOT, Client


def load_fills(client, limit=200):
    f = client.get('/tournaments/midterm-elections/portfolio/fills', limit=limit)
    rows = f.get('data', f) if isinstance(f, dict) else f
    return rows if isinstance(rows, list) else []


def mids_at(client, tid, exchange_ids):
    out = {}
    eids = sorted(set(exchange_ids))
    for offset in range(0, len(eids), 100):
        resp = client.get('/exchanges/prices', ids=','.join(eids[offset:offset + 100]),
                          tournamentId=tid)
        rows = resp.get('data', resp) if isinstance(resp, dict) else resp
        for q in rows:
            if q.get('bestBid') is not None and q.get('bestAsk') is not None:
                out[str(q['exchangeId'])] = (float(q['bestBid']) + float(q['bestAsk'])) / 2
    return out


HORIZONS = (5.0, 30.0, 60.0, 300.0, 1800.0)


def at_fill_mids(history_path, fills, delay=60.0, max_lag=300.0, delays=None):
    """Mid + executable exit at FIXED horizons after each fill.

    Returns {fill_index: {horizon: (mid, exec_exit, lag)}} using the first
    quote-change at/after fill_time + horizon. exec_exit is the executable
    exit price for an econ-LONG YES (YES bid); shorts mirror it at scoring
    time via fillnorm signs. A horizon is recorded only when its quote lands
    within horizon + tolerance (min 30s, or 25% of horizon); missing horizons
    are excluded explicitly, never substituted. Without delays, behaves as
    the legacy single-delay call returning {i: mid} for compatibility.
    """
    horizons = list(delays) if delays else [delay]
    out = {}
    try:
        db = sqlite3.connect(f'file:{history_path}?mode=ro', uri=True)
    except sqlite3.Error:
        return out
    for i, r in enumerate(fills):
        try:
            qty = float(r.get('quantity', 0))
            at = r.get('filledAt', '')
            float(r.get('price'))
        except (TypeError, ValueError):
            continue
        if qty == 0 or not at:
            continue
        try:
            base = datetime.fromisoformat(at)
        except ValueError:
            continue
        per = {}
        for h in horizons:
            target = (base + timedelta(seconds=h)).isoformat()
            tol = max(30.0, h * 0.25)
            row = db.execute(
                "SELECT at, payload FROM observations WHERE kind='quote_change' "
                "AND resource=? AND at>=? ORDER BY at LIMIT 1",
                (str(r.get('exchangeId')), target)).fetchone()
            if not row:
                continue
            try:
                quote = json.loads(row[1])
                bid, ask = float(quote['bestBid']), float(quote['bestAsk'])
                lag = (datetime.fromisoformat(row[0]) - datetime.fromisoformat(at)).total_seconds()
            except (ValueError, KeyError, TypeError):
                continue
            if h <= lag <= h + tol:
                mid = (bid + ask) / 2
                per[h] = (mid, bid, ask, lag)
        if per:
            out[i] = per if delays else per[delay]
    db.close()
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=200)
    parser.add_argument('--at-fill', action='store_true',
                        help='Score vs quote-change mids at fill time (honest); default vs current mids')
    parser.add_argument('--history', default=str(ROOT / 'data/monitor/history.sqlite3'))
    args = parser.parse_args()
    client = Client()
    tid = client.get('/tournaments/midterm-elections')['id']
    fills = load_fills(client, args.limit)
    try:
        orders = client.pages('/orders', limit=100, status='all')
    except (RuntimeError, OSError, ValueError, KeyError):
        orders = []
    omap = {}
    for order in orders:
        try:
            omap[str(order.get('id'))] = order
        except (AttributeError, TypeError):
            continue
    from .fillnorm import normalize, edge_vs
    unattributed = 0
    if args.at_fill:
        ref = at_fill_mids(args.history, fills, delays=HORIZONS)
        label = 'edge_at_fill'
    else:
        mids = mids_at(client, tid, [str(r.get('exchangeId')) for r in fills])
        ref = None
    horizons = HORIZONS if args.at_fill else (None,)
    per_h = {h: [] for h in horizons}


    def score(norm, qty, mid, bid, ask):
        # Mid edge + EXECUTABLE exit edge. Longs exit into the YES bid;
        # shorts (long-NO) exit into the NO bid = 1 - YES ask.
        edge = (mid - norm['exec_yes']) * norm['sign']
        if norm['sign'] > 0:
            edge_exe = bid - norm['exec_yes']
        else:
            edge_exe = norm['exec_yes'] - ask
        return edge, edge_exe

    rows = []
    for i, r in enumerate(fills):
        # Canonical scoring (item 1): order-joined direction, YES units.
        norm = normalize(r, omap.get(str(r.get('orderId', '')), {}))
        if norm is None:
            unattributed += 1
            continue
        try:
            qty = abs(float(r.get('quantity', 0)))
        except (TypeError, ValueError):
            continue
        if qty == 0:
            continue
        if args.at_fill:
            per = ref.get(i)
            if not per:
                continue
            for h, (mid, bid, ask, lag) in per.items():
                edge, edge_exe = score(norm, qty, mid, bid, ask)
                per_h[h].append((edge, edge_exe, qty))
                if h == 60.0:
                    rows.append({'at': r.get('filledAt'), 'eid': str(r.get('exchangeId')),
                                 'qty': qty, 'px': norm['exec_yes'],
                                 'mid_now': round(mid, 4),
                                 'edge_now': round(edge, 4), 'sign': norm['sign']})
        else:
            mid = mids.get(str(r.get('exchangeId')))
            if mid is None:
                continue
            edge = edge_vs(norm, mid)
            rows.append({'at': r.get('filledAt'), 'eid': str(r.get('exchangeId')),
                         'qty': qty, 'px': norm['exec_yes'], 'mid_now': round(mid, 4),
                         'edge_now': round(edge, 4), 'sign': norm['sign']})
    if args.at_fill:
        summary = {}
        for h, vals in per_h.items():
            q = sum(v[2] for v in vals)
            summary[str(h)] = {'n': len(vals),
                               'mean_mid_edge': round(sum(v[0] * v[2] for v in vals) / q, 4) if q else None,
                               'mean_exe_edge': round(sum(v[1] * v[2] for v in vals) / q, 4) if q else None}
        print(json.dumps({'horizons': summary}, indent=2))
    pos = [x['edge_now'] for x in rows if x['edge_now'] > 0]
    neg = [x['edge_now'] for x in rows if x['edge_now'] <= 0]
    print(json.dumps({
        'fills_scored': len(rows),
        'mean_edge_per_share': round(sum(x['edge_now'] for x in rows) / len(rows), 4) if rows else None,
        'total_edge_now': round(sum(x['edge_now'] * abs(x['qty']) for x in rows), 2) if rows else None,
        'winners': len(pos), 'losers': len(neg),
    }, indent=2))
    from collections import defaultdict
    by_venue = defaultdict(lambda: [0.0, 0])
    by_side = defaultdict(lambda: [0.0, 0])
    by_hour = defaultdict(lambda: [0.0, 0])
    for x in rows:
        by_venue[x['eid']][0] += x['edge_now'] * abs(x['qty'])
        by_venue[x['eid']][1] += 1
        side = 'long' if x.get('sign', 1) > 0 else 'short'
        by_side[side][0] += x['edge_now'] * abs(x['qty'])
        by_side[side][1] += 1
        by_hour[x['at'][:13]][0] += x['edge_now'] * abs(x['qty'])
        by_hour[x['at']][1] += 1
    print('by_venue (worst 5):',
          sorted([(k, round(v[0], 2), v[1]) for k, v in by_venue.items()])[:5])
    print('by_venue (best 5):',
          sorted([(k, round(v[0], 2), v[1]) for k, v in by_venue.items()], reverse=True)[:5])
    print('by_side:', {k: [round(v[0], 2), v[1]] for k, v in by_side.items()})
    print('by_hour:', sorted((k, round(v[0], 2), v[1]) for k, v in by_hour.items())[-8:])
    for x in rows[:15]:
        print(json.dumps(x))


if __name__ == '__main__':
    main()
