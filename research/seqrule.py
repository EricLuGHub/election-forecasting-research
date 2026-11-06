"""Sequential decision rules suited to strategy class (item 85). Pure.

A fixed "500 fills and 52% wins" gate misleads twice: correlated fills
from one hot race pass it on dependence, while low-frequency structural
trades (E8: n=2, +$49.61) can never meet it no matter how clean. Rules:
- maker (high-frequency): clustered-t confidence — collapse fills to
  cluster (race/day) means, t-interval over clusters must clear 0 with
  MIN_CLUSTERS distinct clusters. 500 fills from 3 races prove nothing.
- structural (low-frequency): K clean stages with no breach (floor,
  conflict, orphan, rescore-flip) + predeclared K (default 3). Two clean
  stages = promising, not proven — the rule must say "not yet".
- stability: same sign across genuinely different periods (early/late
  halves per item 82); reported, not averaged.
"""
MIN_CLUSTERS = 8
CLEAN_STAGES = 3


def clustered_ci(values, clusters, conf=1.96):
    """Mean + conf-level normal interval over CLUSTER means. Returns
    (mean, lo, hi, n_clusters) or None when <2 clusters (no interval
    from one basket — refused, not zero-width)."""
    from collections import defaultdict
    import math
    groups = defaultdict(list)
    for v, c in zip(values, clusters):
        try:
            groups[c].append(float(v))
        except (TypeError, ValueError):
            return None
    means = [sum(g) / len(g) for g in groups.values()]
    n = len(means)
    if n < 2:
        return None
    mean = sum(means) / n
    if n == 2:
        half = abs(means[0] - means[1])
    else:
        var = sum((m - mean) ** 2 for m in means) / (n - 1)
        half = conf * math.sqrt(var / n)
    return {'mean': round(mean, 4), 'lo': round(mean - half, 4),
            'hi': round(mean + half, 4), 'n_clusters': n}


def decide_maker(values, clusters, min_clusters=MIN_CLUSTERS):
    """(decision, detail). PROMOTE only on clustered CI > 0 with enough
    distinct clusters; else KEEP TESTING (starved or dependent)."""
    ci = clustered_ci(values, clusters)
    if ci is None:
        return 'keep-testing', {'reason': 'fewer than 2 clusters'}
    if ci['n_clusters'] < min_clusters:
        return 'keep-testing', {'reason': 'only %d clusters (need %d)'
                                % (ci['n_clusters'], min_clusters), 'ci': ci}
    if ci['lo'] > 0:
        return 'promote', {'ci': ci}
    return 'keep-testing', {'reason': 'clustered CI covers zero', 'ci': ci}


def decide_structural(clean_stages, breaches, required=CLEAN_STAGES):
    """(decision, detail). PROMOTE at required clean stages, zero breach
    tolerance (any breach resets the count — stated)."""
    if breaches:
        return 'stop', {'reason': '%d breach(es): count reset' % len(breaches),
                        'clean': clean_stages}
    if clean_stages >= required:
        return 'promote', {'clean': clean_stages}
    return 'keep-testing', {'reason': '%d/%d clean stages — not yet'
                            % (clean_stages, required)}
