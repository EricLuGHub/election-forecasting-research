"""Read-only maker reconnaissance with incremental checkpoints, never fill claims.

The supplied snapshot only selects research candidates. Fresh book, tape and
contract reads are archived independently. Tape prices lack aggressor/queue
information; past volume does not establish our achievable fill rate.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time

from .client import Client, ROOT
from .e6data import contract_identity
from .external import event_for_title
from .monitor import atomic_json
from .risk import finite, inventory


def utc():
    return datetime.now(timezone.utc).isoformat()


def select(snapshot, positions, orders, limit=12, allow_held_counterparts=False, min_spread=.02):
    markets = snapshot['markets']
    race_by_eid = {str(e['id']): mapp[0] for m in markets
                   if (mapp := event_for_title(m['title'])) for e in m['exchanges']}
    occupied = set(inventory(positions)) | {str(o['exchangeId']) for o in orders if o['open']}
    occupied_races = {race_by_eid[eid] for eid in occupied if eid in race_by_eid}
    quotes = {str(q['exchangeId']): q for q in snapshot['quotes']}
    candidates = []
    for market in markets:
        mapping = event_for_title(market['title'])
        if not mapping or mapping[0].startswith('CONTROL') or len(market['exchanges']) != 1:
            continue
        eid = str(market['exchanges'][0]['id'])
        ref = snapshot['references'].get('-'.join(mapping))
        if (not ref or eid in occupied or (not allow_held_counterparts and mapping[0] in occupied_races)
                or market['status'] != 'open'):
            continue
        try:
            bid, ask = (finite(quotes[eid][key]) for key in ('bestBid', 'bestAsk'))
            rb, ra = finite(ref['bid']), finite(ref['ask'])
            if (not 0 < bid < ask < 1 or ask-bid < min_spread-1e-9
                    or ref['status'] != 'active' or not 0 < rb <= ra < 1 or ra-rb > .06+1e-9
                    or min(finite(ref['bidSize']), finite(ref['askSize'])) < 20
                    or finite(ref['volume24h']) < 100):
                continue
            candidates.append({'exchangeId': eid, 'market': market, 'reference': ref,
                               'raceCandidate': mapping[0], 'snapshotBid': bid, 'snapshotAsk': ask,
                               'makerEdge': round(max(rb-bid-.005, ask-.005-ra), 6)})
        except (ValueError, KeyError, TypeError):
            continue
    candidates.sort(key=lambda r: (-r['makerEdge'], r['exchangeId']))
    selected, seen = [], set()
    for row in candidates:
        if row['raceCandidate'] not in seen:
            selected.append(row)
            seen.add(row['raceCandidate'])
        if len(selected) == limit:
            break
    return selected


def read_resource(client, path, **params):
    # GET only. A timeout must not discard earlier candidates or trigger any
    # order retry. Limit the additional network retry to one per resource.
    started = utc()
    for attempt in range(2):
        try:
            data = client.get(path, **params)
            return {'requestStartedAt': started, 'receivedAt': utc(), 'data': data}
        except (OSError, RuntimeError, ValueError) as exc:
            if isinstance(exc, OSError) and attempt == 0:
                time.sleep(1)
                continue
            return {'requestStartedAt': started, 'receivedAt': utc(), 'error': str(exc)[:300]}


def tape_stats(pages):
    rows, seen = [], set()
    for page in pages:
        for row in page['data']:
            if row['id'] in seen:
                raise ValueError('Overlapping tape pages')
            seen.add(row['id'])
            rows.append(row)
    shares = sum(finite(row['size']) for row in rows)
    prices = [finite(row['price']) for row in rows if row['price'] is not None]
    return {'trades': len(rows), 'shares': shares,
            'minYesPrice': min(prices) if prices else None,
            'maxYesPrice': max(prices) if prices else None,
            'completePagination': bool(pages) and not pages[-1]['pagination']['hasMore'],
            'fillRateEstimate': None}


def run(snapshot_path, output, limit=12, hours=2, max_pages=3, client=None,
        allow_held_counterparts=False, min_spread=.02):
    client = client or Client()
    snapshot = json.loads(Path(snapshot_path).read_text())
    t = client.get('/tournaments/midterm-elections')
    if str(snapshot['tournament']['id']) != str(t['id']):
        raise ValueError('Wrong snapshot tournament')
    positions = client.get('/tournaments/midterm-elections/portfolio/positions')['positions']
    orders = client.pages('/orders', tournamentId=t['id'], status='open', limit=100)
    end = datetime.now(timezone.utc)
    result = {'startedAt': utc(), 'snapshotAt': snapshot['at'], 'tournamentId': t['id'],
              'from': (end-timedelta(hours=hours)).isoformat(), 'to': end.isoformat(),
              'positions': positions, 'openOrders': orders,
              'candidates': select(snapshot, positions, orders, limit, allow_held_counterparts, min_spread),
              'executionEligible': False, 'limitations': 'Research selection only; no maker fills inferred.'}
    atomic_json(output, result)
    for row in result['candidates']:
        eid, market = row['exchangeId'], row['market']
        print(json.dumps({'phase': 'reading', 'exchangeId': eid, 'title': market['title']}), flush=True)
        row['book'] = read_resource(client, f'/exchanges/{eid}/orderbook', tournamentId=t['id'], depth=50)
        atomic_json(output, result)
        row['node'] = read_resource(client, f"/markets/{market['id']}/nodes")
        row['identity'] = contract_identity(market, row['node']['data']) if 'data' in row['node'] else None
        atomic_json(output, result)
        row['tapePages'], cursor, seen = [], None, set()
        for _ in range(max_pages):
            page = read_resource(client, f'/exchanges/{eid}/trades', tournamentId=t['id'],
                                 limit=200, cursor=cursor, **{'from': result['from'], 'to': result['to']})
            row['tapePages'].append(page)
            atomic_json(output, result)
            if 'error' in page or not page['data']['pagination']['hasMore']:
                break
            cursor = page['data']['pagination']['nextCursor']
            if not cursor or cursor in seen:
                row['tapeError'] = 'Missing or repeated cursor'
                break
            seen.add(cursor)
        row['tapeStats'] = tape_stats([p['data'] for p in row['tapePages'] if 'data' in p])
        row['completedAt'] = utc()
        atomic_json(output, result)
        print(json.dumps({'exchangeId': eid, 'identity': row['identity'], 'tape': row['tapeStats']}), flush=True)
    result['completedAt'] = utc()
    atomic_json(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, default=ROOT/'data/top20/opportunity-snapshot.json')
    parser.add_argument('--output', type=Path, default=ROOT/'data/top20/maker-study.json')
    parser.add_argument('--limit', type=int, default=12)
    parser.add_argument('--hours', type=float, default=2)
    parser.add_argument('--max-pages', type=int, default=3)
    parser.add_argument('--allow-held-counterparts', action='store_true')
    parser.add_argument('--min-spread', type=float, default=.02)
    args = parser.parse_args()
    if (not 1 <= args.limit <= 50 or not 0 < args.hours <= 48 or not 1 <= args.max_pages <= 10
            or not .005 <= args.min_spread <= .1):
        parser.error('Unbounded research request')
    run(args.snapshot, args.output, args.limit, args.hours, args.max_pages,
        allow_held_counterparts=args.allow_held_counterparts, min_spread=args.min_spread)


if __name__ == '__main__':
    main()
