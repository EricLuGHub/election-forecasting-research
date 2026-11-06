"""Settlement-value intervals vs external probabilities (item 61). Pure.

For an R/D NO-pair basket the conservative bound is the floor (certain
under exhaustive R/D settlement — no external input needed). External
probability ranges add two things:
1. LEG-FAIRNESS: SIG-implied P(R)+P(D) vs 1.0. Legs summing far above 1.0
   (overround) with a cheap NO pair = structural discount, not a
   fundamental view. Legs summing far BELOW 1.0 while the NO pair is
   cheap = someone knows something; demand a wider bar.
2. SINGLE-LEG value: a lone NO leg is worth P(other wins) — externals
   price the directional residual item 43 warns about.

Edge interval for the pair at cost C (per unit): [floor - C, floor - C]
is a point under exhaustive settlement; the interval enters via
settlement-basis doubt (item 64): expected = (1-q) * floor + q * stressed,
with q the assessed basis-failure probability. This module computes the
breakeven q: the basis doubt that would erase the edge.
"""


def implied_probs(yes_bid_r, yes_bid_d):
    """(p_r, p_d, overround) from YES bids. Refuses Nones/non-numerics."""
    try:
        pr, pd = float(yes_bid_r), float(yes_bid_d)
    except (TypeError, ValueError):
        return None
    if not (0 <= pr <= 1 and 0 <= pd <= 1):
        return None
    return {'p_r': pr, 'p_d': pd, 'overround': round(pr + pd - 1.0, 4)}


def breakeven_q(edge, floor):
    """Basis-failure probability erasing the edge (edge/floor). None on bad
    inputs or non-positive edge (nothing to erase — refused, not zero)."""
    try:
        edge, floor = float(edge), float(floor)
    except (TypeError, ValueError):
        return None
    if floor <= 0 or edge <= 0:
        return None
    return round(edge / floor, 4)
