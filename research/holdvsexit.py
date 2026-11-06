"""Hold-vs-exit with a real alternative (backlog item 38 + LIQUIDITY.md).

Per flagged basket: G = remaining guaranteed payout (floor x paired
fraction), L = executable joint liquidation (convexit proceeds at depth).
Holding retains G-L over the remaining horizon. A replacement must beat
that with CONCRETE, sized, risk-adjusted cash — an empty queue and idle
cash are not a replacement.

Predeclared bar:
- retain <= 0 (L covers G: the book pays more than the guarantee) -> EXIT
  dominates holding outright; execution still belongs to E1, this module
  only ranks the proposal.
- retain > alt_gain + USD_ALLOWANCE and no concrete replacement -> HOLD.
- otherwise -> CONTINGENT (bankable if cash is ever needed).

Defaults: HOLD_DAYS 29 (to 2026-11-03 settlement, stated assumption, not a
verified release date); DUST_DAILY 0.00015 (cycle-2 measured dust economics:
~$1.25 per $250 locked 34d). USD_ALLOWANCE 5.00 (E8 absolute bar).
G assumes normal settlement semantics (item-64 basis risk noted, not priced).
"""
import json

HOLD_DAYS = 29
DUST_DAILY = 0.00015
USD_ALLOWANCE = 5.00


def analyze(name, floor, size, qty, proceeds, paired_cost,
            hold_days=HOLD_DAYS, alt_daily=DUST_DAILY,
            replacement=None):
    """(verdict, detail). Refuses (None, reason) on missing/bad inputs.

    paired_cost is the ledger cost AT qty (cost*qty/size) — the convexit row
    `cost` field already carries that scaling; do NOT scale again (c188:
    double-scaling printed 52.66/237.92 phantom edges).
    """
    try:
        floor = float(floor)
        size = int(size)
        qty = int(qty)
        proceeds = float(proceeds)
        paired_cost = float(paired_cost)
    except (TypeError, ValueError):
        return None, {'basket': name, 'refused': 'non-numeric input'}
    if size <= 0 or qty <= 0 or qty > size:
        return None, {'basket': name, 'refused': 'qty outside (0, size]'}
    paired_frac = qty / size
    G = round(floor * paired_frac, 2)
    L = round(proceeds, 2)
    retain = round(G - L, 2)
    if replacement is None:
        alt_gain = round(L * alt_daily * hold_days, 2)
        alt_desc = 'dust-rate placeholder (no concrete queue)'
    else:
        try:
            alt_gain = round(float(replacement['gain']), 2)
        except (KeyError, TypeError, ValueError):
            return None, {'basket': name, 'refused': 'bad replacement'}
        alt_desc = replacement.get('name', 'named replacement')
    edge_vs_cost = round(L - paired_cost, 2)
    if retain <= 0:
        verdict = 'exit'
        why = 'L(%.2f) covers G(%.2f): book pays more than guarantee' % (L, G)
    elif retain > alt_gain + USD_ALLOWANCE:
        verdict = 'hold'
        why = ('retain %.2f/%.2fd (%.4f%%/d) beats %s %.2f + %.2f allowance'
               % (retain, hold_days, 100 * retain / L / hold_days,
                  alt_desc, alt_gain, USD_ALLOWANCE))
    else:
        verdict = 'contingent'
        why = ('retain %.2f within %.2f of %s %.2f: bankable if cash needed'
               % (retain, USD_ALLOWANCE, alt_desc, alt_gain))
    return verdict, {'basket': name, 'G': G, 'L': L, 'retain': retain,
                     'retain_per_day': round(retain / hold_days, 2),
                     'alt_gain': alt_gain, 'alt': alt_desc,
                     'edge_vs_cost': edge_vs_cost,
                     'verdict': verdict, 'why': why}


def rank(flags, hold_days=HOLD_DAYS):
    """flags: [(name, floor, size, qty, proceeds, cost, replacement?)]."""
    out = []
    for f in flags:
        verdict, detail = analyze(*f, hold_days=hold_days) \
            if len(f) <= 6 else analyze(*f[:6], replacement=f[6],
                                        hold_days=hold_days)
        out.append((verdict, detail))
    order = {'exit': 0, 'contingent': 1, 'hold': 2, None: 3}
    out.sort(key=lambda t: (order[t[0]],
                            -(t[1].get('retain') or 0)
                            if t[0] == 'exit' else (t[1].get('retain') or 0)))
    return out
