"""Four separate quantities (backlog item 3). One screen, four numbers that must
never be mixed: realized net P&L (FIFO, item 1), marked account P&L (venue
marks), executable liquidation P&L (depth exits on top positions, marks for
the tail), verified remaining settlement floor (paired baskets × $1, shorts'
tails stated separately). A structural edge and a leaderboard mark belong in
different fields; neither is automatically cash profit.
"""
import argparse
import json
from .client import Client
from .realized import attribute
from .exit import depth_proceeds

TOP_N = 20


def liquidation(positions, books):
    """(exit_proceeds, marks_rest, cost_basis) over positions.

    Top-N by abs market value exit at depth (YES bids for longs, NO bids =
    1-YES asks for short-YES/long-NO inventory); the tail stays at marks,
    labeled as such. Proceeds are CASH receivable now; compare against cost
    basis for the liquidation P&L. Never mix the two.
    """
    ranked = sorted(positions, key=lambda p: abs(float(p.get('marketValue', 0) or 0)),
                    reverse=True)
    proceeds, marked, basis = 0.0, 0.0, 0.0
    for pos in ranked:
        basis += float(pos.get('costBasis', 0) or 0)
    for pos in ranked[:TOP_N]:
        eid = str(pos.get('exchangeId'))
        book = books.get(eid)
        qty = float(pos.get('quantity', 0) or 0)
        if book is None or qty == 0:
            marked += float(pos.get('marketValue', 0) or 0)
            continue
        side = 'yes' if qty > 0 else 'no'
        got = depth_proceeds(book, side, abs(qty))
        if got is None:
            marked += float(pos.get('marketValue', 0) or 0)
            continue
        proceeds += got
    for pos in ranked[TOP_N:]:
        marked += float(pos.get('marketValue', 0) or 0)
    return round(proceeds, 2), round(marked, 2), round(basis, 2)


def four_quantities(client=None, slug='midterm-elections'):
    client = client or Client()
    base = f'/tournaments/{slug}/portfolio'
    pnl = client.get(base + '/pnl', period='all')
    positions = client.get(base + '/positions').get('positions', [])
    fills = client.pages(base + '/fills', limit=200)
    try:
        orders = client.pages('/orders', limit=100, status='all')
    except (RuntimeError, OSError, ValueError, KeyError):
        orders = []
    realized = attribute(fills, orders).get('realized_total')
    tid = client.get('/tournaments', slug=slug)['data'][0]['id']
    top = sorted(positions, key=lambda p: abs(float(p.get('marketValue', 0) or 0)),
                 reverse=True)[:TOP_N]
    books = {}
    for pos in top:
        eid = str(pos.get('exchangeId'))
        try:
            books[eid] = client.get(f'/exchanges/{eid}/orderbook',
                                    tournamentId=tid, depth=10)
        except (RuntimeError, OSError, ValueError, KeyError):
            continue
    liq, liq_marks, basis = liquidation(positions, books)
    from .reconcile import reconcile
    from .convexit import race_pair
    from .client import ROOT
    try:
        ledger = json.loads((ROOT / 'data/e2_taken.json').read_text())
        floor = sum(r.get('paired', 0) * 1.0 for r in
                    reconcile(ledger, positions,
                              lambda race: race_pair(client, tid, race))
                    if r.get('status') in ('intact', 'partial'))
    except (RuntimeError, OSError, ValueError, KeyError):
        floor = None
    return {'realized_fifo': realized,
            'marked_pnl': round(float(pnl.get('totalAccountValue', 0)) - 100000.0, 2),
            'liquidation_proceeds_top': liq,
            'liquidation_marks_rest': liq_marks,
            'positions_cost_basis': basis,
            'settlement_floor_paired': floor}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()
    print(json.dumps(four_quantities(), indent=2))


if __name__ == '__main__':
    main()
