"""Factor-adjusted relative value (backlog item 77). Pure.

Two races, same national factor, different local news: if SIG prices
them inconsistently with fundamentals, a PAIR (long cheap leg, short
rich leg) isolates the idiosyncratic — but a national wave hits both
legs together, so this is RISKY relative value, never a hedge. Sizing
by payoff sensitivity: size_ratio = sens_rich / sens_cheap (equalize
P&L per point of idiosyncratic move); residual stress = both legs move
together ±s (the wave the pair does NOT hedge — quantified, not wished
away). Verdicts: 'paper-setup' (spread + sizing + residual all stated),
'no-spread' (prices consistent — nothing to do), or refusal.
"""


def spread(cheap_px, rich_px):
    """Mispricing gap in price units, or None."""
    try:
        return round(float(rich_px) - float(cheap_px), 4)
    except (TypeError, ValueError):
        return None


def size_ratio(sens_rich, sens_cheap):
    """Equalize P&L per idiosyncratic point: qty_rich/qty_cheap =
    sens_cheap/sens_rich. Returns ratio or None."""
    try:
        r, c = float(sens_rich), float(sens_cheap)
    except (TypeError, ValueError):
        return None
    if r <= 0 or c <= 0:
        return None
    return round(c / r, 3)


def residual_stress(qty_cheap, qty_rich, wave):
    """Both legs move together by wave (same sign): net P&L. The pair
    does not hedge this — number it."""
    try:
        return round((float(qty_cheap) - float(qty_rich)) * float(wave), 2)
    except (TypeError, ValueError):
        return None


def verdict(name, cheap_px, rich_px, sens_cheap, sens_rich, min_spread=0.02):
    """(verdict, detail). min_spread predeclared 2c (below = noise)."""
    sp = spread(cheap_px, rich_px)
    if sp is None:
        return None, {'pair': name, 'refused': 'bad prices'}
    if sp < min_spread:
        return 'no-spread', {'pair': name, 'spread': sp,
                             'why': 'prices consistent within 2c'}
    ratio = size_ratio(sens_rich, sens_cheap)
    if ratio is None:
        return None, {'pair': name, 'refused': 'bad sensitivity'}
    return 'paper-setup', {'pair': name, 'spread': sp,
                           'qty_ratio_rich_over_cheap': ratio,
                           'why': 'mispricing with sized residual risk'}
