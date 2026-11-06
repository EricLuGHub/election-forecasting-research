"""Executable capacity audit: how much size can books take before 1c slippage?

For a set of exchanges, sums displayed depth within one tick of touch on each
side. Answers whether flat PnL is caution (we quote too small) or capacity (the
book has nothing to take). Read-only.
"""
import argparse
import json
from .client import Client


def slippage(levels, take, side='buy'):
    """Paper fill model: walk YES asks (buy) or bids (sell). Returns (avg_px, levels_used)."""
    levels = sorted(((float(x['price']), float(x['quantity'])) for x in levels),
                    reverse=(side == 'sell'))
    filled, cost, used = 0.0, 0.0, 0
    for price, qty in levels:
        take_now = min(qty, take - filled)
        filled += take_now
        cost += take_now * price
        used += 1
        if filled >= take:
            break
    if filled < take:
        return None
    return {'avg_price': round(cost / filled, 4), 'levels_used': used}


def capacity(book, ticks=1, tick=0.005):
    out = {}
    for side, key in (('bid', 'bids'), ('ask', 'asks')):
        levels = book.get(key, [])
        if not levels:
            out[side] = {'shares': 0, 'notional': 0.0}
            continue
        touch = float(levels[0]['price'])
        bound = touch - ticks * tick if side == 'bid' else touch + ticks * tick
        shares, notional = 0.0, 0.0
        for level in levels:
            price = float(level['price'])
            if (side == 'bid' and price < bound - 1e-9) or (side == 'ask' and price > bound + 1e-9):
                break
            qty = float(level['quantity'])
            shares += qty
            notional += qty * price
        out[side] = {'shares': shares, 'notional': round(notional, 2)}
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exchange-ids', default='')
    parser.add_argument('--depth', type=int, default=50)
    args = parser.parse_args()
    client = Client()
    tid = client.get('/tournaments/midterm-elections')['id']
    eids = [e.strip() for e in args.exchange_ids.split(',') if e.strip()]
    if not eids:
        markets = client.pages('/markets', limit=100, tournamentId=tid)
        eids = [str(e['id']) for m in markets if m.get('status') == 'open'
                for e in m.get('exchanges', [])][:40]
    total = {'bid_shares': 0.0, 'ask_shares': 0.0, 'bid_notional': 0.0, 'ask_notional': 0.0}
    thin = []
    for eid in eids:
        try:
            book = client.get(f'/exchanges/{eid}/orderbook', tournamentId=tid, depth=args.depth)
        except (RuntimeError, OSError, ValueError, KeyError):
            continue
        cap = capacity(book)
        total['bid_shares'] += cap['bid']['shares']
        total['ask_shares'] += cap['ask']['shares']
        total['bid_notional'] += cap['bid']['notional']
        total['ask_notional'] += cap['ask']['notional']
        if cap['bid']['shares'] + cap['ask']['shares'] < 100:
            thin.append(eid)
    print(json.dumps({'exchanges': len(eids), 'total': total, 'thin_exchanges': thin,
                      'thin_count': len(thin)}, indent=2))


if __name__ == '__main__':
    main()
