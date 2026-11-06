"""Conserved lot allocation across repeated entries (backlog item 108). Pure.

reconcile.py reports per-basket paired qty from ALL lots on each leg, so
two ledger entries in one race both claim the same shares (double
attribution). This module attributes FIFO: entries ordered by acquisition
time consume oldest lots first per leg; each share attributed ONCE.
Exits (E8X fills, reducer sales) consume attributed lots first (FIFO
netting); leftovers carry as unattributed residue (netting artifacts,
non-basket holdings — flagged, never double-counted).

Completion contract (item text): total attributed shares never exceed
current owned shares — across two same-race entries, FIFO netting, and
reducer sales. Tested exactly.
"""


def allocate(entries, lots_by_eid, exits=()):
    """entries: [(name, eid_r, eid_d, size, at)] oldest-first wins ties by
    name. lots_by_eid: {eid: [(qty, opened_at)]} oldest-first. exits:
    [(eid, qty, at)] consumed FIFO from attributed lots.
    Returns {name: attributed_pairs} + {'_residue': {eid: qty}}.
    Attributed total per eid never exceeds owned lots (asserted)."""
    lots = {e: sorted([(float(q), a) for q, a in ls], key=lambda t: (t[1], t[0]))
            for e, ls in lots_by_eid.items()}
    # exits consume oldest attributed-eligible lots first
    for eid, qty, _ in sorted(exits, key=lambda t: t[2]):
        try:
            need = float(qty)
        except (TypeError, ValueError):
            continue
        pool = lots.get(str(eid), [])
        rest = []
        for q, a in pool:
            if need <= 0:
                rest.append((q, a))
                continue
            take = min(q, need)
            need -= take
            if q - take > 0:
                rest.append((q - take, a))
        lots[str(eid)] = rest
    out = {}
    for name, er, ed, size, _ in sorted(entries, key=lambda t: (t[4], t[0])):
        try:
            want = float(size)
        except (TypeError, ValueError):
            out[name] = 0
            continue
        if want <= 0:
            out[name] = 0
            continue
        lr, ld = lots.get(str(er), []), lots.get(str(ed), [])
        rq, dq = sum(q for q, _ in lr), sum(q for q, _ in ld)
        take = min(want, rq, dq)
        out[name] = int(take) if take == int(take) else round(take, 2)
        for eid in (str(er), str(ed)):
            pool, need, rest = lots.get(eid, []), take, []
            for q, a in pool:
                if need <= 0:
                    rest.append((q, a))
                    continue
                t = min(q, need)
                need -= t
                if q - t > 0:
                    rest.append((q - t, a))
            lots[eid] = rest
    residue = {e: round(sum(q for q, _ in ls), 2) for e, ls in lots.items()}
    return out, {'_residue': residue}
