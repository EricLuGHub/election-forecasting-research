"""Equivalent favorite-contract routes (backlog item 63). Pure.

Bearish-S exposure (profit iff S loses) via three routes, per-share P&L
across settlement states {S wins, D wins, Other}:
- A short S-YES @p:        S: -(1-p)   D: +p        O: +p
- B long D-YES @ask a:     S: -a       D: +(1-a)    O: -a
- C long S-NO @ (1-bidS):  S: -(1-bS)  D: +bS       O: +bS
A and C share the state profile (both win iff S loses); the better number
wins outright. B differs in state O (loses under third-party) — never
strictly comparable; quantify the tradeoff instead of forcing a rank.

Verdicts (predeclared): 'route-optimal' (A numbers ≥ C and B-tradeoff
favors A), 'c-cheaper' (C strictly better states+numbers), 'b-tradeoff'
(B wins more in D but bleeds R and O — report, owner judges).
Third-party contracts (e.g. MT Independent) live in state O explicitly.
"""


def table(p, a, bidS):
    """Per-share P&L by route and state. Nones refuse (missing quotes are
    not a route)."""
    try:
        p, a, bidS = float(p), float(a), float(bidS)
    except (TypeError, ValueError):
        return None
    if not (0 < p < 1 and 0 < a < 1 and 0 < bidS < 1):
        return None
    c = 1.0 - bidS
    return {'A_short_YES': {'S': -(1 - p), 'D': p, 'O': p},
            'B_long_DYES': {'S': -a, 'D': 1 - a, 'O': -a},
            'C_long_SNO': {'S': -c, 'D': bidS, 'O': bidS}}


def compare(name, p, a, bidS):
    """(verdict, detail) with exact per-state tables."""
    t = table(p, a, bidS)
    if t is None:
        return None, {'race': name, 'refused': 'bad quotes'}
    A, B, C = t['A_short_YES'], t['B_long_DYES'], t['C_long_SNO']
    detail = {'race': name, 'table': {k: {s: round(v, 4) for s, v in r.items()}
                                      for k, r in t.items()}}
    if p > bidS + 1e-9:
        detail.update(verdict='route-optimal',
                      why=('A collects %.3f > C pays %.3f, same states; B '
                           'bleeds %.3f in O where A wins %.3f'
                           % (p, bidS, a, p)))
        return 'route-optimal', detail
    if bidS > p + 1e-9:
        detail.update(verdict='c-cheaper',
                      why=('C pays %.3f > A collects %.3f, same states'
                           % (bidS, p)))
        return 'c-cheaper', detail
    detail.update(verdict='b-tradeoff',
                  why=('A≈C tie (%.3f); B wins %.3f in D but loses R and O'
                       % (p, 1 - a)))
    return 'b-tradeoff', detail
