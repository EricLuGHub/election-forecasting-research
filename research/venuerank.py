"""Rank venues by expected earned profit per hour (backlog item 46). Pure.

Widest spread alone is the worst predictor (c190: uniform seed ladders).
Score per exchange from measured components (all per-eid evidence):
  intensity: quote changes/hour (activity proxy; monitor-cadence caveat
    from c208 applies — relative ranking, not absolute).
  capture: mean spread/2 in ticks (what a round-trip can earn if filled
    at touch on both sides — upper bound, labeled).
  depth: top-level size in hundreds (usable size gate).
  toxicity: continuation rate (c201/c209 regime-conditioned; fading a
    high-continuation venue fights drift — subtract).
score = intensity * capture_ticks * min(depth_hundreds, CAP) * (1 - tox)
Units are index-like (not dollars): RANKING only. Absolute profit/hour
needs fill-rate calibration the paper detector cannot supply — stated,
not smuggled. Negative scores refuse (bad inputs), zeros rank last.
"""
DEPTH_CAP = 20.0


def score(intensity, capture_ticks, depth_hundreds, toxicity,
          depth_cap=DEPTH_CAP):
    try:
        i, c, d, t = (float(intensity), float(capture_ticks),
                      float(depth_hundreds), float(toxicity))
    except (TypeError, ValueError):
        return None
    if i < 0 or c < 0 or d < 0 or not 0 <= t <= 1:
        return None
    return round(i * c * min(d, depth_cap) * (1 - t), 3)


def rank(venues):
    """venues: [(eid, intensity, capture, depth, tox)] -> sorted
    [(eid, score)] descending; unscorable last with None."""
    out = []
    for eid, i, c, d, t in venues:
        out.append((str(eid), score(i, c, d, t)))
    out.sort(key=lambda kv: (kv[1] is None, -(kv[1] or 0)))
    return out
