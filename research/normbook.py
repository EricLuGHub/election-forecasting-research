"""Normalize the whole book to common exposure units (item 53). Pure.

Labels lie: "long NO", "short YES", "buy YES-only" are venue vocabulary,
not economics. Every position restates as:
- p_now: current mark-implied probability of the held outcome.
- win_payoff / lose_payoff per share (settlement-normalized, +1/0).
- capital_at_risk: cost basis tied up.
- direction: favorite (p_now > 0.5) or longshot (p_now <= 0.5) side held.
Book verdict: net capital and net payoff-at-upset on favorite-held vs
longshot-held exposure. A book 100% longshot-fade is a VIEW (acceptable
if priced — c195 bounds) or an ARTIFACT of one-sided screening
(unacceptable — means the entry filter never looks at favorite value).
The module reports the balance; the filter audit decides which.
"""


def normalize(qty, avg_cost, mark, side):
    """Position -> exposure dict. Venue sign conventions (NO booked
    negative, rebooked shorts) make long/short inference from the sign
    fiction — report BOOKED exposure only (side + mark economics).
    mark: current price of held outcome in [0,1]. Refuses bad inputs."""
    try:
        qty = float(qty)
        cost, m = float(avg_cost), float(mark)
    except (TypeError, ValueError):
        return None
    if qty == 0 or not 0 <= m <= 1 or cost < 0:
        return None
    if side not in ('YES', 'NO'):
        return None
    n = abs(qty)
    exposure = n * m  # mark value of the held outcome claim
    return {'qty': n, 'booked': ('short' if qty < 0 else 'long') + '-' + side,
            'side': side, 'p_now': round(m, 4),
            'capital': round(n * cost, 2),
            'value': round(exposure, 2),
            'direction': 'favorite' if m > 0.5 else 'longshot'}


def book_balance(positions):
    """positions: normalize() dicts. Returns capital/value split by
    direction + concentration verdict."""
    fav_c = fav_v = long_c = long_v = 0.0
    n_fav = n_long = 0
    for p in positions:
        if not p:
            continue
        if p['direction'] == 'favorite':
            fav_c += p['capital']
            fav_v += p['value']
            n_fav += 1
        else:
            long_c += p['capital']
            long_v += p['value']
            n_long += 1
    total = fav_c + long_c
    share = round(long_c / total, 3) if total > 0 else None
    verdict = ('single-direction' if share in (0.0, 1.0)
               else 'longshot-tilted' if share is not None and share > 0.7
               else 'balanced' if share is not None else 'empty')
    return {'favorite_capital': round(fav_c, 2), 'longshot_capital': round(long_c, 2),
            'favorite_positions': n_fav, 'longshot_positions': n_long,
            'longshot_share': share, 'verdict': verdict}
