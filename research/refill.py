"""Basket refill and depletion at the next clip (backlog item 35). Pure.

Scaling depends on REPLENISHED opportunity, not recounting one snapshot.
After an executed acquisition, re-walk the entry-side books (YES-bid
ladders → NO-buy cost via marginal.curve) and compare the next clip
against the entry clip:

- REFILLED: another full-size clip clears the $15/total + 1c/share bars.
- THIN: positive edge survives only below bar/size (smaller clip or
  thinner rate — quantified, not rounded up).
- DEPLETED: no positive edge at any probed qty (book paid us and emptied,
  or the market moved).

edge_retention = best current edge / entry edge (None when entry edge
<= 0 — retention of a non-positive base is meaningless; refused, not 0).

One re-scan is a LEVEL, not a rate: "how long replenishment takes" needs
a series. This module scores the level; cadence comes from repeated runs.
"""
from .marginal import curve, choose

QTYS = (250, 500, 1000, 1500, 2000, 3000)


def score(name, bids_r, bids_d, entry_size, entry_edge,
          quantities=QTYS):
    """(verdict, detail). Refuses (None, reason) on bad inputs."""
    try:
        entry_size = int(entry_size)
        entry_edge = float(entry_edge)
    except (TypeError, ValueError):
        return None, {'basket': name, 'refused': 'bad entry clip'}
    if entry_size <= 0:
        return None, {'basket': name, 'refused': 'bad entry clip'}
    try:
        rows = curve(bids_r, bids_d, [q for q in quantities if q > 0])
    except (TypeError, ValueError):
        return None, {'basket': name, 'refused': 'bad ladders'}
    if not rows:
        return 'depleted', {'basket': name, 'verdict': 'depleted',
                            'curve': [], 'best': None,
                            'retention': None,
                            'why': 'no fillable qty at any probe'}
    best = max(rows, key=lambda t: t[1])
    pick = choose(rows)
    retention = (round(best[1] / entry_edge, 2)
                 if entry_edge > 0 else None)
    detail = {'basket': name, 'curve': rows,
              'best': {'qty': best[0], 'edge': best[1]},
              'retention': retention}
    if pick is not None and pick[0] >= entry_size:
        detail.update(verdict='refilled',
                      why=('another x%d clip clears bars (edge %.2f)'
                           % (pick[0], pick[1])))
        return 'refilled', detail
    if best[1] > 0:
        detail.update(verdict='thin',
                      why=('best x%d edge %.2f below bar/size'
                           % (best[0], best[1])))
        return 'thin', detail
    detail.update(verdict='depleted',
                  why='no positive edge at any probe')
    return 'depleted', detail
