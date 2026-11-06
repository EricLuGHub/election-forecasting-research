"""Staged size ladder (backlog item 87). Measured clips only, no extrapolation.

Evidence: NH Senate buy-basket depth walks at six sizes (recorded pre-fire),
plus basket fire outcomes at 250/500/1000 sizes. Rule: advance one clip at a
time while MARGINAL edge/share >= 1.0c AND marginal absolute >= $15; stop at
the first clip that fails either. Doubling capital never preserves edge by
assumption — the table proves where it vanishes instead.
"""
import json

# Measured NH Senate (R-NO + D-NO) buy cost/edge per clip, depth-walked live.
NH_MEASURED = [
    # (shares_per_leg, total_cost, floor) from live depth walks
    (1000, 965.00, 1000.0),
    (2000, 1931.52, 2000.0),
    (5000, 4859.71, 5000.0),
    (10000, 9807.30, 10000.0),
]
# Typical-rotation-basket evidence at 1000 (median of fired rounds).
TYPICAL_1000_EDGE = 25.0
NJ_500_EDGE = 7.50


def marginals(clips):
    """[(size, edge, marginal_edge, marginal_per_share)] stepwise."""
    rows = []
    prev_size, prev_edge = 0, 0.0
    for size, cost, floor in clips:
        edge = floor - cost
        m_edge = edge - prev_edge
        m_size = size - prev_size
        rows.append({'size': size, 'edge': round(edge, 2),
                     'marginal_edge': round(m_edge, 2),
                     'marginal_per_share': round(m_edge / (2 * m_size), 4) if m_size else None})
        prev_size, prev_edge = size, edge
    return rows


def recommend(clips, min_marginal=15.0, min_per_share=0.01):
    """Largest clip where the MARGINAL step clears both bars. Returns row."""
    ok = None
    for row in marginals(clips):
        if row['marginal_edge'] >= min_marginal and \
                (row['marginal_per_share'] or 0) >= min_per_share:
            ok = row
        else:
            break
    return ok


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()
    rows = marginals(NH_MEASURED)
    print(json.dumps({'nh_clips': rows,
                      'recommend_nh': recommend(NH_MEASURED)}, indent=2))


if __name__ == '__main__':
    main()
