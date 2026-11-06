"""Coherent election-outcome risk model (backlog items 75 + 107). Pure.

PROBABILITY CONVENTION (stated once, used everywhere): p = P(the
contract's party wins its race), per (race, party). A national D wave
of size s means dp=+s on (race,'D') entries and dp=-s on (race,'R')
entries — never the same sign on both (item-107 fix; the old '*' did
exactly that wrong thing and a c232 runaround masked it).
Shock lookup order per position: (race, party) -> race -> party-letter
('D'/'R' national keys) -> 0.0. A bare '*' key means a uniform
non-directional book stress (documented, distinct from a wave).
Venue signs (c222): YES rows carry signed qty; NO rows book long as
negative, so NO always uses -abs(qty).

Two SEPARATE analyses (item-107 demand):
- revalue(): small mark sensitivities (linear, capped [0,1]).
- simulate(): joint BINARY outcomes (win/lose per race, correlated
  draws) paying structures at settlement: pairs floor at 1.0 per unit
  (2.0 if neither listed party wins), shorts keep premium or pay tails.
  A linear sensitivity never substitutes for tail loss — both reported.
"""
import random


def shift(p, s):
    try:
        return min(max(float(p) + float(s), 0.0), 1.0)
    except (TypeError, ValueError):
        return None


def national_wave(s_d):
    """National D-wave of size s_d as party-signed shock dict."""
    try:
        s = float(s_d)
    except (TypeError, ValueError):
        return None
    return {'D': s, 'R': -s}


def revalue(positions, shocks):
    """positions: [{race, party, side, qty, p}]. Returns
    (total_dvalue, per_race)."""
    per = {}
    for pos in positions:
        try:
            race = pos['race']
            party = pos['party']
            key = (race, party)
            if key in shocks:
                dp = shocks[key]
            elif race in shocks:
                dp = shocks[race]
            else:
                dp = shocks.get(party, shocks.get('*', 0.0))
            p0 = float(pos['p'])
            q = float(pos['qty'])
            dp = float(dp)
        except (KeyError, TypeError, ValueError):
            continue
        p1 = shift(p0, dp)
        if p1 is None:
            continue
        d = p1 - p0
        if pos.get('side') == 'YES':
            dv = q * d
        elif pos.get('side') == 'NO':
            dv = -abs(q) * d
        else:
            continue
        per[race] = per.get(race, 0.0) + dv
    return round(sum(per.values()), 2), {k: round(v, 2) for k, v in per.items()}


def concentration(per_race):
    """Top-3 share of |P&L|. None when empty."""
    vals = sorted((abs(v) for v in per_race.values()), reverse=True)
    if not vals or sum(vals) == 0:
        return None
    return round(sum(vals[:3]) / sum(vals), 3)


def simulate(structures, race_p, rho=0.0, n=2000, seed=7):
    """Joint binary outcomes. structures: [{name, kind, ...}] where kind
    'pair' has (qty, cost) paying floor 1.0/unit (2.0 if 'other' wins);
    kind 'short' has (qty, premium, tail, party) keeping premium unless
    its party wins (then paying tail). race_p: {race: (p_D, p_R, p_O)}.
    Correlation: mixture — with prob rho all races take the common draw,
    else independent draws (transparent, no copula machinery).
    Returns {mean, p5, p95, floor_breaches} over sims + n."""
    rng = random.Random(seed)
    names = list(race_p.keys())
    results = []
    breaches = 0
    for _ in range(n):
        common = rng.random()
        winners = {}
        for race in names:
            pd, pr, po = race_p[race]
            u = common if rng.random() < rho else rng.random()
            winners[race] = 'D' if u < pd else ('R' if u < pd + pr else 'O')
        total = 0.0
        for st in structures:
            if st['kind'] == 'pair':
                w = winners.get(st['race'], 'D')
                pay = 2.0 if w == 'O' else 1.0
                total += st['qty'] * pay - st['cost']
                if pay < 1.0:
                    breaches += 1
            elif st['kind'] == 'short':
                total += (-st['tail'] if winners.get(st['race']) == st['party']
                          else st['premium'])
        results.append(total)
    results.sort()
    pick = lambda q: results[min(n - 1, int(q * n))]
    return {'mean': round(sum(results) / n, 2), 'p5': round(pick(0.05), 2),
            'p95': round(pick(0.95), 2), 'floor_breaches': breaches, 'n': n}
