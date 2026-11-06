"""Counterfactual rejection ledger (backlog item 90).

Every refused candidate re-walked under the ORIGINAL entry policy. Verdicts
cover ALL refusals, not just spectacular misses: a gate is over-strict only
if refused value systematically clears the bar later, not because one name
recovered. Basket refusals re-walk depth; directional-short refusals re-check
the tail price (a short refused at 0.16 that now trades 0.30+ was correctly
refused — firing would have lost).
"""
import argparse
import json
from .client import Client

# (name, kind, size, edge_at_refusal, legs/rpc, note)
REFUSALS = [
    ('NM-SEN-r1', 'basket', 1000, 10.00, ('974', '973'), 'refused, retook +30'),
    ('WA-03-r2', 'basket', 1000, 10.50, ('1037', '1036'), 'refused'),
    ('WA-03-r3', 'basket', 1000, 14.40, ('1037', '1036'), 'refused again'),
    ('MN-02-r4', 'basket', 1000, 13.38, ('1026', '1025'), 'refused'),
    ('PA-GOV-r5', 'basket', 1000, 12.96, ('879', '878'), 'refused'),
    ('NJ-SEN-r6', 'basket', 500, 7.50, ('972', '971'), 'refused'),
    ('CA-GOV', 'basket', 250, 2.50, ('851', '850'), 'fired fair by mistake'),
    ('CT-GOV-short', 'short', 500, 0.13, ('854',), 'rejected: fair value'),
    ('AR-SEN-short', 'short', 500, 0.165, ('943',), 'rejected: competitive'),
    ('LA-SEN-short', 'short', 500, 0.16, ('957',), 'rejected: below fair'),
    ('MN-SEN-short', 'short', 500, 0.17, ('1050',), 'rejected: below fair'),
    ('AR-GOV-short', 'short', 500, 0.145, ('846',), 'rejected: fair-cheap'),
]


def walk_buy_no(client, tid, eid, size):
    book = client.get(f'/exchanges/{eid}/orderbook', tournamentId=tid, depth=50)
    need, cost = size, 0.0
    for x in book.get('bids', []):
        take = min(need, float(x['quantity']))
        cost += take * (1.0 - float(x['price']))
        need -= take
        if need <= 0:
            break
    if need > 0:
        return None
    return round(cost, 2)


def tail_bid(client, tid, eid):
    book = client.get(f'/exchanges/{eid}/orderbook', tournamentId=tid, depth=5)
    bids = book.get('bids', [])
    return float(bids[0]['price']) if bids else None


def review(client=None):
    client = client or Client()
    tid = client.get('/tournaments', slug='midterm-elections')['data'][0]['id']
    rows = []
    for name, kind, size, ref_edge, legs, note in REFUSALS:
        try:
            if kind == 'basket':
                costs = [walk_buy_no(client, tid, eid, size) for eid in legs]
                if any(c is None for c in costs):
                    rows.append({'name': name, 'state': 'thin'})
                    continue
                edge = size - sum(costs)
                verdict = 'missed-winner' if edge >= 15.0 else 'correct-refusal'
                rows.append({'name': name, 'ref_edge': ref_edge,
                             'now_edge': round(edge, 2), 'verdict': verdict,
                             'note': note})
            else:
                bid = tail_bid(client, tid, legs[0])
                if bid is None:
                    rows.append({'name': name, 'state': 'thin'})
                    continue
                # A refused short is vindicated when the tail fades (edge gone
                # WITH the price). Revisit only if richness returned.
                verdict = 'revisit' if bid >= ref_edge else 'stands'
                rows.append({'name': name, 'ref_price': ref_edge,
                             'now_bid': bid, 'verdict': verdict, 'note': note})
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            rows.append({'name': name, 'state': 'error',
                         'reason': str(exc)[:120]})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()
    for row in review():
        print(json.dumps(row)[:220], flush=True)


if __name__ == '__main__':
    main()
