"""Inventory skew tied to risk and exit capacity (backlog item 58). Pure.

Reduction pressure per position, predeclared weights (stated, not tuned):
  exposure: capital share of book (big positions dominate risk).
  depth: 1 - min(exit_depth / position_size, 1) (can't exit = pressure;
    exit depth from live books, stale labeled).
  correlation: count of same-direction same-state positions (wave load
    per c195: red-wave R shorts move together).
  underwater: 1 when mark < cost (loss positions consume attention and
    E1's floor logic; pressure to resolve, not to fire blindly).
pressure = exposure * (0.5 + depth + 0.25*corr_norm + 0.25*underwater).
Ranks reduction CANDIDATES for the exit owner — never fires (their
engine, their guards). Paper proposals with reasons attached.
"""


def pressure(capital, book_capital, exit_depth, position_size,
             corr_count, corr_max, underwater):
    """(score, components). corr normalized by book max. exit_depth
    None = unknown depth: scored without the depth term and flagged
    needs_depth (routes a depth check, never assumes exitable)."""
    try:
        cap, tot = float(capital), float(book_capital)
        size = float(position_size)
        cc, cm = float(corr_count), float(corr_max)
        uw = 1.0 if underwater else 0.0
    except (TypeError, ValueError):
        return None, {'refused': 'non-numeric'}
    if tot <= 0 or size <= 0 or cm < 0:
        return None, {'refused': 'bad scale'}
    if exit_depth is None:
        depth_known, thin = False, None
    else:
        try:
            thin = 1.0 - min(float(exit_depth) / size, 1.0)
        except (TypeError, ValueError):
            return None, {'refused': 'bad depth'}
        depth_known = True
    exposure = cap / tot
    corr = min(cc / cm, 1.0) if cm > 0 else 0.0
    score = exposure * (0.5 + (thin if thin is not None else 0.0)
                        + 0.25 * corr + 0.25 * uw)
    return round(score, 4), {'exposure': round(exposure, 4),
                             'thin': round(thin, 3) if thin is not None else None,
                             'corr': round(corr, 3), 'underwater': uw,
                             'depth_known': depth_known}


def rank(candidates):
    """candidates: [(name, score, components)] -> sorted desc, unscored
    last (refused entries rank never — reported, not hidden)."""
    ok = [(n, s, c) for n, s, c in candidates if s is not None]
    bad = [n for n, s, c in candidates if s is None]
    ok.sort(key=lambda t: -t[1])
    return ok, bad
