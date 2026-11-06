"""Partial-fill decision tree (backlog item 29). Pure logic + dry drill.

After one basket leg fills, exactly one of three bounded actions applies:

  COMPLETE  resting remainder still fills within the original cost limit
            (plus a small completion tolerance) before the timeout.
  UNWIND    exit filled legs now; bounded loss accepted; chosen when the
            residual can't complete in time or would breach orphan exposure.
  HOLD      residual exposure is within allocation AND timeout not exceeded;
            keep working the remainder, re-evaluate next check.

Max orphan exposure caps the directional risk of a half-filled basket;
timeout bounds how long a residual may live. Placement atomicity never
implies simultaneous execution — this tree is the missing half.
All quantities in shares; prices in YES-normalized units; NO legs convert
at 1 - YES book prices (see fillnorm).
"""
import math

COMPLETION_TOL = 0.005  # extra per-share slippage tolerated to complete


def walk_buy_no(bids, size):
    """(avg_no_price, filled) buying NO into YES bids. filled False if thin."""
    need, cost = size, 0.0
    for price, qty in bids:
        take = min(need, qty)
        cost += take * (1.0 - price)
        need -= take
        if need <= 0:
            break
    if need > 0:
        return None, False
    return cost / size, True


def walk_sell_no(asks, size):
    """(avg_no_proceeds, filled) selling NO into NO bids (= 1 - YES asks)."""
    need, proceeds = size, 0.0
    for price, qty in asks:
        take = min(need, qty)
        proceeds += take * (1.0 - price)
        need -= take
        if need <= 0:
            break
    if need > 0:
        return None, False
    return proceeds / size, True


def decide(filled, residual, books, limits, size,
           max_orphan=500.0, elapsed_min=0.0, timeout_min=15.0,
           tol=COMPLETION_TOL):
    """filled: {eid: shares_done}. residual: {eid: shares_open}.
    books: {eid: {'bids': [(px, qty)], 'asks': [(px, qty)]}} (YES books).
    limits: {eid: original NO limit price}. size: intended per-leg shares.
    Returns (action, detail dict)."""
    if not residual:
        return 'COMPLETE', {'reason': 'nothing open'}
    open_eids = [e for e, q in residual.items() if q > 0]
    if not open_eids:
        return 'COMPLETE', {'reason': 'nothing open'}
    # One-sided risk: a filled leg with an unfilled counterpart is directional.
    one_sided = len([e for e in set(list(filled) + open_eids)
                     if filled.get(e, 0) > 0]) == 1 and len(open_eids) >= 1
    if elapsed_min >= timeout_min:
        return 'UNWIND', {'reason': 'timeout', 'one_sided': one_sided}
    # Completion check: remainder fills within limit + tol?
    worst = 0.0
    for eid in open_eids:
        book = books.get(eid, {})
        avg, ok = walk_buy_no(book.get('bids', []), residual[eid])
        if not ok:
            return 'UNWIND', {'reason': 'remainder_thin', 'leg': eid}
        worst = max(worst, avg - limits.get(eid, avg))
    if worst <= tol:
        return 'COMPLETE', {'reason': 'within_limit', 'worst_slip': round(worst, 4)}
    # Over tolerance: hold only if residual exposure fits allocation.
    exposed = sum(residual.values())
    if exposed <= max_orphan:
        return 'HOLD', {'reason': 'await_better_books', 'worst_slip': round(worst, 4)}
    return 'UNWIND', {'reason': 'orphan_breach', 'exposed': exposed}
