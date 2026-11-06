"""Post-fill replenishment after our own sweeps (backlog item 69). Pure.

Our stage-1/2 fills swept displayed depth. Did it come back? Compare
pre-fire vs post NO-bid ladders at the fill reference price:
- refilled: post depth >= 80% of pre (makers reloaded; reversal tradable
  again under the same bars).
- partial: 20-80% (thinner — re-entry at reduced size or not at all).
- pulled: <20% (liquidity was one-shot or makers repriced away).
Reversal note: post top price vs fill price — snapped back (c201 momentum
says it should), stuck (flow was informative), or improved (noise).

Thresholds are stated conventions (80/20), not calibrated optima — the
verdict is directional evidence for re-entry sizing, never a fire order.
"""
REFILLED_AT = 0.8
PULLED_BELOW = 0.2


def depth_at(levels, price):
    """Total size with bid price >= price. levels: [(price, size)]."""
    try:
        total = 0.0
        ref = float(price)
        for p, s in levels:
            # 1e-9 tolerance: live books carry float dust (0.1049999999 vs
            # 0.105) that would zero real depth (c202 caught it live).
            if float(p) >= ref - 1e-9:
                total += float(s)
        return total
    except (TypeError, ValueError):
        return None


def verdict(name, pre_levels, post_levels, ref_price, fill_price):
    """(verdict, detail). Refuses on bad ladders."""
    pre = depth_at(pre_levels, ref_price)
    post = depth_at(post_levels, ref_price)
    if pre is None or post is None or pre <= 0:
        return None, {'leg': name, 'refused': 'bad ladders'}
    ratio = round(post / pre, 2)
    if ratio >= REFILLED_AT:
        v = 'refilled'
    elif ratio < PULLED_BELOW:
        v = 'pulled'
    else:
        v = 'partial'
    try:
        rev = round(float(post_levels[0][0]) - float(fill_price), 4)
    except (IndexError, TypeError, ValueError):
        rev = None
    return v, {'leg': name, 'pre_depth': pre, 'post_depth': post,
               'ratio': ratio, 'reversal_vs_fill': rev,
               'why': 'post %.0f vs pre %.0f at %.3f' % (post, pre,
                                                          float(ref_price))}
