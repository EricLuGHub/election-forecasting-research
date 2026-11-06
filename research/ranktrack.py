"""Same-period leaderboard tracker (backlog item 10). No anecdotes.

Snapshots top-N + our rank for calendar periods (1d/7d/30d/all), appends to
data/ranktrack.log, and measures persistence: top-20 ID overlap across
snapshots, leader rank drift, cutoff velocity. Aggregate P&L/trade counts
never establish per-trade edge; persistence across days and settlement does
(or doesn't) establish repeatability. Participant IDs as published; no
inference about strategies from numbers alone.
"""
import argparse
import json
from datetime import datetime, timezone
from .client import ROOT, Client

LOG = ROOT / 'data/ranktrack.log'
SELF_HINTS = ('happy-pebble-3751', 'ericlu3141592@gmail.com')


def snapshot(client, slug='midterm-elections', period='all', limit=50):
    resp = client.get(f'/tournaments/{slug}/leaderboard', period=period,
                      limit=limit)
    if isinstance(resp, dict):
        for key in ('leaderboard', 'data', 'rows', 'entries'):
            rows = resp.get(key)
            if isinstance(rows, list):
                return rows
        return []
    return resp if isinstance(resp, list) else []


def summarize(rows, period):
    """(top_ids, cutoff, self_row). Cutoff = lowest top-20 PnL when present."""
    top_ids = [str(r.get('profileId') or r.get('id') or r.get('participantId')
                   or r.get('username'))
               for r in rows[:20]]
    pnls = []
    for r in rows[:20]:
        try:
            pnls.append(float(r.get('pnl', r.get('totalPnl', 0)) or 0))
        except (TypeError, ValueError):
            continue
    cutoff = min(pnls) if pnls else None
    self_row = None
    for r in rows:
        blob = json.dumps(r)
        if any(h in blob for h in SELF_HINTS):
            self_row = {k: r.get(k) for k in ('rank', 'username', 'pnl', 'totalPnl', 'trades')}
            break
    return {'at': datetime.now(timezone.utc).isoformat(), 'period': period,
            'top_ids': top_ids, 'cutoff_top20': cutoff, 'self': self_row,
            'board_size': len(rows)}


def overlap(a, b):
    """Jaccard-ish: share of A's top-20 still in B's top-20."""
    sa, sb = set(a or []), set(b or [])
    if not sa:
        return None
    return round(len(sa & sb) / len(sa), 3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--periods', default='all,1d')
    parser.add_argument('--limit', type=int, default=50)
    args = parser.parse_args()
    client = Client()
    with LOG.open('a') as handle:
        for period in [p.strip() for p in args.periods.split(',') if p.strip()]:
            try:
                rows = snapshot(client, period=period, limit=args.limit)
            except (RuntimeError, OSError, ValueError, KeyError) as exc:
                print(json.dumps({'period': period, 'error': str(exc)[:150]}))
                continue
            summary = summarize(rows, period)
            handle.write(json.dumps(summary) + '\n')
            print(json.dumps(summary)[:400], flush=True)


if __name__ == '__main__':
    main()
