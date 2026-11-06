"""Canonical fill normalizer (backlog item 1).

Every consumer (realized P&L, markouts, gates, dashboards) must agree on what
a fill MEANS. Fill side/quantity signs are ambiguous after venue
canonicalization (a YES sale can print as a NO fill with flipped signs); only
the originating order disambiguates direction. Prices convert to YES units.

normalize(fill, order) -> dict with:
  econ_qty   signed YES-equivalent quantity (order direction × |fill qty|)
  exec_yes   execution price in YES units (fill price, NO mirrored)
  order_yes  order/limit price in YES units (NO mirrored)
  premium    limit-economics cash now: -econ_qty × order_yes
             (+collect on shorts, -pay on longs). Estimate from limits;
             actual settlement/payouts reconcile separately (backlog item 2).
  edge(mid)  signed per-share edge vs a YES mid: (mid - exec_yes) × sign.

Audit example: YES sale 5 @0.13 printing as NO fill (qty -5 @0.87), YES mid
0.12 → edge +0.01 (raw-sign math reports +0.75; see test).
Unmatched fills (no order) return None — counted, never forced.
"""
from .risk import direction


def normalize(fill, order):
    try:
        order_dir = direction(order)
    except (ValueError, KeyError, TypeError):
        return None
    try:
        raw_qty = abs(float(fill.get('quantity', 0)))
        fpx = float(fill.get('price'))
        opx = float(order.get('priceLimit', order.get('price')))
    except (TypeError, ValueError, KeyError):
        return None
    if raw_qty == 0:
        return None
    if str(fill.get('side')) == 'no':
        fpx = 1.0 - fpx
    if str(order.get('side')) == 'no':
        opx = 1.0 - opx
    if not (0 < fpx < 1) or not (0 < opx < 1):
        return None
    econ_qty = order_dir * raw_qty
    return {'econ_qty': econ_qty,
            'exec_yes': fpx,
            'order_yes': opx,
            'premium': -econ_qty * opx,
            'sign': 1 if order_dir > 0 else -1}


def edge_vs(norm, mid):
    """Signed per-share edge vs a YES mid. None when unscorable."""
    try:
        mid = float(mid)
    except (TypeError, ValueError):
        return None
    if norm is None:
        return None
    return (mid - norm['exec_yes']) * norm['sign']
