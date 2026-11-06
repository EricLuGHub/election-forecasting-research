"""Position-aware basket reconciliation (backlog item 12).

A ledger entry is an acquisition event, not proof the basket still exists:
netting, reductions, and prior lots change what remains. reconcile() joins
each basket's legs (strict instrument identity from convexit) to current
position lots and reports remaining paired quantity plus ambiguity flags.

paired_remaining = min(NO-lot sum on R leg, NO-lot sum on D leg), with:
- net_mismatch: position net quantity != lot-sum (netting evidence; the
  venue nets same-exchange opposite holdings — remaining exposure differs
  from lot arithmetic, flagged not silently resolved).
- depleted: paired_remaining <= 0 → basket cannot exit as a pair.
- partial: 0 < paired < size → only part of the basket remains.
Statuses are inventory facts for E8/convexit to consume, never orders.
"""
import json
from .client import ROOT, Client


def leg_inventory(positions, eid):
    """(no_lot_sum, net_qty) for one exchange. Both reported; mismatch flagged."""
    no_sum, net = 0.0, None
    for pos in positions:
        if str(pos.get('exchangeId')) != str(eid):
            continue
        try:
            net = float(pos.get('quantity', 0)) if net is None else net
        except (TypeError, ValueError):
            pass
        for lot in pos.get('lots', []) or []:
            try:
                q = float(lot.get('quantity', 0))
            except (TypeError, ValueError):
                continue
            if str(lot.get('side')) == 'NO' and q > 0:
                no_sum += q
    return no_sum, net


def reconcile(ledger, positions, resolve):
    """resolve(race) -> (eid_r, eid_d) | None. Returns per-basket rows."""
    from .convexit import load_baskets
    rows = []
    for name, race, size, cost in load_baskets_from(ledger):
        pair = resolve(race)
        if not pair:
            rows.append({'basket': name, 'status': 'unresolved'})
            continue
        r_sum, r_net = leg_inventory(positions, pair[0])
        d_sum, d_net = leg_inventory(positions, pair[1])
        paired = min(r_sum, d_sum)
        if paired <= 0:
            status = 'depleted'
        elif paired < size:
            status = 'partial'
        else:
            status = 'intact'
        mismatch = ((r_net is not None and abs(r_net) != r_sum) or
                    (d_net is not None and abs(d_net) != d_sum))
        rows.append({'basket': name, 'status': status, 'size': size,
                     'paired': paired, 'legs': {pair[0]: [r_sum, r_net],
                                                pair[1]: [d_sum, d_net]},
                     'net_mismatch': bool(mismatch)})
    return rows


def load_baskets_from(ledger):
    out = []
    for name, info in ledger.items():
        race = str(info.get('race', ''))
        cost = info.get('cost')
        if cost is None or 'floor' not in info:
            continue
        size = None
        for token in race.split():
            if token.startswith('x') and token[1:].isdigit():
                size = int(token[1:])
        if size:
            out.append((name, race, size, float(cost)))
    return out


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()
    client = Client()
    tid = client.get('/tournaments', slug='midterm-elections')['data'][0]['id']
    ledger = json.loads((ROOT / 'data/e2_taken.json').read_text())
    positions = client.get('/tournaments/midterm-elections/portfolio/positions')
    positions = positions.get('positions', positions)
    from .convexit import race_pair
    rows = reconcile(ledger, positions if isinstance(positions, list) else [],
                     lambda race: race_pair(client, tid, race))
    for row in rows:
        print(json.dumps(row)[:260], flush=True)


if __name__ == '__main__':
    main()
