"""E3 paper loop: log SIG midpoints for Kalshi-mapped legs every run.

No trading. Builds the time series that validates (or kills) the reference-fade
idea: do SIG-Kalshi gaps converge, persist (rule differences), or does SIG lead?
Kalshi side refreshes via the existing research.external flow; this logger covers
the cheap SIG side. Cron every 10 minutes.
"""
import json
from datetime import datetime, timezone
from .client import ROOT, Client
from .external import event_for_title


def main():
    client = Client()
    tid = client.get('/tournaments/midterm-elections')['id']
    markets = client.pages('/markets', limit=100, tournamentId=tid)
    eids = [str(e['id']) for m in markets if m.get('status') == 'open'
            for e in m.get('exchanges', [])]
    books = {}
    for offset in range(0, len(eids), 100):
        resp = client.get('/exchanges/prices', ids=','.join(eids[offset:offset + 100]),
                          tournamentId=tid)
        rows = resp.get('data', resp) if isinstance(resp, dict) else resp
        for q in rows:
            books[str(q['exchangeId'])] = q
    now = datetime.now(timezone.utc).isoformat()
    lines = 0
    with (ROOT / 'data/e3paper.log').open('a') as handle:
        for market in markets:
            mapping = event_for_title(market['title'])
            if not mapping:
                continue
            for exchange in market.get('exchanges', []):
                q = books.get(str(exchange['id']))
                if not q or q.get('bestBid') is None or q.get('bestAsk') is None:
                    continue
                handle.write(json.dumps({
                    'at': now, 'marketId': market['id'],
                    'exchangeId': str(exchange['id']), 'title': market['title'],
                    'kalshi_event': mapping[0],
                    'sig_bid': q['bestBid'], 'sig_ask': q['bestAsk'],
                    'sig_mid': round((float(q['bestBid']) + float(q['bestAsk'])) / 2, 4),
                }) + '\n')
                lines += 1
    print(f'e3paper: {lines} legs logged at {now}')


if __name__ == '__main__':
    main()
