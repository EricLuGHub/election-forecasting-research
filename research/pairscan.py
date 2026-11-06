"""Pair-edge sweep (2x/day cron): reseeds, new listings, regime breaks.

For every same-race party group: best BUY basket (sum of YES asks vs floor)
and best SELL basket (sum of YES bids vs floor) at top-book. Anything crossing
CROSS (default 0.005/unit) logs ALERT. Top-book only: a hit means "go look with
depth", never "fire". Read-only.
"""
import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from .client import ROOT, Client

CROSS_DEFAULT = 0.005


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cross', type=float, default=CROSS_DEFAULT)
    args = parser.parse_args()
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
    races = defaultdict(dict)
    for market in markets:
        match = re.fullmatch(r'Will the (.+) win the (.+)\?', market['title'] or '')
        if not match:
            continue
        party, race = match.groups()
        for exchange in market.get('exchanges', []):
            q = books.get(str(exchange['id']))
            if q and q.get('bestBid') is not None and q.get('bestAsk') is not None:
                races[race][party] = (float(q['bestBid']), float(q['bestAsk']))
    alerts = []
    worst_buy = (None, 0.0)
    worst_sell = (None, 0.0)
    for race, legs in races.items():
        if len(legs) < 2:
            continue
        floor = len(legs) - 1
        buy_cost = sum(1.0 - b for b, _ in legs.values())  # NO basket pays YES-bid complements
        sell_collect = sum(b for b, _ in legs.values())   # sell YES legs into bids
        buy_edge = floor - buy_cost                        # floor n-1 NOs pay
        sell_edge = sell_collect - 1.0                     # worst case one listed winner pays 1.0
        if buy_cost - floor < worst_buy[1]:
            worst_buy = (race, buy_cost - floor)
        if floor - sell_collect < worst_sell[1]:
            worst_sell = (race, floor - sell_collect)
        if buy_edge >= args.cross:
            alerts.append({'race': race, 'side': 'BUY', 'edge': round(buy_edge, 4)})
        if sell_edge >= args.cross:
            alerts.append({'race': race, 'side': 'SELL', 'edge': round(sell_edge, 4)})
    row = {'at': datetime.now(timezone.utc).isoformat(), 'races': len(races),
           'best_buy_overpay': round(worst_buy[1], 4), 'best_buy_race': worst_buy[0],
           'best_sell_undercollect': round(worst_sell[1], 4), 'best_sell_race': worst_sell[0],
           'alerts': alerts}
    with (ROOT / 'data/pairscan.log').open('a') as handle:
        handle.write(json.dumps(row) + '\n')
    print(json.dumps(row, indent=2)[:1500])


if __name__ == '__main__':
    main()
