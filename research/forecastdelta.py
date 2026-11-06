"""Forecast-change gate: trade updates only beyond uncertainty (item 71). Pure.

A newly retrieved article containing old information is not a signal.
Versioned forecasts enter with (source, version_at, p, uncertainty) where
uncertainty is the source's own interval (half-width). A tradable update
needs |p_new - p_old| > k * (u_old + u_new) with k=1 predeclared — the
move must clear the combined doubt, not just the point estimates.
SIG comparison: did our book move WITH the forecast (confirmation),
AGAINST it (divergence — widen, per item 65), or NOT AT ALL (stale
books or already-priced information)?

Stale-article guard: same source value re-retrieved later is versioned
by content, not retrieval time — identical content never triggers.
"""
K = 1.0


def version(source, at, p, uncertainty):
    try:
        p, u = float(p), float(uncertainty)
    except (TypeError, ValueError):
        return None
    if not source or not at or not 0 <= p <= 1 or u < 0:
        return None
    return {'source': source, 'at': at, 'p': p, 'u': u}


def change_gate(old, new, k=K):
    """(tradeable, detail). Same source, new content required."""
    if not old or not new or old['source'] != new['source']:
        return False, {'reason': 'needs two versions, same source'}
    if old['p'] == new['p'] and old['u'] == new['u']:
        return False, {'reason': 'identical content re-retrieved — not news'}
    move = abs(new['p'] - old['p'])
    bar = k * (old['u'] + new['u'])
    detail = {'move': round(move, 4), 'bar': round(bar, 4),
              'old': old, 'new': new}
    if move > bar:
        detail['reason'] = 'move clears combined uncertainty'
        return True, detail
    detail['reason'] = 'move within combined uncertainty'
    return False, detail


def sig_comparison(forecast_move, sig_move):
    """Confirmation / divergence / stale classification of OUR book move
    against the forecast move (same direction units, same window)."""
    try:
        fm, sm = float(forecast_move), float(sig_move)
    except (TypeError, ValueError):
        return 'unknown'
    if abs(sm) < 0.005:
        return 'stale-or-priced'
    if fm * sm > 0:
        return 'confirmation'
    return 'divergence'
