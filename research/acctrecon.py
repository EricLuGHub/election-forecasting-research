"""End-to-end accounting identity (backlog item 2).

Pulls every money-relevant endpoint and checks the identities that must hold:

  total_value == cash + holdings_value                      (A)
  total_pnl   == realized_fifo + unrealized                 (B)
  sum(transactions cash legs) == cash - starting_balance    (C, best effort)

where realized_fifo comes from the order-joined FIFO (realized.py) and
unrealized from the positions endpoint. Anything that does not reconcile is
surfaced as an explicit residual with its magnitude — never zeroed.

Known limits: fills print in canonicalized units (see fillnorm); short-sale
collateral moves through portfolio/collateral, not fills; settlement/refund
events appear only in portfolio/settlements+transactions. Residuals name the
unexplained part instead of hiding it.
"""
import argparse
import json
from .client import Client


def check_identity(snap):
    """Pure identity check. Returns {checks: {...}, residuals: {...}}."""
    out = {'checks': {}, 'residuals': {}}
    tv = snap.get('total_value')
    cash = snap.get('cash')
    hold = snap.get('holdings_value')
    if None not in (tv, cash, hold):
        out['checks']['A_cash_plus_holdings'] = round(tv - (cash + hold), 2)
    tp = snap.get('total_pnl')
    rf = snap.get('realized_fifo')
    un = snap.get('unrealized')
    if None not in (tp, rf, un):
        out['checks']['B_realized_plus_unrealized'] = round(tp - (rf + un), 2)
    tx = snap.get('tx_cash_sum')
    start = snap.get('starting_balance', 100000.0)
    if None not in (tx, cash):
        out['checks']['C_transactions_vs_cash'] = round((cash - start) - tx, 2)
    for key, val in out['checks'].items():
        if val != 0:
            out['residuals'][key] = val
    return out


def fetch(client=None, slug='midterm-elections'):
    client = client or Client()
    base = f'/tournaments/{slug}/portfolio'
    pnl = client.get(base + '/pnl', period='all')
    try:
        cash = float(client.get('/account').get('balance'))
    except (RuntimeError, OSError, ValueError, KeyError, TypeError):
        cash = None
    positions = client.get(base + '/positions')
    tx = client.pages(base + '/transactions', limit=100)
    settlements = client.get(base + '/settlements')
    try:
        collateral = client.get('/portfolio/collateral', tournamentId=(
            client.get('/tournaments', slug=slug)['data'][0]['id']))
    except (RuntimeError, OSError, ValueError, KeyError):
        collateral = None
    holds = positions.get('positions', positions)
    holdings_value = sum(float(p.get('marketValue', 0) or 0) for p in holds) \
        if isinstance(holds, list) else None
    unrealized = sum(float(p.get('unrealizedPnl', 0) or 0) for p in holds) \
        if isinstance(holds, list) else None
    tx_cash = 0.0
    for row in tx if isinstance(tx, list) else []:
        for key in ('amount', 'cashDelta', 'cash'):
            try:
                tx_cash += float(row.get(key, 0) or 0)
                break
            except (TypeError, ValueError):
                continue
    from .realized import attribute
    fills = client.pages(base + '/fills', limit=200)
    try:
        orders = client.pages('/orders', limit=100, status='all')
    except (RuntimeError, OSError, ValueError, KeyError):
        orders = []
    realized_fifo = attribute(fills, orders).get('realized_total')
    from .windows import resolve_alltime_pnl
    total_value = pnl.get('totalAccountValue')
    total_pnl, pnl_basis = resolve_alltime_pnl(
        pnl.get('periodPnl'), total_value)
    return {'total_value': total_value, 'cash': cash,
            'holdings_value': holdings_value if holdings_value is not None else pnl.get('totalHoldingsValue'),
            'total_pnl': total_pnl, 'pnl_basis': pnl_basis,
            'realized_fifo': realized_fifo, 'unrealized': unrealized,
            'tx_cash_sum': tx_cash, 'starting_balance': 100000.0,
            'tx_count': len(tx) if isinstance(tx, list) else 0,
            'settlements': settlements, 'collateral': collateral,
            'position_count': len(holds) if isinstance(holds, list) else 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()
    snap = fetch()
    result = check_identity(snap)
    print(json.dumps({'snapshot_meta': {k: snap.get(k) for k in
                                        ('tx_count', 'position_count')},
                      'checks': result['checks'],
                      'residuals': result['residuals'],
                      'settlements': str(snap.get('settlements'))[:300],
                      'collateral': str(snap.get('collateral'))[:500]}, indent=2))


if __name__ == '__main__':
    main()
