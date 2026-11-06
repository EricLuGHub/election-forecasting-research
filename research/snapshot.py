"""Save timestamped tournament data, contract definitions and executable books."""
import argparse
from datetime import datetime, timezone
import json
from .client import Client, ROOT, save_json


def now():
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--slug', default='midterm-elections')
    parser.add_argument('--max-markets', type=int, default=0, help='0 collects every market')
    args = parser.parse_args()
    c = Client()
    directory = ROOT / 'data/snapshots' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    t = c.get(f'/tournaments/{args.slug}')
    tid = t['id']
    markets = c.pages('/markets', limit=100, tournamentId=tid)
    snapshot = {'startedAt': now(), 'tournament': t, 'markets': markets,
                'nodes': {}, 'books': {}, 'errors': []}
    save_json(directory / 'snapshot.json', snapshot)
    for name, path, params in [
        ('relationships', '/relationships', {'limit': 200, 'tournamentId': tid}),
        ('constraints', '/relationships/constraints', {'tournamentId': tid}),
        ('positions', f'/tournaments/{args.slug}/portfolio/positions', {}),
        ('orders', '/orders', {'tournamentId': tid, 'status': 'open', 'limit': 100}),
    ]:
        try:
            snapshot[name] = c.pages(path, **params) if name in ('relationships', 'orders') else c.get(path, **params)
        except RuntimeError as exc:
            snapshot['errors'].append({'resource': name, 'error': str(exc)})
    selected = markets[:args.max_markets] if args.max_markets else markets
    for index, market in enumerate(selected, 1):
        try:
            snapshot['nodes'][market['id']] = c.get(f'/markets/{market["id"]}/nodes', tournamentId=tid)
            for exchange in market['exchanges']:
                start = now()
                book = c.get(f'/exchanges/{exchange["id"]}/orderbook', tournamentId=tid, depth=200)
                book['requestStartedAt'] = start
                book['receivedAt'] = now()
                snapshot['books'][exchange['id']] = book
        except RuntimeError as exc:
            snapshot['errors'].append({'marketId': market['id'], 'error': str(exc)})
        if index % 20 == 0:
            save_json(directory / 'snapshot.json', snapshot)
            print(f'Collected {index}/{len(selected)} markets', flush=True)
    snapshot['completedAt'] = now()
    save_json(directory / 'snapshot.json', snapshot)
    save_json(ROOT / 'data/latest.json', {'path': str(directory / 'snapshot.json')})
    print(json.dumps({'snapshot': str(directory / 'snapshot.json'), 'markets': len(markets),
                      'books': len(snapshot['books']), 'errors': snapshot['errors']}, indent=2))


if __name__ == '__main__':
    main()
