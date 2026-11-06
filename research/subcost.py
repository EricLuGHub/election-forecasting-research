"""Sub-cost exits blocked by leg-level floors (backlog item 39). Pure.

E1 sells one leg at a time and each sale must clear
    floor_i = max(cost_ceiling_i + MIN_GAIN, held_mark_i)   (e1run.proposal)
plus never reduce the race settlement floor (risk.floor_safe_quantity).
A WHOLE-BASKET exit can be jointly profitable (L > paired cost) while one
leg's bid sits below its individual floor — E1 then cannot fire it
leg-by-leg, and the value sits blocked. This module quantifies exactly
that gap per basket. It proposes; E1's owner disposes (their engine,
their guards — this changes no guard).

Verdicts (predeclared):
- 'fires-today': no leg blocked (E1 can already do it; nothing blocked).
- 'blocked-profitable': joint edge > 0 but >=1 leg blocked. Blocked value
  = joint edge. This is the item-39 case.
- 'hold-candidate': joint edge <= 0. Freed cash and joint loss are
  reported, but NO risk verdict is manufactured — whether a loss-taking
  exit is "risk-improving" needs the owner's book view (cash needs,
  correlated exposure). Quantified, not judged.
- Refusal (None) on missing bids/costs — a leg without a bid is not
  "blocked", it is unmeasurable.
"""
from .risk import cost_ceiling, held_mark

MIN_GAIN = 0.01


def leg_floor(position):
    """(floor, highest_cost, mark). Raises ValueError on bad position."""
    from .risk import finite
    hi = cost_ceiling(position)
    mark = held_mark(position)
    return max(hi + MIN_GAIN, mark), hi, mark


def analyze_basket(name, legs, joint_proceeds, paired_cost):
    """legs: [(eid, position, bid)] with bid = executable NO-bid per share
    or None. Returns (verdict, detail)."""
    if joint_proceeds is None or paired_cost is None:
        return None, {'basket': name, 'refused': 'no joint valuation'}
    detail_legs = []
    for eid, position, bid in legs:
        try:
            floor, hi, mark = leg_floor(position)
        except (ValueError, KeyError, TypeError):
            return None, {'basket': name, 'refused': 'bad position %s' % eid}
        if bid is None:
            return None, {'basket': name, 'refused': 'no bid leg %s' % eid}
        try:
            bid = float(bid)
        except (TypeError, ValueError):
            return None, {'basket': name, 'refused': 'bad bid leg %s' % eid}
        blocked = bid < floor - 1e-9
        detail_legs.append({'eid': str(eid), 'floor': round(floor, 4),
                            'highest_cost': round(hi, 4),
                            'mark': round(mark, 4),
                            'bid': round(bid, 4), 'blocked': blocked})
    blocked = [l for l in detail_legs if l['blocked']]
    edge = round(float(joint_proceeds) - float(paired_cost), 2)
    detail = {'basket': name, 'legs': detail_legs,
              'joint_edge': edge,
              'proceeds': round(float(joint_proceeds), 2),
              'paired_cost': round(float(paired_cost), 2)}
    if not blocked:
        detail['verdict'] = 'fires-today'
        detail['why'] = 'no leg blocked; E1 can fire leg-by-leg today'
        return 'fires-today', detail
    if edge > 0:
        detail['verdict'] = 'blocked-profitable'
        detail['blocked_value'] = edge
        detail['why'] = ('joint +%.2f blocked by %d leg floor(s)'
                         % (edge, len(blocked)))
        return 'blocked-profitable', detail
    detail['verdict'] = 'hold-candidate'
    detail['why'] = ('joint %.2f; loss-taking exit needs owner book view'
                     % edge)
    return 'hold-candidate', detail
