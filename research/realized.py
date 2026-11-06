"""Realized PnL attribution (FIFO per exchange/side). Marks lie; closes don't.

Pairs closing trades against opening lots in time order. A buy closes a
negative (short) lot and vice versa. Output: realized per exchange, total,
plus unmatched (still-open) inventory. Pure function for testability; a thin
live wrapper reads the account fills endpoint.
"""
import argparse
import json
from .client import Client


def attribute(fills, orders=None):
    lots = {}   # eid -> list of [signed_yes_qty, price] open lots
    realized = {}
    unattributed = 0
    order_dir = {}
    order_rec = {}
    for order in (orders or []):
        try:
            from .risk import direction as _direction
            order_dir[str(order.get('id'))] = _direction(order)
            order_rec[str(order.get('id'))] = order
        except (ValueError, KeyError):
            continue

    def key(fill):
        return str(fill.get('exchangeId'))

    def fill_yes(fill):
        """(signed YES qty, YES price) or (0, None) when unattributable.

        Delegates to the canonical normalizer (backlog item 1): fill
        side/qty signs are AMBIGUOUS by themselves; only the originating
        order record disambiguates. Unmatched fills are counted, never forced.
        """
        from .fillnorm import normalize
        oid = str(fill.get('orderId', ''))
        if oid not in order_rec:
            return 0.0, None
        norm = normalize(fill, order_rec[oid])
        if norm is None:
            return 0.0, None
        return norm['econ_qty'], norm['exec_yes']

    for fill in sorted(fills, key=lambda r: r.get('filledAt', '')):
        qty, px = fill_yes(fill)
        if qty == 0 or px is None:
            unattributed += 1
            continue
        book = lots.setdefault(key(fill), [])
        remaining = qty
        i = 0
        while remaining != 0 and i < len(book):
            lot_qty, lot_px = book[i]
            if lot_qty == 0 or (lot_qty > 0) == (remaining > 0):
                i += 1
                continue
            m = min(abs(remaining), abs(lot_qty))
            if lot_qty > 0:
                pnl = (px - lot_px) * m      # long closed by a sell
            else:
                pnl = (lot_px - px) * m      # short closed by a buy
            realized[key(fill)] = realized.get(key(fill), 0.0) + pnl
            take = m if remaining > 0 else -m
            book[i][0] += take
            remaining -= take
            if book[i][0] == 0:
                i += 1
        if remaining != 0:
            book.append([remaining, px])
    open_inv = {k: [list(lot) for lot in v if lot[0] != 0] for k, v in lots.items()}
    return {'realized': {k: round(v, 2) for k, v in realized.items()},
            'realized_total': round(sum(realized.values()), 2),
            'open_lots': len([l for v in open_inv.values() for l in v]),
            'unattributed_fills': unattributed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=200)
    args = parser.parse_args()
    client = Client()
    rows = client.pages('/tournaments/midterm-elections/portfolio/fills', limit=200)
    try:
        orders = client.pages('/orders', limit=100, status='all')
    except (RuntimeError, OSError, ValueError, KeyError):
        orders = []
    print(json.dumps(attribute(rows, orders), indent=2)[:3000])


if __name__ == '__main__':
    main()
