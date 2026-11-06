"""Maker vs passive-buyer separation (backlog item 54). Pure.

One "quoting" label hides two strategies with different clocks:
- MAKER (inventory-controlled): earns spread per round-trip; horizon
  minutes–hours; exits into the opposite touch; capital recycles fast;
  bar = clustered spread-capture rate > 0 after adverse selection
  (seqrule maker rule). Needs: two-sided flow, tight inventory, fast
  exits. Dies on: one-sided books, slow exits, trend days.
- BUYER (fair-value-constrained passive): buys below fair value, holds
  to convergence/settlement; horizon days–weeks; exits at bankable
  flags or floor; capital locked (bound for weeks); bar = edge vs
  settlement/floor clearing absolute + rate bars (marginal $15/1c).
  Needs: verifiable edge, patience, exit monitoring. Dies on:
  overpaying, no-exit holds, capital starvation elsewhere.
Mapping our engines (evidence-backed): E2 entries = BUYER (floor edge,
$15 bar, 29-day horizon); E8 exits = BUYER's exit leg (same clock);
v4 quoter = MAKER aspirant (paper detector; starved of two-sided flow);
E1-REDUCE = exit-only recovery (neither — loss-banking, not edge).
Confusion to avoid: judging BUYER entries by maker fill-rates, or MAKER
quotes by settlement edge. Each bar binds only its own strategy.
"""

STRATEGIES = {
    'maker': {'horizon': 'minutes-hours', 'exit': 'opposite touch',
              'capital': 'recycling', 'bar': 'clustered spread-capture > 0',
              'dies_on': 'one-sided books, slow exits, trend days'},
    'buyer': {'horizon': 'days-weeks', 'exit': 'bankable flag or floor',
              'capital': 'locked', 'bar': 'edge vs settlement + $15/1c',
              'dies_on': 'overpaying, no-exit holds, capital starvation'},
}


def classify(name, holds_inventory, quotes_both_sides, edge_vs_settlement,
             horizon_days):
    """Engine activity -> 'maker' | 'buyer' | 'neither' with reason.
    Neither = exit-only recovery / loss-banking (no edge thesis)."""
    try:
        horizon_days = float(horizon_days)
    except (TypeError, ValueError):
        return 'neither', {'engine': name, 'reason': 'bad horizon'}
    if not holds_inventory and quotes_both_sides:
        return 'maker', {'engine': name, 'reason': 'two-sided, no inventory'}
    if holds_inventory and edge_vs_settlement:
        return 'buyer', {'engine': name, 'reason': 'holds to convergence'}
    return 'neither', {'engine': name,
                       'reason': 'exit-only or no edge thesis'}
