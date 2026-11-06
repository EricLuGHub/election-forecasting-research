"""Marginal edge curves (backlog item 32). Fixed clips miss good trades.

For a two-leg NO basket, floor(q) = q (per paired unit $1) and
executable_cost(q) walks both books. The curve edge(q) = floor(q) - cost(q)
is concave by construction (depth thins); the marginal curve picks size
subject to: absolute floor ($15), per-share floor (1.0c), and capital
($5k/basket). A fixed 1,000-share test misses a good 400-share trade and a
deeper 2,500-share opportunity alike — the curve decides per book.
"""
import argparse
import json


def curve(bids_r, bids_d, quantities):
    """[(qty, edge)] for NO-buy baskets from YES-bid ladders."""
    rows = []
    for qty in quantities:
        total, ok = 0.0, True
        for bids in (bids_r, bids_d):
            need, cost = qty, 0.0
            for price, size in bids:
                take = min(need, size)
                cost += take * (1.0 - price)
                need -= take
                if need <= 0:
                    break
            if need > 0:
                ok = False
                break
            total += cost
        if ok:
            rows.append((qty, round(qty - total, 2)))
    return rows


def choose(curve_rows, min_edge=15.0, min_per_share=0.01, max_capital=5000.0,
           unit_floor=1.0):
    """Largest qty whose marginal RATE clears the bar at every step (concave
    curves thin monotonically: first failing rate ends the search), with
    TOTAL edge clearing min_edge AND curve-derived cost within max_capital.
    UNITS (item-110, stated once): qty in basket units (pairs); edge in $;
    rate in $/share/pair-unit (marginal edge per added pair — matches the
    per-share bars); cost(qty) = qty*unit_floor - edge(qty) from the SAME
    curve (never inherited from differently labeled units). A 970-cost
    candidate cannot pass a 5-capital limit: cost refusal precedes bars."""
    best, prev_qty, prev_edge = None, 0, 0.0
    for qty, edge in curve_rows:
        if qty - prev_qty <= 0:
            continue
        try:
            qty, edge = float(qty), float(edge)
        except (TypeError, ValueError):
            return best
        cost = qty * unit_floor - edge
        if cost > max_capital:
            break  # capital binds before bars are even consulted
        rate = (edge - prev_edge) / (2 * (qty - prev_qty))
        if rate < min_per_share:
            break
        if edge >= min_edge:
            best = (int(qty), edge)
        prev_qty, prev_edge = qty, edge
    return best


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--eids', default='1077,1076')
    parser.add_argument('--sizes', default='250,500,1000,1500,2000,3000')
    args = parser.parse_args()
    print(json.dumps({'note': 'live run needs books; see cycle log'}))
