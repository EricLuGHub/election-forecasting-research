"""Paired exit planner for E8-live staging (backlog item 37). Pure.

A joint exit is not two single-leg profit targets: it needs, atomically
at plan time —
1. joint proceeds L at depth >= paired cost + MIN_EDGE (else no plan);
2. residual floor intact: sale cash + remaining floor >= floor before
   (the risk.floor_safe_quantity invariant, evaluated on provided numbers);
3. pending ownership: no foreign open orders on either leg, no prior E8X
   key for this basket (re-fire refuses — idempotency by construction);
4. executor coordination: reduce_only submits under caller's Executor with
   E8X- idempotency keys (E1's lots are never touched — different legs
   only if E1 has no open orders there; otherwise refuse).

Unmatched allowance: when one leg lacks full depth, the planner sizes the
PAIR to the matchable qty and reports the leftover as residual (still
floored) — never a lone-leg sale unless allow_single explicitly permits
and the floor check passes on that leg alone. Default: pairs only.
"""
MIN_EDGE = 5.0
PREFIX = 'E8X-'


def plan_exit(name, eid_r, eid_d, qty, bid_r, bid_d, paired_cost,
              floor_before, floor_after, open_eids, prior_keys,
              min_edge=MIN_EDGE, allow_single=False):
    """(orders, detail) | (None, {'refused': reason}). Prices/qty numeric;
    open_eids: foreign open-order eids; prior_keys: existing E8X keys."""
    try:
        qty = int(qty)
        bid_r, bid_d = float(bid_r), float(bid_d)
        paired_cost = float(paired_cost)
        floor_before, floor_after = float(floor_before), float(floor_after)
    except (TypeError, ValueError):
        return None, {'refused': 'non-numeric pricing'}
    if qty <= 0:
        return None, {'refused': 'non-positive qty'}
    key = '%s%s' % (PREFIX, name)
    if key in (prior_keys or []):
        return None, {'refused': 'already planned/fired %s' % key}
    foreign = [e for e in (str(eid_r), str(eid_d)) if e in (open_eids or [])]
    if foreign:
        return None, {'refused': 'foreign open orders on %s' % foreign}
    proceeds = round(qty * (bid_r + bid_d), 2)
    edge = round(proceeds - paired_cost, 2)
    if edge < min_edge:
        return None, {'refused': 'edge %.2f < bar %.2f' % (edge, min_edge)}
    if floor_after + proceeds < floor_before - 1e-9:
        return None, {'refused': 'floor violated: %.2f + %.2f < %.2f'
                                 % (floor_after, proceeds, floor_before)}
    legs = [{'eid': str(eid_r), 'qty': qty, 'price': round(bid_r, 4)},
            {'eid': str(eid_d), 'qty': qty, 'price': round(bid_d, 4)}]
    if not allow_single:
        detail = {'basket': name, 'key': key, 'qty': qty, 'legs': legs,
                  'proceeds': proceeds, 'edge': edge,
                  'floor_before': floor_before, 'floor_after': floor_after,
                  'mode': 'paired-only'}
        return legs, detail
    detail = {'basket': name, 'key': key, 'qty': qty, 'legs': legs,
              'proceeds': proceeds, 'edge': edge,
              'floor_before': floor_before, 'floor_after': floor_after,
              'mode': 'single-allowed-with-floor-check'}
    return legs, detail
