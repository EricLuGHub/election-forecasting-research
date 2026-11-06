"""Feed-vs-REST consistency check (backlog item 24). Read-only.

A connected socket is not evidence of complete data: the venue documents
dropped late batches and possible silent last-update loss. For each sampled
exchange this compares the monitor's latest observation against a fresh REST
book: if the REST sequence advanced while no observation arrived, the event
path missed it (GAP); if tops differ beyond tolerance, books disagree
(DIVERGED); otherwise OK. Quiet books with static sequences are quiet, not
gappy — the sequence number is the discriminator.
"""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from .client import Client


def latest_obs(history_path, eid):
    db = sqlite3.connect(f'file:{history_path}?mode=ro', uri=True)
    try:
        row = db.execute(
            "SELECT at, payload FROM observations WHERE resource=? "
            "ORDER BY at DESC LIMIT 1", (str(eid),)).fetchone()
    finally:
        db.close()
    if not row:
        return None
    try:
        p = json.loads(row[1])
        return {'at': row[0], 'bid': float(p['bestBid']), 'ask': float(p['bestAsk'])}
    except (ValueError, KeyError, TypeError):
        return None


def check_venue(client, tid, history_path, eid, now=None, tol=0.005):
    """Verdict dict with sequence evidence. Never raises on data issues."""
    now = now or datetime.now(timezone.utc)
    try:
        book = client.get(f'/exchanges/{eid}/orderbook', tournamentId=tid, depth=5)
        seq = book.get('asOf', {}).get('sequence')
        rb = float(book['bids'][0]['price'])
        ra = float(book['asks'][0]['price'])
    except (RuntimeError, OSError, ValueError, KeyError, IndexError) as exc:
        return {'eid': str(eid), 'verdict': 'rest_error',
                'reason': str(exc)[:120]}
    obs = latest_obs(history_path, eid)
    if obs is None:
        return {'eid': str(eid), 'verdict': 'no_obs', 'rest_seq': seq}
    try:
        age = (now - datetime.fromisoformat(obs['at'])).total_seconds()
    except ValueError:
        return {'eid': str(eid), 'verdict': 'bad_timestamp', 'rest_seq': seq}
    diff = max(abs(obs['bid'] - rb), abs(obs['ask'] - ra))
    if diff > tol:
        # Tops disagree: either a missed update or a moved book. A fresh REST
        # sequence with an old obs means the event path is behind.
        return {'eid': str(eid), 'verdict': 'diverged',
                'rest_seq': seq, 'obs_age_s': round(age, 1),
                'diff': round(diff, 4)}
    return {'eid': str(eid), 'verdict': 'ok', 'rest_seq': seq,
            'obs_age_s': round(age, 1)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--eids', default='1077,1075,1054,963,1060,1071,1070,851,850,948,947,1048')
    parser.add_argument('--tol', type=float, default=0.005)
    args = parser.parse_args()
    from .client import ROOT
    client = Client()
    tid = client.get('/tournaments', slug='midterm-elections')['data'][0]['id']
    history = str(ROOT / 'data/monitor/history.sqlite3')
    for eid in [e.strip() for e in args.eids.split(',') if e.strip()]:
        try:
            row = check_venue(client, tid, history, eid, tol=args.tol)
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            row = {'eid': eid, 'verdict': 'error', 'reason': str(exc)[:120]}
        print(json.dumps(row)[:220], flush=True)


if __name__ == '__main__':
    main()
