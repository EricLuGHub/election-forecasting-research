"""Held-out venue scoring with shrinkage (backlog item 55). Pure.

A venue selected because two past fills looked good has weak support.
Process: estimate per-venue edge on EARLY data, shrink toward the global
baseline by n/(n+K) (tiny samples collapse to baseline — no more
two-fill venues), select the allowlist early, validate persistence on
LATE data (sign agreement + rank correlation). A selection that does
not persist was noise; retire it without ceremony.

K predeclared (K=10 events): a venue needs ~10+ events before its own
estimate outweighs the baseline. Not tuned — stated.
"""
K_SHRINK = 10.0


def shrink(venue_mean, n, baseline, k=K_SHRINK):
    """Shrunk estimate. Refuses bad inputs (no estimate from nothing)."""
    try:
        m, n, b, k = float(venue_mean), float(n), float(baseline), float(k)
    except (TypeError, ValueError):
        return None
    if n <= 0 or k < 0:
        return None
    return round((n * m + k * b) / (n + k), 4)


def select_allowlist(scores, bar=0.0):
    """scores: {venue: shrunk_edge} -> sorted [venues] above bar."""
    try:
        return sorted([v for v, s in scores.items() if s is not None and s > bar],
                      key=lambda v: -scores[v])
    except TypeError:
        return None


def validate(early_rank, late_sign):
    """early_rank: [venues] selected early; late_sign: {venue: +/-1}.
    Returns agreement rate or None (no overlap — nothing to validate)."""
    overlap = [v for v in early_rank if v in late_sign]
    if not overlap:
        return None
    agree = sum(1 for v in overlap if late_sign[v] > 0)
    return {'n': len(overlap), 'agree_rate': round(agree / len(overlap), 3)}
