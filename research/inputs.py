"""Probability-input dependence audit (backlog item 65). Pure.

Five aggregators of the same polls are one vote, not five. Families:
- polls: direct voter surveys (timestamped, MoE-carrying).
- aggregates: poll averages (inherit poll dependence by construction).
- markets: money-weighted (but ingest polls — FTP anchors on market
  price then moves it with polling averages; Kalshi/Polymarket 88/89
  is one book quoted twice, not two witnesses).
- fundamentals: structure (PVI, incumbency, fundraising, past results)
  — genuinely orthogonal to polls, and they DIVERGE (IA: R+2.1 vs D+7.8).
- book: the SIG quote itself (the thing being priced, not an input).

Rules: record source timestamps + coverage; when cross-family spread on
the same race exceeds WIDEN_AT, widen uncertainty instead of averaging
it away; never count two same-family sources as independent.
"""
WIDEN_AT = 0.10


def register(source, family, at, coverage, p_dem):
    """Normalized input record. p_dem: P(Democrat wins) in [0,1]."""
    try:
        p = float(p_dem)
    except (TypeError, ValueError):
        return None
    if family not in ('polls', 'aggregates', 'markets', 'fundamentals',
                      'book') or not 0 <= p <= 1:
        return None
    return {'source': source, 'family': family, 'at': at,
            'coverage': coverage, 'p_dem': p}


EFFECTIVE = {'polls': 'polls', 'aggregates': 'polls', 'markets': 'markets',
             'fundamentals': 'fundamentals', 'book': 'book'}


def audit(records):
    """{effective_families, family_values, spread, widen, note}.

    Same-family sources collapse to their median (one vote). widen=True
    when cross-family spread >= WIDEN_AT — average-no-more, report range.
    """
    by_fam = {}
    for r in records:
        if r is None:
            continue
        by_fam.setdefault(EFFECTIVE[r['family']], []).append(r['p_dem'])
    med = {f: sorted(v)[len(v) // 2] for f, v in by_fam.items()}
    vals = list(med.values())
    spread = round(max(vals) - min(vals), 3) if vals else 0.0
    note = ('independent families disagree' if spread >= WIDEN_AT
            else 'families agree')
    if len(med) < 2:
        note = 'single effective family — no cross-check possible'
    return {'effective_families': sorted(med),
            'family_values': med, 'spread': spread,
            'widen': spread >= WIDEN_AT, 'note': note}
