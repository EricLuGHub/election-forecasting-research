"""Event-driven targeted discovery triggers (backlog item 34). Pure.

Replace "scan everything daily or constantly" with: hold a baseline per
tracked basket, re-value ONLY on meaningful book change or new listings.
Predeclared trigger bars (not tuned — stated, then measured):
- PRICE: |Δ joint top NO-cost| >= 1c/share at reference qty (matches the
  1c marginal-rate bar; smaller moves cannot clear it).
- DEPTH: top-level size on either leg changed >= 25% (liquidity regime
  shift; edge math may follow).
- RELIST: pair eids differ from baseline (contract re-listing).
- NEW: catalog contains R/D markets for tracked races absent at baseline.

A trigger is a HUNTING instruction (re-run the verifier), never a fire
order. Quiet books cost zero API beyond the cheap top-book poll.
"""
PRICE_TRIGGER = 0.01
# Calibrated c191 (two-snapshot demo, needs a longer series): 25% depth
# fired 17/21 on seed-ladder flicker with zero accompanying price moves;
# 100% fires 6/21, all multi-x regime shifts. Depth is a noisy trigger on
# market-maker books — keep it wide, let price do the fine work.
DEPTH_TRIGGER = 1.0


def top(book):
    """(price, size) of best YES bid, or (None, 0) when absent."""
    try:
        bids = book.get('bids', []) if isinstance(book, dict) else []
        if not bids:
            return None, 0
        return float(bids[0]['price']), float(bids[0]['quantity'])
    except (KeyError, TypeError, ValueError):
        return None, 0


def joint_top_cost(top_r, top_d):
    """Per-share NO-buy cost at top of book (2 legs), or None."""
    if top_r[0] is None or top_d[0] is None:
        return None
    return (1.0 - top_r[0]) + (1.0 - top_d[0])


def should_recheck(name, old, new, reference_note=''):
    """old/new: {'eids': (r, d), 'top_r': (p, s), 'top_d': (p, s)}.

    Returns (fire: bool, reasons: [str]). Missing books never fire —
    absence of data is not a signal (refuses quietly with reason).
    """
    reasons = []
    if old.get('eids') != new.get('eids'):
        if old.get('eids') and new.get('eids'):
            reasons.append('relist %s->%s' % (old['eids'], new['eids']))
        else:
            return False, ['missing pair leg']
    for leg in ('top_r', 'top_d'):
        op, os = old.get(leg, (None, 0))
        np_, ns = new.get(leg, (None, 0))
        if op is None or np_ is None:
            return False, ['missing %s book' % leg]
        if os > 0 and abs(ns - os) / os >= DEPTH_TRIGGER:
            reasons.append('%s depth %.0f->%.0f' % (leg, os, ns))
    oc = joint_top_cost(old['top_r'], old['top_d'])
    nc = joint_top_cost(new['top_r'], new['top_d'])
    if oc is not None and nc is not None and abs(nc - oc) >= PRICE_TRIGGER:
        reasons.append('joint cost %.4f->%.4f' % (oc, nc))
    return (len(reasons) > 0), reasons


def catalog_diff(old_ids, new_markets, tracked_places):
    """New R/D exchange ids for tracked race places absent at baseline.

    old_ids: set of known exchange-id strings. new_markets: catalog market
    dicts (must carry title + first-exchange id). tracked_places: {'Iowa'}
    style place names. Returns sorted new ids. Title-matching is the same
    strict place+party rule as convexit (no fuzzy expansion).
    """
    found = set()
    for mk in new_markets:
        t = str(mk.get('title', ''))
        ex = mk.get('exchanges') or [{}]
        eid = str((ex[0] or {}).get('id', ''))
        if not eid or eid in old_ids:
            continue
        for place in tracked_places:
            if place in t and (('Republican' in t) != ('Democratic' in t)):
                found.add(eid)
    return sorted(found)
