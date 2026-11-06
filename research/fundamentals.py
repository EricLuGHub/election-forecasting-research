"""Fundamentals where polling is sparse (backlog item 74). Pure.

Polls cover marquee races; House districts mostly have fundamentals only
(PVI, incumbency, Cook rating). Records per race (all sourced+dated) and
checks DIRECTION agreement with SIG-implied favorite (YES-bid > 0.5
side). Level agreement is not tested — books move, ratings lag, and
the pair floor doesn't care who wins. Held-out improvement over polls
needs outcomes (post-election); until then this is a consistency table
with teeth: any SIG-vs-fundamentals DIRECTION disagreement flags a race
for the uncertainty-widening rule (item 65).
"""


def record(race, pvi, incumbency, cook, cook_date, source_date):
    """Verified fundamentals row. pvi: e.g. 'R+6'. incumbency: 'R'/'D'/
    'OPEN'. cook: rating string. Any missing -> None (gaps explicit)."""
    if not race or pvi is None or cook is None:
        return None
    return {'race': race, 'pvi': pvi, 'incumbency': incumbency,
            'cook': cook, 'cook_date': cook_date, 'asof': source_date}


def lean_of(row):
    """Implied favorite party from Cook rating text, or None."""
    if row is None:
        return None
    t = str(row.get('cook', ''))
    if ' R' in t or t.startswith('R'):
        return 'R'
    if ' D' in t or t.startswith('D'):
        return 'D'
    rating = t.lower()
    if 'republican' in rating and 'democrat' not in rating:
        return 'R'
    if 'democrat' in rating and 'republican' not in rating:
        return 'D'
    return None


def agree(row, sig_fav):
    """Direction agreement vs SIG-implied favorite ('R'/'D'/None)."""
    if row is None or sig_fav not in ('R', 'D'):
        return None
    fund = lean_of(row)
    if fund is None:
        return None
    return {'agree': fund == sig_fav, 'fundamentals': fund,
            'sig': sig_fav}
