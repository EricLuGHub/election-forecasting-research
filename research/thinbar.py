"""Thinner-edge buying tier (user-authorized c246). Pure.

The $15/total + 1c/share tier stands for full-size baskets (evidence Kept).
Beside it, a THIN tier for small clips, authorized by the user on
throughput grounds ("better than no edge"):
- THIN bars: absolute >= $5.00 AND marginal rate >= 0.5c/share at every
  step (half the standard bars — stated, not derived).
- THIN caps: $2,000 max per basket (vs $5k standard); $70k total unchanged.
- THIN stops: 3 consecutive sub-cost exits retire the tier back to paper
  (bounded experiment discipline); any floor violation refuses as usual.
- Same verify+fire path, same executor, same namespaces; tier recorded
  on every intent (THIN- prefix) for attribution.
A thin edge is still an edge: floor-backed, depth-verified, settled.
Dust (sub-$5, sub-0.5c) stays dead — that evidence was not overturned.
"""
THIN_ABS = 5.0
THIN_RATE = 0.005
THIN_CAP = 2000.0


from .marginal import choose


def qualifies(curve_rows, abs_bar=THIN_ABS, rate_bar=THIN_RATE):
    """Thin-tier answer via the single traversal (marginal.choose with
    thin bars — no duplicated logic to drift; item-110 unit discipline)."""
    return choose(curve_rows, min_edge=abs_bar, min_per_share=rate_bar)
