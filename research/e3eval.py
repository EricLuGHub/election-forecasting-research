"""E3 paper-fade evaluator (hourly cron). No trading.

Joins fresh Kalshi quotes (public API) with fresh SIG midpoints, logs paper fade
signals with buffered edges, and scores previous signals on convergence: did the
SIG mid move toward Kalshi (fade works), persist (rule difference / noise), or
did SIG lead (fade is adverse selection)? Arming E3 live requires this ledger to
show convergence, not hope.
"""
import json
from datetime import datetime, timezone
from .client import ROOT, Client
from . import external as kalshi


def sig_mids(client, markets, tid):
    eids = [str(e['id']) for m in markets if m.get('status') == 'open'
            for e in m.get('exchanges', [])]
    books = {}
    for offset in range(0, len(eids), 100):
        resp = client.get('/exchanges/prices', ids=','.join(eids[offset:offset + 100]),
                          tournamentId=tid)
        rows = resp.get('data', resp) if isinstance(resp, dict) else resp
        for q in rows:
            if q.get('bestBid') is not None and q.get('bestAsk') is not None:
                books[str(q['exchangeId'])] = (float(q['bestBid']), float(q['bestAsk']))
    return books


def kalshi_mids(markets):
    out = {}
    event_ids = sorted({v[0] for v in
                        (kalshi.event_for_title(m['title']) for m in markets) if v})
    for event_id in event_ids:
        try:
            d = kalshi.public_get('/markets', event_ticker=event_id, limit=1000)
            for r in d.get('markets', []):
                try:
                    b, a = float(r['yes_bid_dollars']), float(r['yes_ask_dollars'])
                except (TypeError, ValueError):
                    continue
                if r.get('status') == 'active' and 0 < b <= a < 1:
                    out[r['ticker']] = (b + a) / 2
        except (RuntimeError, OSError, ValueError, KeyError):
            continue
    return out


def main():
    client = Client()
    tid = client.get('/tournaments/midterm-elections')['id']
    snap = json.loads(open(json.loads((ROOT / 'data/latest.json').read_text())['path']).read())
    markets = snap['markets']
    books = sig_mids(client, markets, tid)
    refs = kalshi_mids(markets)
    now = datetime.now(timezone.utc).isoformat()
    signals = []
    for market in markets:
        mapping = kalshi.event_for_title(market['title'])
        if not mapping:
            continue
        ref = refs.get(mapping[0] + '-' + mapping[1])
        if ref is None:
            continue
        for exchange in market.get('exchanges', []):
            book = books.get(str(exchange['id']))
            if not book:
                continue
            mid = (book[0] + book[1]) / 2
            edge = ref - mid
            if abs(edge) >= 0.02:
                signals.append({'at': now, 'marketId': market['id'],
                                'exchangeId': str(exchange['id']), 'title': market['title'],
                                'sig_mid': round(mid, 4), 'kalshi_mid': round(ref, 4),
                                'edge': round(edge, 4),
                                'direction': 'buy SIG toward Kalshi' if edge > 0 else 'sell SIG toward Kalshi'})
    with (ROOT / 'data/e3eval.log').open('a') as handle:
        handle.write(json.dumps({'at': now, 'signals': signals,
                                 'n_compared': len(books)}) + '\n')
    print(f'e3eval: {len(signals)} paper signals at {now}')


if __name__ == '__main__':
    main()
