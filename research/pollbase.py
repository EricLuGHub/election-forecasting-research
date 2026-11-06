"""Simple polling baseline: decay + house effects + error (item 73). Pure.

Deliberately SIMPLE (the item's point): inverse-variance weights with
exponential time decay, partisan-sponsor half-weighting, house-effect
reporting (not fitting — fitting 11 polls on 6 pollsters overfits; report
leave-one-out deviations instead), plus election-level error floor added
in quadrature (polls miss correlated — averaging 11 polls does not make
±1pt; floor ELECTION_ERR keeps the interval honest).

Predeclared: HALF_LIFE 14d, SPONSOR_WEIGHT 0.5, ELECTION_ERR 3.5pp (all
stated conventions, not tuned — tuning on the evaluation race is the
overfitting the item warns about). No historical vintages available here
(item's warning recorded as limitation: this is a current-race
demonstration, NOT an October execution backtest).
"""
HALF_LIFE_D = 14.0
SPONSOR_WEIGHT = 0.5
ELECTION_ERR = 3.5


def weight(n, moe, age_d, sponsored, half_life=HALF_LIFE_D):
    """Inverse-variance x decay x sponsor discount. None-safe."""
    try:
        n, moe, age_d = float(n), float(moe), float(age_d)
    except (TypeError, ValueError):
        return None
    if n <= 0 or moe <= 0 or age_d < 0:
        return None
    import math
    w = (n / moe / moe) * 0.5 ** (age_d / half_life)
    return w * (SPONSOR_WEIGHT if sponsored else 1.0)


def average(polls, ref_date, election_err=ELECTION_ERR):
    """polls: [(margin_D, n, moe, end_date, sponsored, name)].
    Returns (avg, se, house) with house = {name: loo_deviation}."""
    from datetime import datetime
    try:
        ref = datetime.fromisoformat(str(ref_date).replace('Z', '+00:00'))
    except ValueError:
        return None
    rows = []
    for margin, n, moe, end, sponsored, name in polls:
        try:
            age = (ref - datetime.fromisoformat(str(end).replace('Z', '+00:00'))).days
        except ValueError:
            continue
        w = weight(n, moe, age, sponsored)
        if w is None:
            continue
        rows.append((float(margin), w, float(moe), name))
    if not rows:
        return None
    tot = sum(w for _, w, _, _ in rows)
    avg = sum(m * w for m, w, _, _ in rows) / tot
    import math
    se = math.sqrt(sum((w / tot) ** 2 * me ** 2 for _, w, me, _ in rows)
                   + election_err ** 2)
    house = {}
    for m, w, me, name in rows:
        rest = [(mm, ww) for mm, ww, _, nn in rows if nn != name]
        if rest:
            t = sum(ww for _, ww in rest)
            house[name] = round(m - sum(mm * ww for mm, ww in rest) / t, 2)
    return {'avg': round(avg, 2), 'se': round(se, 2), 'n': len(rows),
            'house_effects': house}
