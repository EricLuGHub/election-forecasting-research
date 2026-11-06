"""Entry×exit engine attribution (backlog item 8).

Every FIFO close pairs entry lots with an exit fill. Engines come from order
idempotency prefixes (Q3/Q4 quoter, ROT/NH/SHELF/ROTM baskets, E7/trial
theirs, null/other E1-other). A reducer's profitable sale of another engine's
entry is SHARED credit, never single-engine evidence. Uses fillnorm for
direction (item 1); amounts reconcile to realized.py totals by construction.
"""
import argparse
import json
from .client import Client
from .execution import Executor
from .fillnorm import normalize

PREFIX_ENGINE = (
    (('Q3-', 'Q4-'), 'quoter-mine'),
    (('ROT-', 'ROTM-', 'NH-', 'SHELF-', 'ROT2-', 'ROT3-', 'ROT4-',
      'ROT5-', 'ROT6-'), 'baskets-mine'),
    (('E7-', 'TRIAL-', 'trial'), 'trial-theirs'),
)


def engine_of(order):
    key = str((order or {}).get('idempotencyKey') or '')
    return engine_of_key(key)


def engine_of_key(key):
    for prefixes, name in PREFIX_ENGINE:
        if key.startswith(prefixes):
            return name
    return 'E1-other'


def journal_order_engines(journal):
    """orderId -> engine via Executor journal responses (multi-leg component
    orders carry venue IDs, not our idempotency keys)."""
    out = {}
    for key, row in (journal or {}).items():
        eng = engine_of_key(str(key))
        if eng == 'E1-other':
            continue
        resp = (row or {}).get('response') or {}
        results = resp.get('results', [])
        if isinstance(results, list):
            for leg in results:
                oid = ((leg or {}).get('data') or {}).get('orderId')
                if oid is not None:
                    out[str(oid)] = eng
        elif resp.get('orderId') is not None:
            out[str(resp.get('orderId'))] = eng
    return out


def attribute_engines(fills, orders, journal=None):
    """(matrix, closes). matrix[(entry_engine, exit_engine)] = [pnl, qty]."""
    omap = {}
    for order in orders or []:
        try:
            omap[str(order.get('id'))] = order
        except (AttributeError, TypeError):
            continue
    jmap = journal_order_engines(journal)
    lots = {}
    matrix = {}
    closes = 0
    unattributed = 0
    for fill in sorted(fills, key=lambda r: r.get('filledAt', '')):
        oid = str(fill.get('orderId', ''))
        order = omap.get(oid)
        if order is None:
            unattributed += 1
            continue
        eng = engine_of(order)
        if eng == 'E1-other' and oid in jmap:
            eng = jmap[oid]
        norm = normalize(fill, order)
        if norm is None:
            unattributed += 1
            continue
        eid = str(fill.get('exchangeId'))
        qty = norm['econ_qty']
        book = lots.setdefault(eid, [])
        remaining = qty
        i = 0
        while remaining != 0 and i < len(book):
            lqty, lpx, leng = book[i]
            if lqty == 0 or (lqty > 0) == (remaining > 0):
                i += 1
                continue
            m = min(abs(remaining), abs(lqty))
            pnl = (norm['exec_yes'] - lpx) * m if lqty > 0 else \
                (lpx - norm['exec_yes']) * m
            key = (leng, eng)
            cell = matrix.setdefault(key, [0.0, 0.0])
            cell[0] += pnl
            cell[1] += m
            closes += 1
            take = m if remaining > 0 else -m
            book[i][0] += take
            remaining -= take
            if book[i][0] == 0:
                i += 1
        if remaining != 0:
            book.append([remaining, norm['exec_yes'], eng])
    return ({'%s>%s' % k: [round(v[0], 2), v[1]] for k, v in matrix.items()},
            closes, unattributed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()
    client = Client()
    base = '/tournaments/midterm-elections/portfolio'
    fills = client.pages(base + '/fills', limit=200)
    try:
        orders = client.pages('/orders', limit=100, status='all')
    except (RuntimeError, OSError, ValueError, KeyError):
        orders = []
    matrix, closes, unattributed = attribute_engines(fills, orders,
                                                       Executor(slug='midterm-elections').journal())
    print(json.dumps({'matrix': matrix, 'closes': closes,
                      'unattributed': unattributed}, indent=2))


if __name__ == '__main__':
    main()
