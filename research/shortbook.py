"""Overpriced-longshot short book: systematized cohort view (item 62). Pure.

Each YES-short collects premium P for tail T (=qty): normal settlement
keeps P; the upset pays T (net -(T-P)). The item-62 discipline per short:
1. UPPER BOUND: forecast upset probability p_up (external, timestamped)
   must satisfy p_up * T < P — the premium covers even the generous case.
2. COVER MARK: executable YES-bid cover cost C at remaining qty vs P —
   bankable-now = P - C when C < P (realizable, not a mark).
3. ALLOCATION: size by max loss (T - P), not by premium; cap single-tail
   share of book risk.
4. WAVE: aggregate upset losses by party direction — a red wave hits R
   shorts together, a blue wave hits D shorts together. Mixed books are
   a natural wave hedge; quantify both tails.

Statuses: 'certified' (bound holds + cover-bankable or improving),
'watch' (bound holds but cover above premium — thesis intact, exit costs),
'breach' (bound fails — thesis broken, cover per triggers).
"""


def analyze(name, party, qty, premium, tail, cover_cost, p_up):
    """(status, detail). party: 'R'/'D' whose YES was shorted. cover_cost:
    executable buy-back at remaining qty (None when unmeasurable — then
    no banked claim, status at best 'watch'). p_up: forecast upper bound
    on the shorted party winning."""
    try:
        qty = int(qty)
        premium, tail = float(premium), float(tail)
        p_up = float(p_up)
        cover = None if cover_cost is None else float(cover_cost)
    except (TypeError, ValueError):
        return None, {'short': name, 'refused': 'non-numeric input'}
    if qty <= 0 or tail <= 0 or not 0 <= p_up <= 1:
        return None, {'short': name, 'refused': 'bad economics'}
    max_loss = round(tail - premium, 2)
    bound_cost = round(p_up * tail, 2)
    bound_holds = bound_cost < premium
    banked = None if cover is None else round(premium - cover, 2)
    detail = {'short': name, 'party': party, 'qty': qty,
              'premium': premium, 'tail': tail, 'max_loss': max_loss,
              'p_up': p_up, 'bound_cost': bound_cost,
              'bound_holds': bound_holds, 'cover_cost': cover,
              'banked_now': banked}
    if not bound_holds:
        detail.update(status='breach',
                      why=('p_up %.2f x tail %.0f = %.2f >= premium %.2f'
                           % (p_up, tail, bound_cost, premium)))
        return 'breach', detail
    if banked is not None and banked > 0:
        detail.update(status='certified',
                      why=('bound holds (%.2f < %.2f) + bankable +%.2f now'
                           % (bound_cost, premium, banked)))
        return 'certified', detail
    detail.update(status='watch',
                  why=('bound holds but cover %.2f >= premium, thesis intact'
                       % (cover if cover is not None else float('nan'))))
    return 'watch', detail


def wave_loss(analyses):
    """{party: total upset net} over (status, detail) pairs. Upset net per
    short = -(tail - premium). Mixed books hedge waves; same-side books
    concentrate them."""
    out = {}
    for _, d in analyses:
        if not d or 'refused' in d:
            continue
        out[d['party']] = round(out.get(d['party'], 0.0)
                                - (d['tail'] - d['premium']), 2)
    return out
