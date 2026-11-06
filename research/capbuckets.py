"""Capacity decision on separately labeled buckets (backlog item 109). Pure.

fourq mixes depth proceeds (top) with marks (tail) into one liquidation
number; capuse adds contingent premiums into `locked_edge` and hides a
5% haircut inside `worst_loss`. This module keeps every bucket labeled
and reconciles them BEFORE any sizing decision:
- guaranteed_floor: paired basket units x $1 (normal single-winner).
- premium_contingent: short premiums kept IFF no upset (NOT locked).
- stress_loss: short tails + haircut allowance (stated, not predicted).
- unvalued: positions/books that could not be priced (listed, never
  silently marked).
- max_loss_bound: tails + (cash_tied - floor) if ALL floors break
  (basis catastrophe bound — the true worst case, kept apart from the
  modeled stress).
- executable_only: depth proceeds with zero marks substitution;
  unpriced legs land in unvalued.
A sizing gate may proceed only on guaranteed + contingent-vs-stress
with unvalued explicitly accepted, never on a blended total.
"""


def label_book(paired_units, floor_per_unit, short_premiums, short_tails,
               cash_tied, haircut_rate=0.05):
    """Core buckets from verified inputs. All numeric else refusal."""
    try:
        pu = float(paired_units)
        fpu = float(floor_per_unit)
        prem = float(short_premiums)
        tails = float(short_tails)
        cash = float(cash_tied)
        h = float(haircut_rate)
    except (TypeError, ValueError):
        return None
    if min(pu, fpu, prem, tails, cash, h) < 0:
        return None
    guaranteed = round(pu * fpu, 2)
    contingent = round(prem, 2)
    stress = round(tails + h * cash, 2)
    max_loss = round(tails + max(cash - guaranteed, 0.0), 2)
    return {'guaranteed_floor': guaranteed,
            'premium_contingent': contingent,
            'stress_loss': stress,
            'max_loss_bound': max_loss,
            'unvalued': []}


def executable_only(proceeds_by_leg, missing_legs):
    """Depth proceeds with zero marks substitution. missing_legs listed
    as unvalued (never priced by assumption)."""
    try:
        total = round(sum(float(v) for v in proceeds_by_leg), 2)
    except (TypeError, ValueError):
        return None
    return {'executable_proceeds': total,
            'unvalued': [str(e) for e in missing_legs]}


def gate(labels, required_edge=0.0):
    """ sizing gate: guaranteed + contingent must clear stress by the
    required edge, with unvalued EXPLICITLY accepted (caller passes
    accepted=True in labels). Returns (go, detail)."""
    try:
        g = float(labels['guaranteed_floor'])
        c = float(labels['premium_contingent'])
        s = float(labels['stress_loss'])
    except (KeyError, TypeError, ValueError):
        return False, {'reason': 'unlabeled buckets'}
    if labels.get('unvalued_accepted') is not True and labels.get('unvalued'):
        return False, {'reason': 'unvalued inventory not accepted'}
    margin = round(g + c - s, 2)
    if margin >= required_edge:
        return True, {'margin': margin}
    return False, {'margin': margin, 'reason': 'below required edge'}
